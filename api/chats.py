"""Chats and folders, scoped to an anonymous client id (a random id the browser keeps).

A chat points at the LangGraph thread holding its messages. Editing an earlier
message or regenerating an answer starts a new thread seeded with the unchanged
prefix, and the chat moves to it; history before the edit is never rewritten.
Reports are stored here per turn because graph state only keeps the latest turn's.
"""
import json
import uuid
from datetime import datetime, timezone

from storage import Sql

SCHEMA = """
    CREATE TABLE IF NOT EXISTS folders (
        folder_id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chats (
        chat_id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, folder_id TEXT,
        thread_id TEXT NOT NULL, model TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS reports (
        seq BIGINT, chat_id TEXT NOT NULL, thread_id TEXT NOT NULL, turn INTEGER NOT NULL,
        player_id INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY (thread_id, turn, player_id));
    CREATE INDEX IF NOT EXISTS chats_owner ON chats(owner, updated_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class ChatStore:
    def __init__(self, sql: Sql):
        self.sql = sql
        sql.script(SCHEMA)

    # --- folders -------------------------------------------------------------------------------
    def folders(self, owner: str) -> list[dict]:
        return self.sql.q("SELECT folder_id, name, created_at FROM folders WHERE owner = ? ORDER BY name", (owner,))

    def add_folder(self, owner: str, name: str) -> dict:
        f = {"folder_id": uuid.uuid4().hex[:12], "name": name.strip()[:80] or "Untitled folder", "created_at": _now()}
        self.sql.x("INSERT INTO folders VALUES (?, ?, ?, ?)", (f["folder_id"], owner, f["name"], f["created_at"]))
        return f

    def rename_folder(self, owner: str, folder_id: str, name: str) -> bool:
        return self.sql.x("UPDATE folders SET name = ? WHERE folder_id = ? AND owner = ?",
                          (name.strip()[:80] or "Untitled folder", folder_id, owner)) > 0

    def delete_folder(self, owner: str, folder_id: str) -> bool:
        """Chats in the folder are kept and moved back to the main list."""
        self.sql.x("UPDATE chats SET folder_id = NULL WHERE folder_id = ? AND owner = ?", (folder_id, owner))
        return self.sql.x("DELETE FROM folders WHERE folder_id = ? AND owner = ?", (folder_id, owner)) > 0

    # --- chats -----------------------------------------------------------------------------------
    def chats(self, owner: str) -> list[dict]:
        return self.sql.q("""SELECT chat_id, title, folder_id, model, created_at, updated_at FROM chats
                             WHERE owner = ? ORDER BY updated_at DESC LIMIT 500""", (owner,))

    def get(self, owner: str, chat_id: str) -> dict | None:
        rows = self.sql.q("SELECT * FROM chats WHERE chat_id = ? AND owner = ?", (chat_id, owner))
        return rows[0] if rows else None

    def create(self, owner: str, title: str, model: str | None, folder_id: str | None = None) -> dict:
        now = _now()
        c = {"chat_id": uuid.uuid4().hex[:12], "title": _title(title), "folder_id": folder_id,
             "thread_id": uuid.uuid4().hex, "model": model, "created_at": now, "updated_at": now}
        self.sql.x("INSERT INTO chats VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (c["chat_id"], owner, c["title"], folder_id, c["thread_id"], model, now, now))
        return c

    def touch(self, owner: str, chat_id: str, model: str | None = None, thread_id: str | None = None) -> None:
        sets, args = ["updated_at = ?"], [_now()]
        if model is not None:
            sets.append("model = ?")
            args.append(model)
        if thread_id is not None:
            sets.append("thread_id = ?")
            args.append(thread_id)
        self.sql.x(f"UPDATE chats SET {', '.join(sets)} WHERE chat_id = ? AND owner = ?", (*args, chat_id, owner))

    def update(self, owner: str, chat_id: str, title: str | None = None, folder_id: str | None = None,
               move: bool = False) -> bool:
        if folder_id is not None and not self.sql.q("SELECT 1 AS x FROM folders WHERE folder_id = ? AND owner = ?",
                                                    (folder_id, owner)):
            return False
        sets, args = [], []
        if title is not None:
            sets.append("title = ?")
            args.append(_title(title))
        if move:
            sets.append("folder_id = ?")
            args.append(folder_id)
        if not sets:
            return self.get(owner, chat_id) is not None
        return self.sql.x(f"UPDATE chats SET {', '.join(sets)} WHERE chat_id = ? AND owner = ?",
                          (*args, chat_id, owner)) > 0

    def delete(self, owner: str, chat_id: str) -> bool:
        if self.get(owner, chat_id) is None:
            return False
        self.sql.x("DELETE FROM reports WHERE chat_id = ?", (chat_id,))
        return self.sql.x("DELETE FROM chats WHERE chat_id = ? AND owner = ?", (chat_id, owner)) > 0

    # --- reports ---------------------------------------------------------------------------------
    def save_report(self, chat_id: str, thread_id: str, turn: int, report: dict) -> None:
        self.sql.x("""INSERT INTO reports (seq, chat_id, thread_id, turn, player_id, body)
                      VALUES (?, ?, ?, ?, ?, ?)
                      ON CONFLICT (thread_id, turn, player_id) DO UPDATE SET body = excluded.body""",
                   (_seq(), chat_id, thread_id, turn, report["player_id"], json.dumps(report, ensure_ascii=False)))

    def reports(self, thread_id: str) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for r in self.sql.q("SELECT turn, body FROM reports WHERE thread_id = ? ORDER BY turn, seq", (thread_id,)):
            out.setdefault(r["turn"], []).append(json.loads(r["body"]))
        return out

    def copy_reports(self, chat_id: str, old_thread: str, new_thread: str, before_turn: int) -> None:
        """Keep reports from the turns an edit didn't touch."""
        self.sql.x("""INSERT INTO reports (seq, chat_id, thread_id, turn, player_id, body)
                      SELECT seq, chat_id, ?, turn, player_id, body FROM reports WHERE thread_id = ? AND turn < ?
                      ON CONFLICT (thread_id, turn, player_id) DO NOTHING""", (new_thread, old_thread, before_turn))


_counter = [0]


def _seq() -> int:
    """Insertion order for reports within a turn (microsecond clock, monotonic in-process)."""
    now = int(datetime.now(timezone.utc).timestamp() * 1e6)
    _counter[0] = max(_counter[0] + 1, now)
    return _counter[0]


def _title(text: str) -> str:
    t = " ".join(text.split())
    return (t[:60] + "…") if len(t) > 60 else (t or "New chat")
