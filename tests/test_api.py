import json

import pytest
from fastapi.testclient import TestClient

import api.main as api
from agent.graph import build_graph
from api.limits import Limits
from tests.test_shortlist import FakeClaude, FakeWriter, propose


def events(resp) -> list[tuple[str, dict]]:
    out = []
    for chunk in resp.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def client(warehouse, passage_index, monkeypatch):
    monkeypatch.setattr(api, "limits", Limits(per_minute=100, ip_daily_usd=10, daily_usd=10))
    yield TestClient(api.app)
    api.set_graph(None)


def test_health_and_meta(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["data_as_of"] == "2026-07-06"
    m = client.get("/api/meta").json()
    assert m["active_players"] == 6 and m["event_players"] == 5 and len(m["examples"]) == 6


def test_data_endpoints(client):
    assert client.get("/api/players/find", params={"q": "Pablo Builder"}).json()["candidates"][0]["player_id"] == 3
    assert client.get("/api/players/3").json()["player"]["name"] == "Pablo Builder"
    assert client.get("/api/players/999").status_code == 404
    assert client.get("/api/players/3/similar").json()["players"]
    assert client.get("/api/players/5/similar").json()["notes"]  # market-only: explained, not a 500
    assert len(client.get("/api/compare", params={"ids": "3,4"}).json()["players"]) == 2
    assert client.get("/api/compare", params={"ids": "3"}).status_code == 400


def test_notes_roundtrip(client):
    r = client.post("/api/notes", json={"player_id": 4, "text": "Wins every header, slow to turn.", "author": "D"})
    assert r.status_code == 200
    assert client.get("/api/players/4/notes").json()["notes"][-1]["text"] == "Wins every header, slow to turn."
    assert client.post("/api/notes", json={"player_id": 999, "text": "ghost"}).status_code == 404


def test_chat_without_llm_is_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/chat", json={"message": "find me a CB"})
    assert r.status_code == 503 and "API key" in r.json()["detail"]


def test_chat_streams_steps_then_answer(client):
    fake = FakeClaude(
        ([{"type": "tool_use", "id": "t1", "name": "search_players", "input": {"position_groups": ["CB"]}}], "tool_use"),
        ([{"type": "text", "text": "Pablo Builder leads."}], "end_turn"))
    api.set_graph(build_graph(fake, report_writer=FakeWriter()))
    ev = events(client.post("/api/chat", json={"message": "find me a CB"}))
    kinds = [k for k, _ in ev]
    assert kinds == ["meta", "step", "result", "answer", "done"]
    result = ev[2][1]
    assert result["summary"] == "5 matches" and result["data"][0]["name"] == "Pablo Builder Senior"
    assert ev[3][1]["text"] == "Pablo Builder leads." and ev[4][1]["status"] == "complete"


def test_shortlist_pause_and_resume(client):
    fake = FakeClaude((propose(3, 4), "tool_use"), ([{"type": "text", "text": "Report ready."}], "end_turn"))
    api.set_graph(build_graph(fake, report_writer=FakeWriter()))
    ev = events(client.post("/api/chat", json={"message": "reports on CBs", "thread_id": "th1"}))
    assert [k for k, _ in ev] == ["meta", "step", "shortlist", "done"]
    assert ev[2][1]["candidates"][1]["name"] == "Rugged Stopper" and ev[3][1]["status"] == "awaiting_approval"
    assert client.get("/api/threads/th1").json()["pending"]["candidates"][0]["player_id"] == 3

    ev = events(client.post("/api/chat/resume", json={"thread_id": "th1", "approved": [3]}))
    kinds = [k for k, _ in ev]
    assert "report" in kinds and kinds[-2:] == ["answer", "done"]
    assert dict(ev)["report"]["player_id"] == 3
    assert client.post("/api/chat/resume", json={"thread_id": "th1", "approved": [3]}).status_code == 409


def test_rate_limit_and_budget(client, monkeypatch):
    api.set_graph(build_graph(FakeClaude(*[([{"type": "text", "text": "ok"}], "end_turn")] * 5)))
    monkeypatch.setattr(api, "limits", Limits(per_minute=2, ip_daily_usd=10, daily_usd=10))
    assert client.post("/api/chat", json={"message": "hi there"}).status_code == 200
    assert client.post("/api/chat", json={"message": "hi there"}).status_code == 200
    r = client.post("/api/chat", json={"message": "hi there"})
    assert r.status_code == 429 and "a minute" in r.json()["detail"]

    lim = Limits(per_minute=100, ip_daily_usd=0.5, daily_usd=1.0)
    monkeypatch.setattr(api, "limits", lim)
    lim.record("testclient", 0.6)
    assert "You've used today's" in client.post("/api/chat", json={"message": "hi there"}).json()["detail"]
    lim.record("someone-else", 0.5)
    assert lim.check("third-person") == "The demo has used today's budget. It resets at midnight UTC."


def test_limits_reset_each_day():
    now = [1_800_000_000.0]
    lim = Limits(per_minute=100, ip_daily_usd=0.1, daily_usd=1, clock=lambda: now[0])
    lim.record("a", 0.2)
    assert lim.check("a")
    now[0] += 86_400
    assert lim.check("a") is None
