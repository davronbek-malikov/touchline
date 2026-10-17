"""Terminal chat with the Touchline agent.

    python -m agent.cli                                   # interactive, new thread
    python -m agent.cli --thread scouting-cbs             # resume a saved thread (also a paused shortlist)
    python -m agent.cli "left-footed CB under 23, under €10M"

Threads are checkpointed to state/threads.sqlite, so a shortlist awaiting
approval can be picked up later. Reads ANTHROPIC_API_KEY and LANGSMITH_* from .env.
"""
import argparse
import json
import sqlite3
import uuid

from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from agent.claude import EFFORT, MODEL, PROMPT_VERSION, AnthropicClaude  # noqa: E402
from agent.graph import build_graph, user_turn  # noqa: E402
from agent.reports import report_text  # noqa: E402
from rag.notes import STATE  # noqa: E402


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
    for key, label in (("total_matches", "matches"), ("candidates", "candidates"), ("passages", "passages"),
                       ("players", "players"), ("reports_written", "reports written")):
        if key in data:
            v = data[key]
            return f"{v if isinstance(v, int) else len(v)} {label}"
    return data.get("player", {}).get("name", "")


def _ask_approval(payload: dict) -> dict:
    print("\n  Proposed shortlist:")
    for i, c in enumerate(payload["candidates"], 1):
        value = f"€{c['market_value_eur'] / 1e6:g}M" if c.get("market_value_eur") else "value n/a"
        print(f"   {i}. {c['name']} ({c.get('age')}, {c.get('club_name')}, {value}) - {c['reason']}")
    raw = input("  Approve which for full reports? (e.g. 1,3 · all · none): ").strip().lower()
    ids = [c["player_id"] for c in payload["candidates"]]
    if raw in ("all", "a", "y", "yes"):
        approved = ids
    elif raw in ("", "none", "n", "no"):
        approved = []
    else:
        picks = {int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()}
        approved = [pid for i, pid in enumerate(ids, 1) if i in picks]
    comment = input("  Comment for the agent (optional): ").strip() or None
    return {"approved": approved, "comment": comment}


def run(graph, thread_id: str, payload) -> str:
    """Stream one turn (or a resume), handling shortlist interrupts until the turn ends."""
    config = {"configurable": {"thread_id": thread_id}, "run_name": "touchline-turn",
              "metadata": {"prompt_version": PROMPT_VERSION, "effort": EFFORT, "model": MODEL,
                           "thread_id": thread_id}}
    usage = []
    while True:
        interrupted = None
        for update in graph.stream(payload, config, stream_mode="updates"):
            for node, delta in update.items():
                if node == "__interrupt__":
                    interrupted = delta[0].value
                    continue
                for msg in (delta or {}).get("messages", []):
                    for block in msg["content"] if isinstance(msg["content"], list) else []:
                        if block.get("type") == "tool_use":
                            print(f"  → {_summarise_call(block)}")
                        elif block.get("type") == "tool_result":
                            print(f"  ← {_summarise_result(block)}")
                for report in (delta or {}).get("reports", []) or []:
                    print("\n" + "=" * 72 + f"\nSCOUTING REPORT · {report.get('name', report['player_id'])}\n"
                          + "=" * 72)
                    print(report.get("error") or report_text(report))
                usage += (delta or {}).get("usage", [])
        if interrupted is None:
            break
        payload = Command(resume=_ask_approval(interrupted))
    state = graph.get_state(config).values
    cache = sum(u.get("cache_read_input_tokens", 0) for u in usage)
    out = sum(u.get("output_tokens", 0) for u in usage)
    print(f"  [{len(usage)} Claude calls · {out:,} output tokens · {cache:,} cached input tokens · thread {thread_id}]")
    return state.get("final_text", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--thread", help="thread id to resume (default: new thread)")
    args = ap.parse_args()

    STATE.mkdir(exist_ok=True)
    saver = SqliteSaver(sqlite3.connect(STATE / "threads.sqlite", check_same_thread=False))
    graph = build_graph(AnthropicClaude(), checkpointer=saver)
    thread_id = args.thread or str(uuid.uuid4())[:8]

    pending = graph.get_state({"configurable": {"thread_id": thread_id}})
    if pending.next == ("review_shortlist",):
        print(f"Thread {thread_id} has a shortlist waiting for approval.")
        print("\n" + run(graph, thread_id, Command(resume=_ask_approval(pending.interrupts[0].value))))

    if args.question:
        print("\n" + run(graph, thread_id, user_turn(" ".join(args.question))))
        return
    print(f"Touchline · thread {thread_id} · describe the player you need (Ctrl+C to quit)")
    while True:
        try:
            text = input("\nscout> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if text:
            print("\n" + run(graph, thread_id, user_turn(text)))


if __name__ == "__main__":
    main()
