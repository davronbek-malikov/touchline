"""LangGraph agent: agent <-> tools loop with a hard cap on tool rounds.

    START -> agent --tool_use--> tools -> agent ... --end_turn--> END

State holds Anthropic-format messages as plain dicts and is only ever appended
to. review_shortlist (interrupt) and write_reports arrive in milestone 5.
"""
import json
import operator
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langsmith import traceable

from agent.claude import MAX_TOOL_ROUNDS, ClaudeClient
from agent.tools import run_tool

BUDGET_EXHAUSTED = ("Tool budget for this request is used up. Do not call more tools; answer now with "
                    "the results you already have and say what you could not check.")


class AgentState(TypedDict, total=False):
    messages: Annotated[list[dict], operator.add]
    tool_rounds: int          # reset to 0 by the caller on each new user turn
    usage: Annotated[list[dict], operator.add]
    final_text: str
    stop_reason: str


@traceable(run_type="tool", name="tool")
def _traced_tool(name: str, tool_input: dict) -> dict:
    content, is_error = run_tool(name, tool_input)
    return {"content": content, "is_error": is_error}


def build_graph(claude: ClaudeClient, checkpointer=None, max_tool_rounds: int = MAX_TOOL_ROUNDS):
    def agent(state: AgentState) -> dict:
        r = claude.create(state["messages"])
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
            with ThreadPoolExecutor(max_workers=min(8, len(calls))) as pool:
                results = list(pool.map(lambda c: _traced_tool(c["name"], c["input"]), calls))
        # All results for one assistant turn go back in a single user message.
        blocks = [{"type": "tool_result", "tool_use_id": c["id"], "content": r["content"],
                   **({"is_error": True} if r["is_error"] else {})} for c, r in zip(calls, results)]
        return {"messages": [{"role": "user", "content": blocks}], "tool_rounds": rounds}

    def after_agent(state: AgentState) -> str:
        if state.get("stop_reason") == "tool_use":
            # One extra round answers the pending calls with BUDGET_EXHAUSTED; after that, stop.
            return "tools" if state.get("tool_rounds", 0) <= max_tool_rounds else "give_up"
        return END

    def give_up(state: AgentState) -> dict:
        return {"messages": _close_pending(state["messages"][-1], BUDGET_EXHAUSTED),
                "final_text": "I ran out of tool budget before finishing this request. "
                              "Try narrowing it (fewer players or filters)."}

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("tools", tools)
    g.add_node("give_up", give_up)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", after_agent, ["tools", "give_up", END])
    g.add_edge("tools", "agent")
    g.add_edge("give_up", END)
    return g.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())


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


def user_turn(text: str) -> dict:
    """Input for one new user request."""
    return {"messages": [{"role": "user", "content": text}], "tool_rounds": 0}
