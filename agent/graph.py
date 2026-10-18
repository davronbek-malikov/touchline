"""LangGraph agent: agent <-> tools loop with a hard cap on tool rounds, plus a
human approval step before scouting reports are written.

    START -> agent --tool_use--> tools -> agent ... --end_turn--> END
             agent --propose_shortlist--> review_shortlist (interrupt) -> write_reports -> tools -> agent

State holds Anthropic-format messages as plain dicts and is only ever appended
to. review_shortlist pauses the run with interrupt(); the scout's decision comes
back through Command(resume={"approved": [player_id, ...]}), even hours later
when a persistent checkpointer is used.
"""
import json
import operator
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from langsmith import traceable
from pydantic import ValidationError

from agent.claude import MAX_TOOL_ROUNDS, ClaudeClient
from agent.messages import is_user_turn, user_message, user_text
from agent.schemas import ProposeShortlistInput
from agent.tools import SHORTLIST_TOOL, run_tool
from agent.tools.db import rows

MAX_REPORT_WORKERS = 4

BUDGET_EXHAUSTED = ("Tool budget for this request is used up. Do not call more tools; answer now with "
                    "the results you already have and say what you could not check.")


class AgentState(TypedDict, total=False):
    messages: Annotated[list[dict], operator.add]
    tool_rounds: int          # reset to 0 by the caller on each new user turn
    usage: Annotated[list[dict], operator.add]
    final_text: str
    stop_reason: str
    model: str | None         # model id for this turn (None = default); see agent.models
    shortlist: dict | None    # the scout's decision on the pending propose_shortlist call
    reports: list[dict]       # reports written this turn (reset per turn)


@traceable(run_type="tool", name="tool")
def _traced_tool(name: str, tool_input: dict) -> dict:
    content, is_error = run_tool(name, tool_input)
    return {"content": content, "is_error": is_error}


def build_graph(claude: ClaudeClient, checkpointer=None, max_tool_rounds: int = MAX_TOOL_ROUNDS,
                report_writer=None):
    def writer():
        nonlocal report_writer
        if report_writer is None:
            from agent.reports import ClaudeReportWriter
            report_writer = ClaudeReportWriter()
        return report_writer

    def agent(state: AgentState) -> dict:
        r = claude.create(state["messages"], model=state.get("model"))
        assistant = {"role": "assistant", "content": r.content}
        update = {"messages": [assistant], "usage": [r.usage | {"model": r.model}], "stop_reason": r.stop_reason}
        if r.stop_reason != "tool_use":
            update["final_text"] = _final_text(r)
            # e.g. max_tokens mid tool call: close the calls so the next turn's history is valid.
            update["messages"] += _close_pending(assistant, "Response ended before this tool could run.")
        return update

    def tools(state: AgentState) -> dict:
        calls = [b for b in state["messages"][-1]["content"] if b.get("type") == "tool_use"]
        rounds = state.get("tool_rounds", 0) + 1
        if rounds > max_tool_rounds:
            results = [{"content": json.dumps({"error": BUDGET_EXHAUSTED}), "is_error": True} for _ in calls]
        else:
            def run(c):
                if c["name"] == SHORTLIST_TOOL:
                    return _shortlist_result(c, state)
                return _traced_tool(c["name"], c["input"])

            with ThreadPoolExecutor(max_workers=min(8, len(calls))) as pool:
                results = list(pool.map(run, calls))
        # All results for one assistant turn go back in a single user message.
        blocks = [{"type": "tool_result", "tool_use_id": c["id"], "content": r["content"],
                   **({"is_error": True} if r["is_error"] else {})} for c, r in zip(calls, results)]
        return {"messages": [{"role": "user", "content": blocks}], "tool_rounds": rounds, "shortlist": None}

    def review_shortlist(state: AgentState) -> dict:
        call = _shortlist_call(state["messages"][-1])
        try:
            proposal = ProposeShortlistInput.model_validate(call["input"])
        except ValidationError as e:
            return {"shortlist": {"error": f"invalid shortlist: {e.errors()[0]['msg']}"}}
        ids = [c.player_id for c in proposal.candidates]
        info = {r["player_id"]: r for r in rows(
            "SELECT player_id, name, age, position_group, club_name, market_value_eur FROM players "
            f"WHERE player_id IN ({', '.join('?' * len(ids))})", ids)}
        unknown = [i for i in ids if i not in info]
        if unknown:
            return {"shortlist": {"error": f"unknown player ids {unknown}; use ids returned by tools"}}
        candidates = [info[c.player_id] | {"reason": c.reason} for c in proposal.candidates]
        # Pauses here. Resumed with {"approved": [ids]}; this node re-runs from the top on resume.
        decision = interrupt({"type": "shortlist", "candidates": candidates}) or {}
        chosen = set(decision.get("approved", []))
        approved = [i for i in ids if i in chosen]
        return {"shortlist": {"candidates": candidates, "approved": approved, "comment": decision.get("comment")}}

    def write_reports(state: AgentState) -> dict:
        decision = state.get("shortlist") or {}
        approved = decision.get("approved") or []
        if not approved:
            return {"reports": []}
        brief = next((user_text(m) for m in reversed(state["messages"]) if is_user_turn(m)), None)

        def one(pid):
            try:
                return writer().write(pid, brief)
            except Exception as e:  # one failed report shouldn't sink the rest
                return {"player_id": pid, "error": f"{type(e).__name__}: {e}", "blocks": []}

        with ThreadPoolExecutor(max_workers=min(MAX_REPORT_WORKERS, len(approved))) as pool:
            reports = list(pool.map(one, approved))
        return {"reports": reports, "usage": [r["usage"] | {"model": "report"} for r in reports if r.get("usage")]}

    def after_agent(state: AgentState) -> str:
        if state.get("stop_reason") == "tool_use":
            # One extra round answers the pending calls with BUDGET_EXHAUSTED; after that, stop.
            if state.get("tool_rounds", 0) > max_tool_rounds:
                return "give_up"
            if _shortlist_call(state["messages"][-1]) and state.get("tool_rounds", 0) < max_tool_rounds:
                return "review_shortlist"
            return "tools"
        return END

    def give_up(state: AgentState) -> dict:
        return {"messages": _close_pending(state["messages"][-1], BUDGET_EXHAUSTED),
                "final_text": "I ran out of tool budget before finishing this request. "
                              "Try narrowing it (fewer players or filters)."}

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_node("give_up", give_up)
    g.add_node("review_shortlist", review_shortlist)
    g.add_node("write_reports", write_reports)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", after_agent, ["tools", "review_shortlist", "give_up", END])
    g.add_edge("review_shortlist", "write_reports")
    g.add_edge("write_reports", "tools")
    g.add_edge("tools", "agent")
    g.add_edge("give_up", END)
    return g.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())


def _shortlist_call(assistant: dict) -> dict | None:
    return next((b for b in assistant["content"] if b.get("type") == "tool_use" and b["name"] == SHORTLIST_TOOL),
                None)


def _shortlist_result(call: dict, state: AgentState) -> dict:
    """tool_result content for propose_shortlist, from the scout's decision and the reports written."""
    decision = state.get("shortlist")
    first = _shortlist_call(state["messages"][-1])
    if decision is None or call["id"] != first["id"]:
        return {"content": json.dumps({"error": "only one shortlist can be proposed at a time"}), "is_error": True}
    if "error" in decision:
        return {"content": json.dumps({"error": decision["error"]}), "is_error": True}
    approved = set(decision["approved"])
    reports = state.get("reports") or []
    out = {
        "approved": [c["name"] for c in decision["candidates"] if c["player_id"] in approved],
        "not_approved": [c["name"] for c in decision["candidates"] if c["player_id"] not in approved],
        "scout_comment": decision.get("comment"),
        "reports_written": [r["name"] for r in reports if r.get("blocks") and not r.get("error")],
        "report_errors": [{"player_id": r["player_id"], "error": r["error"]} for r in reports if r.get("error")],
        "note": "The full cited reports were shown to the scout directly. Reply with a brief summary and next "
                "steps; do not repeat the reports.",
    }
    return {"content": json.dumps(out, ensure_ascii=False), "is_error": False}


def _close_pending(assistant: dict, reason: str) -> list[dict]:
    calls = [b for b in assistant["content"] if b.get("type") == "tool_use"]
    if not calls:
        return []
    return [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": c["id"], "content": json.dumps({"error": reason}), "is_error": True}
        for c in calls]}]


def _final_text(r) -> str:
    text = "".join(b.get("text", "") for b in r.content if b.get("type") == "text").strip()
    if r.stop_reason == "refusal":
        return text or "This request was declined by the model's safety filters, so I can't answer it."
    if r.stop_reason == "max_tokens":
        return (text + "\n\n[Answer cut off at the output limit.]").strip()
    return text


def user_turn(text: str, model: str | None = None, attachment_blocks: list[dict] | None = None,
              attachment_labels: list[str] | None = None, prefix: list[dict] | None = None) -> dict:
    """Input for one new user request. `prefix` seeds a fresh thread with an earlier
    conversation's messages, unchanged, for edit-and-resend and regenerate."""
    msg = user_message(text, attachment_blocks, attachment_labels)
    return {"messages": (prefix or []) + [msg], "tool_rounds": 0, "reports": [], "shortlist": None, "model": model}
