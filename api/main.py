"""Touchline HTTP API: the Scout Assistant over Server-Sent Events, chats and folders,
uploads, and direct data endpoints.

    uvicorn api.main:app --reload

Every chat, folder and upload belongs to an anonymous client id that the browser
sends as X-Client-Id. It scopes a visitor's data; it is not authentication.

Chat events (POST /api/chat, POST /api/chat/resume), one JSON payload each:
    meta       {chat_id, run_id, turn}
    step       {id, name, input}                    a tool call started
    result     {id, name, is_error, summary, data}  its result (data: player rows for tables)
    shortlist  {chat_id, candidates}                paused for the scout's approval
    report     {player_id, name, blocks, sources}   a cited report
    answer     {text}
    error      {message}
    done       {status, cost_usd}
"""
import json
import logging
import os
import re
import sqlite3
import uuid
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from langgraph.types import Command  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agent.claude import EFFORT, PROMPT_VERSION  # noqa: E402
from agent.cost import usage_cost  # noqa: E402
from agent.graph import user_turn  # noqa: E402
from agent.messages import attachment_names, is_user_turn, turn_starts, user_text  # noqa: E402
from agent.models import DEFAULT_MODEL, OLLAMA_PREFIX, is_known, list_models  # noqa: E402
from agent.tools import run_tool  # noqa: E402
from agent.tools.db import data_as_of, rows  # noqa: E402
from api.chats import ChatStore  # noqa: E402
from api.files import FileStore, UploadError  # noqa: E402
from api.limits import Limits, client_ip  # noqa: E402
from data.config import ROOT  # noqa: E402

log = logging.getLogger("touchline.api")
STATE = Path(os.environ.get("TOUCHLINE_STATE", ROOT / "state"))
RESULTS = ROOT / "eval" / "results"
EXAMPLES = [
    "A left-footed centre-back under 23, under €10M, contract ending by 2027",
    "Cheaper alternatives to Florian Wirtz, valued at €40M or less",
    "Ball-playing centre-backs",
    "Compare Rodri, Declan Rice and Granit Xhaka",
    "Wingers aged 21 or under valued between €5M and €20M",
    "Write a scouting report on Jeremie Frimpong",
]

app = FastAPI(title="Touchline API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")],
    allow_origin_regex=os.environ.get("ALLOWED_ORIGIN_REGEX") or None,
    allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"],
)
limits = Limits()
_graph_override = None
_store_override: ChatStore | None = None
_files_override: FileStore | None = None


def set_graph(graph) -> None:
    """Inject a graph (tests)."""
    global _graph_override
    _graph_override = graph


def set_stores(chats: ChatStore | None, files: FileStore | None) -> None:
    """Inject chat and file stores (tests)."""
    global _store_override, _files_override
    _store_override, _files_override = chats, files


@lru_cache(maxsize=1)
def _default_graph():
    from langgraph.checkpoint.sqlite import SqliteSaver

    from agent.graph import build_graph
    from agent.models import ModelRouter

    STATE.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(STATE / "threads.sqlite", check_same_thread=False))
    return build_graph(ModelRouter(), checkpointer=saver)


@lru_cache(maxsize=1)
def _default_store() -> ChatStore:
    return ChatStore(STATE / "chats.sqlite")


@lru_cache(maxsize=1)
def _default_files() -> FileStore:
    return FileStore(STATE / "uploads")


def graph():
    return _graph_override or _default_graph()


def store() -> ChatStore:
    return _store_override or _default_store()


def files() -> FileStore:
    return _files_override or _default_files()


def llm_available() -> bool:
    return _graph_override is not None or bool(os.environ.get("ANTHROPIC_API_KEY"))


def client_id(x_client_id: str | None = Header(None)) -> str:
    if not x_client_id or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", x_client_id):
        raise HTTPException(400, "Missing or invalid X-Client-Id header.")
    return x_client_id


def _tool(name: str, args: dict) -> dict:
    out, is_error = run_tool(name, args)
    data = json.loads(out)
    if is_error:
        raise HTTPException(status_code=404 if "no player" in data.get("error", "") else 400, detail=data["error"])
    return data


# --- data endpoints (no LLM) -------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "data_as_of": data_as_of(), "llm": llm_available(), "model": DEFAULT_MODEL}


@app.get("/api/meta")
def meta():
    counts = rows("""SELECT (SELECT count(*) FROM players WHERE is_active) AS active_players,
                            (SELECT count(*) FROM player_performance) AS event_players""")[0]
    return {"data_as_of": data_as_of(), **counts, "examples": EXAMPLES, "llm": llm_available(),
            "model": DEFAULT_MODEL, "effort": EFFORT, "prompt_version": PROMPT_VERSION, "limits": limits.status()}


@app.get("/api/models")
def models():
    out = list_models()
    if _graph_override is not None:  # tests: a fake agent stands in for every model
        out = [m | {"available": True, "reason": None} if m["provider"] == "anthropic" else m for m in out]
    return {"default": DEFAULT_MODEL, "models": out}


@app.get("/api/players/find")
def find(q: str = Query(min_length=2, max_length=80), limit: int = Query(8, ge=1, le=10)):
    return _tool("find_player", {"name": q, "limit": limit})


@app.get("/api/players/{player_id}")
def profile(player_id: int):
    return _tool("get_player_profile", {"player_id": player_id})


@app.get("/api/players/{player_id}/similar")
def similar(player_id: int, value_max_eur: int | None = None, age_max: int | None = None,
            limit: int = Query(8, ge=1, le=15)):
    args = {"player_id": player_id, "limit": limit}
    if value_max_eur is not None:
        args["value_max_eur"] = value_max_eur
    if age_max is not None:
        args["age_max"] = age_max
    out, is_error = run_tool("similar_players", args)
    data = json.loads(out)
    return {"players": [], "notes": [data["error"]]} if is_error else data


@app.get("/api/compare")
def compare(ids: str = Query(description="2-4 comma-separated player ids")):
    try:
        player_ids = [int(i) for i in ids.split(",") if i.strip()]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated integers")
    return _tool("compare_players", {"player_ids": player_ids})


class NoteIn(BaseModel):
    player_id: int
    text: str = Field(min_length=3, max_length=4000)
    author: str = Field("scout", max_length=60)
    context: str | None = Field(None, max_length=120)


@app.get("/api/players/{player_id}/notes")
def player_notes(player_id: int):
    from rag.notes import list_notes
    return {"notes": list_notes(player_id)}


@app.post("/api/notes")
def create_note(note: NoteIn):
    from rag.notes import add_note
    if not rows("SELECT 1 AS x FROM players WHERE player_id = ?", [note.player_id]):
        raise HTTPException(404, f"no player with id {note.player_id}")
    return add_note(note.player_id, note.text, note.author, note.context)


@app.get("/api/eval/summary")
def eval_summary():
    summaries = sorted(RESULTS.glob("*.summary.json"), key=lambda p: p.stat().st_mtime) if RESULTS.exists() else []
    return {"results": [json.loads(p.read_text(encoding="utf-8")) for p in summaries[-6:]]}


# --- uploads ------------------------------------------------------------------------------------

@app.post("/api/files")
async def upload(file: UploadFile = File(...), owner: str = Depends(client_id)):
    data = await file.read()
    try:
        return files().save(owner, file.filename or "file", file.content_type, data)
    except UploadError as e:
        raise HTTPException(415 if "can't read" in str(e) or "frames" in str(e) else 400, str(e))


# --- chats and folders --------------------------------------------------------------------------

class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ChatPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    folder_id: str | None = None
    move: bool = False  # set with folder_id (or null) to move the chat


@app.get("/api/chats")
def list_chats(owner: str = Depends(client_id)):
    return {"folders": store().folders(owner), "chats": store().chats(owner)}


@app.post("/api/folders")
def add_folder(body: FolderIn, owner: str = Depends(client_id)):
    return store().add_folder(owner, body.name)


@app.patch("/api/folders/{folder_id}")
def rename_folder(folder_id: str, body: FolderIn, owner: str = Depends(client_id)):
    if not store().rename_folder(owner, folder_id, body.name):
        raise HTTPException(404, "No such folder.")
    return {"ok": True}


@app.delete("/api/folders/{folder_id}")
def delete_folder(folder_id: str, owner: str = Depends(client_id)):
    if not store().delete_folder(owner, folder_id):
        raise HTTPException(404, "No such folder.")
    return {"ok": True}


@app.patch("/api/chats/{chat_id}")
def patch_chat(chat_id: str, body: ChatPatch, owner: str = Depends(client_id)):
    if not store().update(owner, chat_id, body.title, body.folder_id, body.move):
        raise HTTPException(404, "No such chat or folder.")
    return store().get(owner, chat_id)


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str, owner: str = Depends(client_id)):
    if not store().delete(owner, chat_id):
        raise HTTPException(404, "No such chat.")
    return {"ok": True}


def _owned(owner: str, chat_id: str) -> dict:
    chat = store().get(owner, chat_id)
    if chat is None:
        raise HTTPException(404, "No such chat.")
    return chat


def _state(thread_id: str):
    return graph().get_state({"configurable": {"thread_id": thread_id}})


def _result_payload(block: dict, name: str) -> dict:
    try:
        data = json.loads(block["content"])
    except (TypeError, json.JSONDecodeError):
        data = {}
    is_error = bool(block.get("is_error"))
    summary = data.get("error") if is_error else None
    table = None
    if not is_error:
        if "total_matches" in data:
            summary = f"{data['total_matches']} matches"
            table = data["players"]
        elif "candidates" in data:
            summary = f"{len(data['candidates'])} candidates"
        elif "passages" in data:
            summary = f"{len(data['passages'])} passages"
        elif "players" in data:
            summary = f"{len(data['players'])} players"
            table = data["players"]
        elif "player" in data:
            summary = data["player"]["name"]
        elif "approved" in data:
            summary = f"{len(data['approved'])} approved"
    return {"id": block["tool_use_id"], "name": name, "is_error": is_error, "summary": summary, "data": table}


def transcript(messages: list[dict]) -> list[dict]:
    """Graph history -> turns for the UI: question, attachments, tool steps, last table, answer."""
    turns, names = [], {}
    for m in messages:
        if is_user_turn(m):
            turns.append({"turn": len(turns), "text": user_text(m), "attachments": attachment_names(m),
                          "steps": [], "table": None, "answer": None})
            continue
        if not turns or not isinstance(m["content"], list):
            continue
        t = turns[-1]
        for b in m["content"]:
            if b.get("type") == "tool_use":
                names[b["id"]] = b["name"]
                t["steps"].append({"id": b["id"], "name": b["name"], "input": b["input"], "done": False})
            elif b.get("type") == "tool_result":
                res = _result_payload(b, names.get(b["tool_use_id"], ""))
                for s in t["steps"]:
                    if s["id"] == res["id"]:
                        s.update(done=True, summary=res["summary"], is_error=res["is_error"])
                if res["data"]:
                    t["table"] = {"name": res["name"], "rows": res["data"]}
        if m["role"] == "assistant" and not any(b.get("type") == "tool_use" for b in m["content"]):
            text = "".join(b.get("text", "") for b in m["content"] if b.get("type") == "text").strip()
            if text:
                t["answer"] = text
    return turns


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str, owner: str = Depends(client_id)):
    chat = _owned(owner, chat_id)
    if not llm_available():
        return chat | {"turns": [], "pending": None}
    state = _state(chat["thread_id"])
    turns = transcript((state.values or {}).get("messages", []))
    saved = store().reports(chat["thread_id"])
    for t in turns:
        t["reports"] = saved.get(t["turn"], [])
    pending = state.interrupts[0].value if state.next == ("review_shortlist",) and state.interrupts else None
    return chat | {"turns": turns, "pending": pending}


@app.get("/api/shortlists")
def shortlists(owner: str = Depends(client_id)):
    """Chats with a shortlist waiting, and chats with reports written."""
    waiting, written = [], []
    for listed in store().chats(owner)[:60]:
        c = store().get(owner, listed["chat_id"])
        if llm_available():
            st = _state(c["thread_id"])
            if st.next == ("review_shortlist",) and st.interrupts:
                waiting.append(listed | {"candidates": st.interrupts[0].value["candidates"]})
        reps = [r for turn in store().reports(c["thread_id"]).values() for r in turn]
        if reps:
            written.append(listed | {"reports": [{"player_id": r["player_id"], "name": r["name"]} for r in reps]})
    return {"waiting": waiting, "written": written}


# --- the assistant over SSE ----------------------------------------------------------------------

def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def stream_turn(payload, chat: dict, turn: int, ip: str, model: str | None):
    run_id = str(uuid.uuid4())
    thread_id = chat["thread_id"]
    config = {"configurable": {"thread_id": thread_id}, "run_id": run_id, "run_name": "touchline-web",
              "metadata": {"prompt_version": PROMPT_VERSION, "effort": EFFORT, "model": model or DEFAULT_MODEL,
                           "chat_id": chat["chat_id"]}}
    yield sse("meta", {"chat_id": chat["chat_id"], "run_id": run_id, "turn": turn, "title": chat["title"]})
    usage, names, status = [], {}, "complete"
    try:
        for update in graph().stream(payload, config, stream_mode="updates"):
            for node, delta in update.items():
                if node == "__interrupt__":
                    status = "awaiting_approval"
                    yield sse("shortlist", {"chat_id": chat["chat_id"], **delta[0].value})
                    continue
                delta = delta or {}
                for msg in delta.get("messages", []):
                    for b in msg["content"] if isinstance(msg["content"], list) else []:
                        if b.get("type") == "tool_use":
                            names[b["id"]] = b["name"]
                            yield sse("step", {"id": b["id"], "name": b["name"], "input": b["input"]})
                        elif b.get("type") == "tool_result":
                            yield sse("result", _result_payload(b, names.get(b["tool_use_id"], "")))
                for r in delta.get("reports") or []:
                    report = {k: r.get(k) for k in ("player_id", "name", "blocks", "sources", "error")}
                    if r.get("blocks") and not r.get("error"):
                        store().save_report(chat["chat_id"], thread_id, turn, report)
                    yield sse("report", report)
                usage += delta.get("usage", [])
                if delta.get("final_text"):
                    yield sse("answer", {"text": delta["final_text"]})
    except Exception as e:  # surface the failure to the UI instead of a dropped stream
        log.exception("agent turn failed (chat %s, run %s)", chat["chat_id"], run_id)
        status = "error"
        local = (model or "").startswith(OLLAMA_PREFIX)
        yield sse("error", {"message": "The local model couldn't be reached. Is Ollama running on the server?"
                            if local else f"The assistant failed: {type(e).__name__}. Try again, or rephrase."})
    cost = usage_cost(usage)
    limits.record(ip, cost)
    yield sse("done", {"status": status, "cost_usd": cost})


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    chat_id: str | None = Field(None, max_length=64)
    model: str | None = Field(None, max_length=120)
    file_ids: list[str] = Field(default_factory=list, max_length=12)
    edit_turn: int | None = Field(None, ge=0, description="Re-ask from this turn: edit or regenerate")
    folder_id: str | None = None


class ResumeIn(BaseModel):
    chat_id: str = Field(max_length=64)
    approved: list[int] = Field(default_factory=list, max_length=8)
    comment: str | None = Field(None, max_length=500)


def _guard(request: Request, model: str | None) -> str:
    if model is not None and not is_known(model):
        raise HTTPException(400, f"Unknown model {model!r}.")
    local = (model or "").startswith(OLLAMA_PREFIX)
    if not local and not llm_available():
        raise HTTPException(503, "The assistant isn't configured on this server yet (no Anthropic API key). "
                                 "Choose a local model if Ollama is running.")
    ip = client_ip(request.headers, request.client.host if request.client else None)
    refusal = limits.check(ip)
    if refusal:
        raise HTTPException(429, refusal)
    return ip


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request, owner: str = Depends(client_id)):
    ip = _guard(request, body.model)
    try:
        blocks, labels = files().blocks(owner, body.file_ids)
    except UploadError:
        raise HTTPException(400, "One of the attached files is no longer available. Attach it again.")

    if body.chat_id is None:
        chat_rec = store().create(owner, body.message, body.model, body.folder_id)
        prefix, turn = None, 0
    else:
        chat_rec = _owned(owner, body.chat_id)
        state = _state(chat_rec["thread_id"])
        if state.next == ("review_shortlist",):
            raise HTTPException(409, "A shortlist is waiting for your approval. Approve or skip it first.")
        messages = (state.values or {}).get("messages", [])
        starts = turn_starts(messages)
        if body.edit_turn is None:
            prefix, turn = None, len(starts)
        else:
            if body.edit_turn >= len(starts):
                raise HTTPException(400, "There's no message at that position to edit.")
            # Fork: a fresh thread seeded with the unchanged history before the edited turn.
            prefix, turn = messages[:starts[body.edit_turn]], body.edit_turn
            old, new = chat_rec["thread_id"], uuid.uuid4().hex
            store().copy_reports(chat_rec["chat_id"], old, new, turn)
            store().touch(owner, chat_rec["chat_id"], thread_id=new)
            chat_rec = chat_rec | {"thread_id": new}
    store().touch(owner, chat_rec["chat_id"], model=body.model)
    payload = user_turn(body.message, model=body.model, attachment_blocks=blocks, attachment_labels=labels,
                        prefix=prefix)
    return StreamingResponse(stream_turn(payload, chat_rec, turn, ip, body.model),
                             media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/chat/resume")
def resume(body: ResumeIn, request: Request, owner: str = Depends(client_id)):
    chat_rec = _owned(owner, body.chat_id)
    ip = _guard(request, chat_rec.get("model"))
    state = _state(chat_rec["thread_id"])
    if state.next != ("review_shortlist",):
        raise HTTPException(409, "This chat has no shortlist waiting for approval.")
    turn = len(turn_starts((state.values or {}).get("messages", []))) - 1
    decision = Command(resume={"approved": body.approved, "comment": body.comment})
    return StreamingResponse(stream_turn(decision, chat_rec, turn, ip, chat_rec.get("model")),
                             media_type="text/event-stream", headers=_SSE_HEADERS)


class FeedbackIn(BaseModel):
    run_id: str = Field(max_length=64)
    score: int = Field(ge=0, le=1)
    comment: str | None = Field(None, max_length=1000)


@app.post("/api/feedback")
def feedback(body: FeedbackIn):
    """👍/👎 from the UI, attached to the LangSmith run for that turn."""
    if not os.environ.get("LANGSMITH_API_KEY"):
        return {"recorded": False, "reason": "LangSmith is not configured"}
    from langsmith import Client
    Client().create_feedback(run_id=body.run_id, key="user_score", score=body.score, comment=body.comment)
    return {"recorded": True}
