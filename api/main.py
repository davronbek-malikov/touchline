"""Touchline HTTP API: the agent over Server-Sent Events, plus direct data endpoints.

    uvicorn api.main:app --reload

Chat events (POST /api/chat, POST /api/chat/resume), one JSON payload each:
    meta       {thread_id, run_id}
    step       {id, name, input}                    a tool call started
    result     {id, name, is_error, summary, data}  its result (data: player rows for tables)
    shortlist  {thread_id, candidates}              paused for the scout's approval
    report     {player_id, name, blocks, sources}   a cited report
    answer     {text}
    error      {message}
    done       {status, cost_usd}
"""
import json
import logging
import os
import sqlite3
import uuid
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from langgraph.types import Command  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agent.claude import EFFORT, MODEL, PROMPT_VERSION  # noqa: E402
from agent.cost import usage_cost  # noqa: E402
from agent.graph import user_turn  # noqa: E402
from agent.tools import run_tool  # noqa: E402
from agent.tools.db import data_as_of, rows  # noqa: E402
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

app = FastAPI(title="Touchline API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")],
    allow_origin_regex=os.environ.get("ALLOWED_ORIGIN_REGEX") or None,
    allow_methods=["GET", "POST"], allow_headers=["*"],
)
limits = Limits()
_graph_override = None


def set_graph(graph) -> None:
    """Inject a graph (tests)."""
    global _graph_override
    _graph_override = graph


@lru_cache(maxsize=1)
def _default_graph():
    from langgraph.checkpoint.sqlite import SqliteSaver

    from agent.claude import AnthropicClaude
    from agent.graph import build_graph

    STATE.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(STATE / "threads.sqlite", check_same_thread=False))
    return build_graph(AnthropicClaude(), checkpointer=saver)


def graph():
    return _graph_override or _default_graph()


def llm_available() -> bool:
    return _graph_override is not None or bool(os.environ.get("ANTHROPIC_API_KEY"))


def _tool(name: str, args: dict) -> dict:
    out, is_error = run_tool(name, args)
    data = json.loads(out)
    if is_error:
        raise HTTPException(status_code=404 if "no player" in data.get("error", "") else 400, detail=data["error"])
    return data


# --- data endpoints (no LLM) -------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "data_as_of": data_as_of(), "llm": llm_available(), "model": MODEL}


@app.get("/api/meta")
def meta():
    counts = rows("""SELECT (SELECT count(*) FROM players WHERE is_active) AS active_players,
                            (SELECT count(*) FROM player_performance) AS event_players""")[0]
    return {"data_as_of": data_as_of(), **counts, "examples": EXAMPLES, "llm": llm_available(),
            "model": MODEL, "effort": EFFORT, "prompt_version": PROMPT_VERSION, "limits": limits.status()}


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


# --- agent over SSE -------------------------------------------------------------------------

def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


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


def stream_turn(payload, thread_id: str, ip: str):
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}, "run_id": run_id, "run_name": "touchline-web",
              "metadata": {"prompt_version": PROMPT_VERSION, "effort": EFFORT, "model": MODEL, "thread_id": thread_id}}
    yield sse("meta", {"thread_id": thread_id, "run_id": run_id})
    usage, names, status = [], {}, "complete"
    try:
        for update in graph().stream(payload, config, stream_mode="updates"):
            for node, delta in update.items():
                if node == "__interrupt__":
                    status = "awaiting_approval"
                    yield sse("shortlist", {"thread_id": thread_id, **delta[0].value})
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
                    yield sse("report", {k: r.get(k) for k in ("player_id", "name", "blocks", "sources", "error")})
                usage += delta.get("usage", [])
                if delta.get("final_text"):
                    yield sse("answer", {"text": delta["final_text"]})
    except Exception as e:  # surface the failure to the UI instead of a dropped stream
        log.exception("agent turn failed (thread %s, run %s)", thread_id, run_id)
        status = "error"
        yield sse("error", {"message": f"The agent failed: {type(e).__name__}. Try again, or rephrase."})
    cost = usage_cost(usage)
    limits.record(ip, cost)
    yield sse("done", {"status": status, "cost_usd": cost})


class ChatIn(BaseModel):
    message: str = Field(min_length=2, max_length=1500)
    thread_id: str | None = Field(None, max_length=64)


class ResumeIn(BaseModel):
    thread_id: str = Field(max_length=64)
    approved: list[int] = Field(default_factory=list, max_length=8)
    comment: str | None = Field(None, max_length=500)


def _guard(request: Request) -> str:
    if not llm_available():
        raise HTTPException(503, "The agent isn't configured on this server yet (no Anthropic API key).")
    ip = client_ip(request.headers, request.client.host if request.client else None)
    refusal = limits.check(ip)
    if refusal:
        raise HTTPException(429, refusal)
    return ip


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    ip = _guard(request)
    thread_id = body.thread_id or uuid.uuid4().hex[:12]
    return StreamingResponse(stream_turn(user_turn(body.message), thread_id, ip),
                             media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/chat/resume")
def resume(body: ResumeIn, request: Request):
    ip = _guard(request)
    state = graph().get_state({"configurable": {"thread_id": body.thread_id}})
    if state.next != ("review_shortlist",):
        raise HTTPException(409, "This thread has no shortlist waiting for approval.")
    decision = Command(resume={"approved": body.approved, "comment": body.comment})
    return StreamingResponse(stream_turn(decision, body.thread_id, ip),
                             media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/api/threads/{thread_id}")
def thread(thread_id: str):
    """Conversation so far and any shortlist still waiting, for reopening a thread."""
    if not llm_available():
        return {"thread_id": thread_id, "messages": [], "pending": None, "reports": []}
    state = graph().get_state({"configurable": {"thread_id": thread_id}})
    values = state.values or {}
    convo = []
    for m in values.get("messages", []):
        if m["role"] == "user" and isinstance(m["content"], str):
            convo.append({"role": "user", "text": m["content"]})
        elif m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in m["content"] if b.get("type") == "text").strip()
            if text and not any(b.get("type") == "tool_use" for b in m["content"]):
                convo.append({"role": "assistant", "text": text})
    pending = state.interrupts[0].value if state.next == ("review_shortlist",) and state.interrupts else None
    return {"thread_id": thread_id, "messages": convo, "pending": pending,
            "reports": [{k: r.get(k) for k in ("player_id", "name", "blocks", "sources")}
                        for r in values.get("reports") or []]}


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
