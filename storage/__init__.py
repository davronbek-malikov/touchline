"""One small SQL layer for app state: SQLite locally, Postgres when DATABASE_URL is set.

Stores write portable SQL with "?" placeholders and ON CONFLICT upserts (both engines
support them); the Postgres adapter converts placeholders. Free hosts such as Render
have no persistent disk, so deployed state (chats, notes, uploads, agent threads)
lives in Postgres.
"""
import os
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path


class Sql:
    dialect = "sqlite"

    def q(self, sql: str, args=()) -> list[dict]: ...
    def x(self, sql: str, args=()) -> int: ...
    def script(self, sqlite: str, postgres: str | None = None) -> None: ...


class SqliteSql(Sql):
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.lock = threading.Lock()

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def x(self, sql, args=()):
        with self.lock, self.con:
            return self.con.execute(sql, args).rowcount

    def script(self, sqlite, postgres=None):
        with self.lock, self.con:
            self.con.executescript(sqlite)


class PostgresSql(Sql):
    dialect = "postgres"

    def __init__(self, url: str):
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        # prepare_threshold=None: safe behind transaction poolers (Neon, Supabase, PgBouncer).
        self.pool = ConnectionPool(url, min_size=1, max_size=5, open=True,
                                   kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None})

    @staticmethod
    def _pg(sql: str) -> str:
        return sql.replace("?", "%s")

    def q(self, sql, args=()):
        with self.pool.connection() as c:
            return [dict(r) for r in c.execute(self._pg(sql), args).fetchall()]

    def x(self, sql, args=()):
        with self.pool.connection() as c:
            return c.execute(self._pg(sql), args).rowcount

    def script(self, sqlite, postgres=None):
        with self.pool.connection() as c:
            for stmt in (postgres or sqlite).split(";"):
                if stmt.strip():
                    c.execute(stmt)


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


@lru_cache(maxsize=None)
def _postgres(url: str) -> PostgresSql:
    return PostgresSql(url)


def open_sql(sqlite_path: Path) -> Sql:
    """Postgres when DATABASE_URL is set (one shared pool), else a SQLite file."""
    url = database_url()
    return _postgres(url) if url else SqliteSql(sqlite_path)
