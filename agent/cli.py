"""Terminal chat with the Touchline agent.

    python -m agent.cli                      # interactive
    python -m agent.cli "left-footed CB under 23, under €10M"   # one question

Reads ANTHROPIC_API_KEY and LANGSMITH_* from .env. Each turn is traced to
LangSmith (project from LANGSMITH_PROJECT) when LANGSMITH_TRACING=true.
"""
import json
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

from agent.claude import EFFORT, MODEL, PROMPT_VERSION, AnthropicClaude  # noqa: E402
from agent.graph import build_graph, user_turn  # noqa: E402


def _summarise_call(block: dict) -> str:
    args = json.dumps(block["input"], ensure_ascii=False)
    return f"{block['name']}({args[:140]}{'…' if len(args) > 140 else ''})"


def _summarise_result(block: dict) -> str:
    try:
        data = json.loads(block["content"])
    except (TypeError, json.JSONDecodeError):
        return ""
    if block.get("is_error"):
        return f"error: {data.get('error')}"
    if "total_matches" in data:
        return f"{data['total_matches']} matches, {data['returned']} returned"
    if "candidates" in data:
        return f"{len(data['candidates'])} candidates"
    if "players" in data:
        return f"{len(data['players'])} players"
    if "player" in data:
        return data["player"]["name"]
    return ""


def ask(graph, thread_id: str, text: str) -> str:
    config = {"configurable": {"thread_id": thread_id}, "run_name": "touchline-turn",
              "metadata": {"prompt_version": PROMPT_VERSION, "effort": EFFORT, "model": MODEL,
                           "thread_id": thread_id}}
    final, usage = "", []
    for update in graph.stream(user_turn(text), config, stream_mode="updates"):
        for node, delta in update.items():
            for msg in delta.get("messages", []):
                for block in msg["content"] if isinstance(msg["content"], list) else []:
                    if block.get("type") == "tool_use":
                        print(f"  → {_summarise_call(block)}")
                    elif block.get("type") == "tool_result":
                        print(f"  ← {_summarise_result(block)}")
            usage += delta.get("usage", [])
            final = delta.get("final_text", final)
    cache = sum(u["cache_read_input_tokens"] for u in usage)
    out = sum(u["output_tokens"] for u in usage)
    print(f"  [{len(usage)} Claude calls · {out:,} output tokens · {cache:,} cached input tokens]")
    return final


def main() -> None:
    graph = build_graph(AnthropicClaude())
    thread_id = str(uuid.uuid4())
    if len(sys.argv) > 1:
        print(ask(graph, thread_id, " ".join(sys.argv[1:])))
        return
    print("Touchline · describe the player you need (Ctrl+C to quit)")
    while True:
        try:
            text = input("\nscout> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if text:
            print("\n" + ask(graph, thread_id, text))


if __name__ == "__main__":
    main()
