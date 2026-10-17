import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from agent import cli
from agent.graph import build_graph, user_turn
from tests.test_shortlist import FakeClaude, FakeWriter, propose


def test_cli_run_handles_shortlist_interrupt(warehouse, monkeypatch, capsys, tmp_path):
    answers = iter(["1", "keep it short"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    fake = FakeClaude((propose(3, 4), "tool_use"), ([{"type": "text", "text": "Done."}], "end_turn"))
    writer = FakeWriter()
    saver = SqliteSaver(sqlite3.connect(tmp_path / "t.sqlite", check_same_thread=False))
    g = build_graph(fake, checkpointer=saver, report_writer=writer)

    final = cli.run(g, "t1", user_turn("reports on two CBs"))
    out = capsys.readouterr().out
    assert final == "Done."
    assert "Proposed shortlist" in out and "Pablo Builder" in out and "SCOUTING REPORT" in out
    assert [pid for pid, _ in writer.calls] == [3]


def test_paused_thread_survives_restart(warehouse, tmp_path):
    db = tmp_path / "threads.sqlite"
    g1 = build_graph(FakeClaude((propose(3), "tool_use")), report_writer=FakeWriter(),
                     checkpointer=SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    g1.invoke(user_turn("report on Pablo"), {"configurable": {"thread_id": "later"}})

    # A new process: fresh graph, same SQLite file.
    writer = FakeWriter()
    g2 = build_graph(FakeClaude(([{"type": "text", "text": "Written."}], "end_turn")), report_writer=writer,
                     checkpointer=SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    state = g2.get_state({"configurable": {"thread_id": "later"}})
    assert state.next == ("review_shortlist",)
    assert state.interrupts[0].value["candidates"][0]["name"] == "Pablo Builder"
    from langgraph.types import Command
    out = g2.invoke(Command(resume={"approved": [3]}), {"configurable": {"thread_id": "later"}})
    assert out["final_text"] == "Written." and [pid for pid, _ in writer.calls] == [3]
