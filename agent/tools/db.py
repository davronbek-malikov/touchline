"""Read-only access to the warehouse. Tools take a cursor per call."""
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import duckdb

from data.config import WAREHOUSE


class ToolError(Exception):
    """A tool call that can't be answered; returned to Claude as an is_error tool_result."""


_override: Path | None = None


def set_warehouse(path: Path | None) -> None:
    """Point tools at another warehouse (tests)."""
    global _override
    _override = path
    _connection.cache_clear()


@lru_cache(maxsize=1)
def _connection() -> duckdb.DuckDBPyConnection:
    path = _override or Path(os.environ.get("TOUCHLINE_WAREHOUSE", WAREHOUSE))
    if not path.exists():
        raise ToolError(f"warehouse not found at {path}; run python -m data.build_warehouse")
    return duckdb.connect(str(path), read_only=True)


def cursor() -> duckdb.DuckDBPyConnection:
    return _connection().cursor()


def rows(sql: str, params: list | None = None) -> list[dict]:
    cur = cursor()
    res = cur.execute(sql, params or [])
    cols = [d[0] for d in res.description]
    return [dict(zip(cols, (_clean(v) for v in r))) for r in res.fetchall()]


def _clean(v):
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return round(v, 2)
    return v


def data_as_of() -> str:
    return cursor().execute("SELECT value FROM meta WHERE key = 'data_as_of'").fetchone()[0]
