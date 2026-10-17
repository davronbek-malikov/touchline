"""Scout notes: written in the app, stored here, and indexed for search.

SQLite for local development; deployment swaps in Postgres behind the same functions.
"""
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from data.config import ROOT

STATE = ROOT / "state"
_override: Path | None = None


def set_db(path: Path | None) -> None:
    global _override
    _override = path


def _con() -> sqlite3.Connection:
    path = _override or Path(os.environ.get("TOUCHLINE_NOTES_DB", STATE / "notes.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS notes (
        note_id TEXT PRIMARY KEY, player_id INTEGER NOT NULL, author TEXT NOT NULL,
        created_at TEXT NOT NULL, context TEXT, text TEXT NOT NULL)""")
    return con


def add_note(player_id: int, text: str, author: str = "scout", context: str | None = None, index: bool = True) -> dict:
    """Save a note and (by default) index it immediately so searches find it."""
    text = text.strip()
    if not text:
        raise ValueError("empty note")
    note = {"note_id": str(uuid.uuid4()), "player_id": int(player_id), "author": author,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "context": context, "text": text}
    with _con() as con:
        con.execute("INSERT INTO notes VALUES (:note_id, :player_id, :author, :created_at, :context, :text)", note)
    if index:
        from rag.index import get_index
        get_index().upsert(note_chunks([note]))
    return note


def list_notes(player_id: int | None = None) -> list[dict]:
    with _con() as con:
        if player_id is None:
            rows = con.execute("SELECT * FROM notes ORDER BY created_at").fetchall()
        else:
            rows = con.execute("SELECT * FROM notes WHERE player_id = ? ORDER BY created_at", [player_id]).fetchall()
    return [dict(r) for r in rows]


def note_chunks(notes: list[dict]) -> list[dict]:
    """One note is one chunk."""
    return [{
        "chunk_id": n["note_id"], "player_id": n["player_id"], "source": "scout_note", "source_id": n["note_id"],
        "title": f"Scout note by {n['author']}, {n['created_at'][:10]}" + (f" ({n['context']})" if n.get("context") else ""),
        "url": None, "licence": "internal", "text": n["text"], "created_at": n["created_at"],
    } for n in notes]
