"""The deployed storage path, on a real (embedded) Postgres: chats, reports, uploads,
notes, and LangGraph threads that survive a restart."""
import pytest

pgserver = pytest.importorskip("pgserver")

from api.chats import ChatStore  # noqa: E402
from api.files import SqlFileStore  # noqa: E402
from storage import PostgresSql  # noqa: E402


@pytest.fixture(scope="module")
def pg_url(tmp_path_factory):
    srv = pgserver.get_server(str(tmp_path_factory.mktemp("pg")), cleanup_mode="stop")
    yield srv.get_uri()


@pytest.fixture
def sql(pg_url):
    s = PostgresSql(pg_url)
    for t in ("reports", "chats", "folders", "uploads", "notes"):
        s.x(f"DROP TABLE IF EXISTS {t}")
    yield s
    s.pool.close()


def test_chat_store_on_postgres(sql):
    store = ChatStore(sql)
    c = store.create("owner-1", "Left-backs under 21", "claude-opus-5-5")
    f = store.add_folder("owner-1", "Summer")
    assert store.update("owner-1", c["chat_id"], folder_id=f["folder_id"], move=True)
    assert store.chats("owner-1")[0]["folder_id"] == f["folder_id"]
    assert store.chats("someone-else") == []

    store.save_report(c["chat_id"], c["thread_id"], 0, {"player_id": 3, "name": "A"})
    store.save_report(c["chat_id"], c["thread_id"], 0, {"player_id": 4, "name": "B"})
    store.save_report(c["chat_id"], c["thread_id"], 0, {"player_id": 3, "name": "A v2"})  # upsert
    assert [r["name"] for r in store.reports(c["thread_id"])[0]] == ["A v2", "B"]
    store.copy_reports(c["chat_id"], c["thread_id"], "new-thread", before_turn=1)
    assert len(store.reports("new-thread")[0]) == 2

    assert store.delete_folder("owner-1", f["folder_id"]) and store.chats("owner-1")[0]["folder_id"] is None
    assert store.delete("owner-1", c["chat_id"]) and store.chats("owner-1") == []


def test_uploads_on_postgres(sql):
    files = SqlFileStore(sql)
    meta = files.save("owner-1", "notes.csv", "text/csv", b"name,age\nPablo,21\n")
    got_meta, data = files.get("owner-1", meta["file_id"])
    assert got_meta["name"] == "notes.csv" and data == b"name,age\nPablo,21\n"
    with pytest.raises(ValueError):
        files.get("owner-2", meta["file_id"])
    blocks, labels = files.blocks("owner-1", [meta["file_id"]])
    assert labels == ["notes.csv (text)"] and "Pablo,21" in blocks[0]["source"]["data"]


def test_notes_on_postgres(sql, pg_url, monkeypatch):
    import rag.notes as notes
    monkeypatch.setenv("DATABASE_URL", pg_url)
    notes.set_db(None)
    n = notes.add_note(3, "Scans before receiving", author="D", index=False)
    assert notes.list_notes(3)[-1]["note_id"] == n["note_id"]
    notes.set_db(None)


def test_paused_shortlist_survives_restart_on_postgres(warehouse, pg_url):
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.types import Command
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from agent.graph import build_graph, user_turn
    from tests.test_shortlist import FakeClaude, FakeWriter, propose

    def saver():
        pool = ConnectionPool(pg_url, min_size=1, max_size=2, open=True,
                              kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None})
        s = PostgresSaver(pool)
        s.setup()
        return s, pool

    s1, p1 = saver()
    g1 = build_graph(FakeClaude((propose(3), "tool_use")), checkpointer=s1, report_writer=FakeWriter())
    g1.invoke(user_turn("report on Pablo"), {"configurable": {"thread_id": "pg-thread"}})
    p1.close()

    s2, p2 = saver()  # a new process after a restart: only Postgres remembers
    writer = FakeWriter()
    g2 = build_graph(FakeClaude(([{"type": "text", "text": "Done."}], "end_turn")), checkpointer=s2,
                     report_writer=writer)
    cfg = {"configurable": {"thread_id": "pg-thread"}}
    assert g2.get_state(cfg).next == ("review_shortlist",)
    out = g2.invoke(Command(resume={"approved": [3]}), cfg)
    assert out["final_text"] == "Done." and [pid for pid, _ in writer.calls] == [3]
    p2.close()
