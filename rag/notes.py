"""Scout notes: written in the app, stored here, and indexed for search.

SQLite locally; Postgres when DATABASE_URL is set (see storage).
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from data.config import ROOT
from storage import Sql, SqliteSql, open_sql

STATE = ROOT / "state"
SCHEMA = """CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT PRIMARY KEY, player_id INTEGER NOT NULL, author TEXT NOT NULL,
    created_at TEXT NOT NULL, context TEXT, text TEXT NOT NULL)"""

_override: Path | None = None
_sql: Sql | None = None


def set_db(path: Path | None) -> None:
    """Use a SQLite file at `path` (tests); None goes back to the default."""
    global _override, _sql
    _override, _sql = path, None


def _db() -> Sql:
    global _sql
    if _sql is None:
        if _override is not None:
            _sql = SqliteSql(_override)
        else:
            _sql = open_sql(Path(os.environ.get("TOUCHLINE_NOTES_DB", STATE / "notes.sqlite")))
        _sql.script(SCHEMA)
    return _sql


def add_note(player_id: int, text: str, author: str = "scout", context: str | None = None, index: bool = True) -> dict:
    """Save a note and (by default) index it immediately so searches find it."""
    text = text.strip()
    if not text:
        raise ValueError("empty note")
    note = {"note_id": str(uuid.uuid4()), "player_id": int(player_id), "author": author,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "context": context, "text": text}
    _db().x("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)",
            (note["note_id"], note["player_id"], note["author"], note["created_at"], note["context"], note["text"]))
    if index:
        from rag.index import get_index
        get_index().upsert(note_chunks([note]))
    return note


def list_notes(player_id: int | None = None) -> list[dict]:
    if player_id is None:
        return _db().q("SELECT * FROM notes ORDER BY created_at")
    return _db().q("SELECT * FROM notes WHERE player_id = ? ORDER BY created_at", (player_id,))


def note_chunks(notes: list[dict]) -> list[dict]:
    """One note is one chunk."""
    return [{
        "chunk_id": n["note_id"], "player_id": n["player_id"], "source": "scout_note", "source_id": n["note_id"],
        "title": f"Scout note by {n['author']}, {n['created_at'][:10]}" + (f" ({n['context']})" if n.get("context") else ""),
        "url": None, "licence": "internal", "text": n["text"], "created_at": n["created_at"],
    } for n in notes]
