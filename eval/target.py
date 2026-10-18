"""Run one golden query through the agent and collect what the evaluators need."""
import json
import time
import uuid

from langgraph.types import Command

from agent.graph import user_turn
from agent.messages import is_user_turn
from agent.reports import report_text


def turn_tool_calls(messages: list[dict]) -> list[dict]:
    """tool_use blocks of the latest user turn, paired with their tool_result."""
    start = max(i for i, m in enumerate(messages) if is_user_turn(m))
    uses, results = {}, {}
    for m in messages[start + 1:]:
        for b in m["content"] if isinstance(m["content"], list) else []:
            if b.get("type") == "tool_use":
                uses[b["id"]] = b
            elif b.get("type") == "tool_result":
                results[b["tool_use_id"]] = b
    calls = []
    for tid, u in uses.items():
        r = results.get(tid, {})
        try:
            out = json.loads(r.get("content", "null"))
        except (TypeError, json.JSONDecodeError):
            out = None
        calls.append({"name": u["name"], "input": u["input"], "output": out, "is_error": bool(r.get("is_error"))})
    return calls


def run_query(graph, query: str, metadata: dict | None = None) -> dict:
    """One turn. Shortlist interrupts are auto-approved in full (the eval policy)."""
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "run_name": "touchline-eval",
              "metadata": metadata or {}}
    t0 = time.perf_counter()
    state = graph.invoke(user_turn(query), config)
    shortlists = []
    while state.get("__interrupt__"):
        pending = state["__interrupt__"][0].value
        shortlists.append([c["player_id"] for c in pending["candidates"]])
        state = graph.invoke(Command(resume={"approved": shortlists[-1]}), config)

    calls = turn_tool_calls(state["messages"])
    reports = [r for r in state.get("reports") or [] if r.get("blocks")]
    for r in reports:  # what each report was written from counts as tool evidence
        calls.append({"name": "report_evidence", "input": {"player_id": r["player_id"]},
                      "output": {"profile": r.get("profile"), "passages": r.get("sources")}, "is_error": False})
    return {
        "final_text": state.get("final_text", ""),
        "tool_calls": calls,
        "reports": [{"player_id": r["player_id"], "name": r.get("name"), "blocks": r["blocks"],
                     "text": report_text(r, with_refs=False)} for r in reports],
        "shortlists": shortlists,
        "usage": state.get("usage", []),
        "latency_s": time.perf_counter() - t0,
        "tool_rounds": state.get("tool_rounds", 0),
    }
