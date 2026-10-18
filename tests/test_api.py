import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api.main as api
from agent.graph import build_graph
from api.chats import ChatStore
from api.files import FileStore
from api.limits import Limits
from tests.test_shortlist import FakeClaude, FakeWriter, propose

ME = {"X-Client-Id": "client-aaaa-1111"}
OTHER = {"X-Client-Id": "client-bbbb-2222"}


def events(resp) -> list[tuple[str, dict]]:
    out = []
    for chunk in resp.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def text(t):
    return ([{"type": "text", "text": t}], "end_turn")


class Recorder(FakeClaude):
    """FakeClaude that also records which model each call asked for."""

    def __init__(self, *responses):
        super().__init__(*responses)
        self.models = []

    def create(self, messages, model=None):
        self.models.append(model)
        return super().create(messages, model)


@pytest.fixture
def client(warehouse, passage_index, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "limits", Limits(per_minute=100, ip_daily_usd=10, daily_usd=10))
    api.set_stores(ChatStore(tmp_path / "chats.sqlite"), FileStore(tmp_path / "uploads"))
    yield TestClient(api.app)
    api.set_graph(None)
    api.set_stores(None, None)


def use(fake):
    api.set_graph(build_graph(fake, report_writer=FakeWriter()))
    return fake


# --- data endpoints ------------------------------------------------------------------------------

def test_health_and_meta(client):
    assert client.get("/api/health").json()["data_as_of"] == "2026-07-06"
    m = client.get("/api/meta").json()
    assert m["active_players"] == 6 and m["event_players"] == 5


def test_data_endpoints(client):
    assert client.get("/api/players/find", params={"q": "Pablo Builder"}).json()["candidates"][0]["player_id"] == 3
    assert client.get("/api/players/999").status_code == 404
    assert client.get("/api/players/5/similar").json()["notes"]
    assert client.get("/api/compare", params={"ids": "3"}).status_code == 400


def test_models_list_offers_claude_and_local(client, monkeypatch):
    monkeypatch.setattr("agent.models.ollama_url", lambda: "http://127.0.0.1:9")  # nothing listening
    ms = client.get("/api/models").json()["models"]
    assert [m["id"] for m in ms[:3]] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
    local = [m for m in ms if m["provider"] == "ollama"]
    assert local and not local[0]["available"] and "Ollama" in local[0]["reason"]


# --- chats ---------------------------------------------------------------------------------------

def test_client_id_required(client):
    assert client.get("/api/chats").status_code == 400
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 400


def test_new_chat_streams_and_is_saved(client):
    fake = use(Recorder(
        ([{"type": "tool_use", "id": "t1", "name": "search_players", "input": {"position_groups": ["CB"]}}], "tool_use"),
        text("Pablo Builder leads.")))
    ev = events(client.post("/api/chat", headers=ME, json={"message": "find me a CB", "model": "claude-sonnet-5-5"}))
    assert [k for k, _ in ev] == ["meta", "step", "result", "answer", "done"]
    chat_id = ev[0][1]["chat_id"]
    assert fake.models == ["claude-sonnet-5-5", "claude-sonnet-5-5"]

    listing = client.get("/api/chats", headers=ME).json()
    assert [c["chat_id"] for c in listing["chats"]] == [chat_id]
    assert listing["chats"][0]["title"] == "find me a CB" and listing["chats"][0]["model"] == "claude-sonnet-5-5"
    assert client.get("/api/chats", headers=OTHER).json()["chats"] == []  # scoped to the client
    assert client.get(f"/api/chats/{chat_id}", headers=OTHER).status_code == 404

    full = client.get(f"/api/chats/{chat_id}", headers=ME).json()
    (turn,) = full["turns"]
    assert turn["text"] == "find me a CB" and turn["answer"] == "Pablo Builder leads."
    assert turn["steps"][0]["summary"] == "5 matches" and turn["table"]["rows"][0]["player_id"] == 6


def test_unknown_model_rejected(client):
    use(FakeClaude(text("x")))
    assert client.post("/api/chat", headers=ME, json={"message": "hi", "model": "gpt-9"}).status_code == 400


def test_edit_forks_from_unchanged_prefix(client):
    fake = use(FakeClaude(text("first answer"), text("second answer"), text("edited answer")))
    ev = events(client.post("/api/chat", headers=ME, json={"message": "question one"}))
    chat_id = ev[0][1]["chat_id"]
    events(client.post("/api/chat", headers=ME, json={"message": "question two", "chat_id": chat_id}))

    ev = events(client.post("/api/chat", headers=ME,
                            json={"message": "question two, but cheaper", "chat_id": chat_id, "edit_turn": 1}))
    assert dict(ev)["answer"]["text"] == "edited answer" and dict(ev)["meta"]["turn"] == 1
    # The model saw the original first turn, byte for byte, then the edited question.
    sent = fake.seen[-1]
    assert sent[0] == {"role": "user", "content": "question one"}
    assert sent[1]["content"] == [{"type": "text", "text": "first answer"}]
    assert sent[2] == {"role": "user", "content": "question two, but cheaper"}

    turns = client.get(f"/api/chats/{chat_id}", headers=ME).json()["turns"]
    assert [t["text"] for t in turns] == ["question one", "question two, but cheaper"]
    assert client.post("/api/chat", headers=ME,
                       json={"message": "x", "chat_id": chat_id, "edit_turn": 9}).status_code == 400


def test_folders_rename_move_delete(client):
    use(FakeClaude(text("ok")))
    chat_id = events(client.post("/api/chat", headers=ME, json={"message": "left-backs"}))[0][1]["chat_id"]
    f = client.post("/api/folders", headers=ME, json={"name": "Summer window"}).json()
    assert client.patch(f"/api/chats/{chat_id}", headers=ME,
                        json={"folder_id": f["folder_id"], "move": True}).json()["folder_id"] == f["folder_id"]
    assert client.patch(f"/api/chats/{chat_id}", headers=ME, json={"title": "LB targets"}).json()["title"] == "LB targets"
    assert client.patch(f"/api/folders/{f['folder_id']}", headers=ME, json={"name": "January"}).status_code == 200
    assert client.patch(f"/api/chats/{chat_id}", headers=OTHER, json={"title": "x"}).status_code == 404
    assert client.patch(f"/api/chats/{chat_id}", headers=ME,
                        json={"folder_id": "nope", "move": True}).status_code == 404

    assert client.delete(f"/api/folders/{f['folder_id']}", headers=ME).status_code == 200
    listing = client.get("/api/chats", headers=ME).json()
    assert listing["folders"] == [] and listing["chats"][0]["folder_id"] is None  # chat kept, unfiled
    assert client.delete(f"/api/chats/{chat_id}", headers=ME).status_code == 200
    assert client.get("/api/chats", headers=ME).json()["chats"] == []


def test_shortlist_pause_resume_and_report_saved(client):
    use(FakeClaude((propose(3, 4), "tool_use"), text("Report ready.")))
    ev = events(client.post("/api/chat", headers=ME, json={"message": "reports on CBs"}))
    chat_id = ev[0][1]["chat_id"]
    assert [k for k, _ in ev] == ["meta", "step", "shortlist", "done"]
    assert client.get(f"/api/chats/{chat_id}", headers=ME).json()["pending"]["candidates"][0]["player_id"] == 3
    assert client.post("/api/chat", headers=ME, json={"message": "next", "chat_id": chat_id}).status_code == 409
    assert client.get("/api/shortlists", headers=ME).json()["waiting"][0]["chat_id"] == chat_id

    ev = events(client.post("/api/chat/resume", headers=ME, json={"chat_id": chat_id, "approved": [3]}))
    assert dict(ev)["report"]["player_id"] == 3 and [k for k, _ in ev][-2:] == ["answer", "done"]
    turn = client.get(f"/api/chats/{chat_id}", headers=ME).json()["turns"][0]
    assert turn["reports"][0]["player_id"] == 3  # stored per turn, survives later turns
    assert client.get("/api/shortlists", headers=ME).json()["written"][0]["reports"][0]["player_id"] == 3


# --- uploads -------------------------------------------------------------------------------------

def _png(size=(2400, 1200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


def test_upload_kinds_and_attachment_blocks(client):
    img = client.post("/api/files", headers=ME, files={"file": ("pitch.png", _png(), "image/png")}).json()
    assert img["kind"] == "image"
    w, h = Image.open(io.BytesIO(api.files().get("client-aaaa-1111", img["file_id"])[1])).size
    assert max(w, h) == 1568  # resized to the size Claude reads best

    csv = client.post("/api/files", headers=ME, files={"file": ("shortlist.csv", b"name,age\nPablo,21\n", "text/csv")}).json()
    assert csv["kind"] == "text"
    pdf_bad = client.post("/api/files", headers=ME, files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert pdf_bad.status_code == 400
    video = client.post("/api/files", headers=ME, files={"file": ("clip.mp4", b"\x00" * 10, "video/mp4")})
    assert video.status_code == 415 and "frames" in video.json()["detail"]
    assert client.post("/api/files", headers=ME, files={"file": ("a.exe", b"MZ", "application/octet-stream")}).status_code == 415

    fake = use(FakeClaude(text("I see a pitch.")))
    ev = events(client.post("/api/chat", headers=ME,
                            json={"message": "what is this?", "file_ids": [img["file_id"], csv["file_id"]]}))
    sent = fake.seen[0][0]["content"]
    assert sent[0]["text"] == "Attached files: pitch.png (image); shortlist.csv (text)"
    assert sent[1]["type"] == "image" and sent[2]["type"] == "document" and "Pablo,21" in sent[2]["source"]["data"]
    assert sent[-1] == {"type": "text", "text": "what is this?"}
    turn = client.get(f"/api/chats/{ev[0][1]['chat_id']}", headers=ME).json()["turns"][0]
    assert turn["text"] == "what is this?" and turn["attachments"] == ["pitch.png (image)", "shortlist.csv (text)"]

    # Another client can't attach my file.
    r = client.post("/api/chat", headers=OTHER, json={"message": "steal", "file_ids": [img["file_id"]]})
    assert r.status_code == 400


# --- limits --------------------------------------------------------------------------------------

def test_rate_limit_and_budget(client, monkeypatch):
    use(FakeClaude(*[text("ok")] * 5))
    monkeypatch.setattr(api, "limits", Limits(per_minute=2, ip_daily_usd=10, daily_usd=10))
    assert client.post("/api/chat", headers=ME, json={"message": "hi"}).status_code == 200
    assert client.post("/api/chat", headers=ME, json={"message": "hi"}).status_code == 200
    r = client.post("/api/chat", headers=ME, json={"message": "hi"})
    assert r.status_code == 429 and "a minute" in r.json()["detail"]


def test_chat_without_llm_is_503_unless_local(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/chat", headers=ME, json={"message": "find me a CB"})
    assert r.status_code == 503 and "local model" in r.json()["detail"]
