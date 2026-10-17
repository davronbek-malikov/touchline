"""Run one golden query through the agent and collect what the evaluators need."""
import json
import time
import uuid

from agent.graph import user_turn


def turn_tool_calls(messages: list[dict]) -> list[dict]:
    """tool_use blocks of the latest user turn, paired with their tool_result."""
    start = max(i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str))
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
    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "run_name": "touchline-eval",
              "metadata": metadata or {}}
    t0 = time.perf_counter()
    state = graph.invoke(user_turn(query), config)
    return {
        "final_text": state.get("final_text", ""),
        "tool_calls": turn_tool_calls(state["messages"]),
        "usage": state.get("usage", []),
        "latency_s": time.perf_counter() - t0,
        "tool_rounds": state.get("tool_rounds", 0),
    }
