import copy
import json

from agent.claude import ClaudeResponse
from agent.graph import BUDGET_EXHAUSTED, build_graph, user_turn

USAGE = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


class FakeClaude:
    """Returns scripted responses in order and records the history it was sent."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen: list[list[dict]] = []

    def create(self, messages):
        self.seen.append(copy.deepcopy(messages))
        content, stop = self.responses.pop(0)
        return ClaudeResponse(content=content, stop_reason=stop, model="fake", usage=USAGE)


def tool_use(i, tool, **args):
    return {"type": "tool_use", "id": f"t{i}", "name": tool, "input": args}


def text(s):
    return {"type": "text", "text": s}


THINK = {"type": "thinking", "thinking": "", "signature": "sig"}


def run(fake, *turns, thread="t", **kw):
    g = build_graph(fake, **kw)
    out = None
    for t in turns:
        out = g.invoke(user_turn(t), {"configurable": {"thread_id": thread}})
    return out


def test_tool_loop_returns_all_results_in_one_message(warehouse):
    fake = FakeClaude(
        ([THINK, tool_use(1, "find_player", name="Pablo Builder"),
          tool_use(2, "search_players", position_groups=["CB"], limit=2)], "tool_use"),
        ([THINK, text("Pablo Builder is the pick.")], "end_turn"),
    )
    out = run(fake, "find me a CB")
    assert out["final_text"] == "Pablo Builder is the pick."
    assert out["tool_rounds"] == 1

    second_call = fake.seen[1]
    assert [m["role"] for m in second_call] == ["user", "assistant", "user"]
    results = second_call[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert not any(r.get("is_error") for r in results)
    assert json.loads(results[1]["content"])["total_matches"] == 5  # CBs 3-7
    # Assistant content, thinking block included, is passed back unchanged.
    assert second_call[1]["content"][0] == THINK


def test_tool_errors_are_flagged(warehouse):
    fake = FakeClaude(
        ([tool_use(1, "search_players", limit=99), tool_use(2, "get_player_profile", player_id=3)], "tool_use"),
        ([text("ok")], "end_turn"),
    )
    run(fake, "q")
    results = fake.seen[1][2]["content"]
    assert results[0]["is_error"] is True and "limit" in results[0]["content"]
    assert "is_error" not in results[1]


def test_tool_round_cap(warehouse):
    looping = ([tool_use(i, "find_player", name="Stopper") for i in range(1)], "tool_use")
    fake = FakeClaude(*[looping] * 4)
    out = run(fake, "q", max_tool_rounds=2)
    # rounds 1-2 run, round 3 answers with BUDGET_EXHAUSTED, then the graph gives up.
    assert len(fake.seen) == 4
    third_results = fake.seen[3][-1]["content"]
    assert BUDGET_EXHAUSTED in third_results[0]["content"]
    assert "ran out of tool budget" in out["final_text"]
    # History ends with tool_results, so a follow-up turn is valid.
    assert out["messages"][-1]["content"][0]["type"] == "tool_result"


def test_budget_resets_each_turn_and_history_persists(warehouse):
    fake = FakeClaude(
        ([tool_use(1, "find_player", name="Stopper")], "tool_use"),
        ([text("first")], "end_turn"),
        ([tool_use(2, "get_player_profile", player_id=4)], "tool_use"),
        ([text("second")], "end_turn"),
    )
    out = run(fake, "who is stopper", "profile him")
    assert out["final_text"] == "second" and out["tool_rounds"] == 1
    roles = [m["role"] for m in fake.seen[3]]
    assert roles == ["user", "assistant", "user", "assistant", "user", "assistant", "user"]
    # Earlier messages are never rewritten.
    assert fake.seen[3][:4] == fake.seen[1] + [{"role": "assistant", "content": [text("first")]}]


def test_refusal_and_max_tokens(warehouse):
    out = run(FakeClaude(([], "refusal")), "q", thread="a")
    assert "declined" in out["final_text"]

    fake = FakeClaude(([text("partial"), tool_use(1, "find_player", name="x")], "max_tokens"))
    out = run(fake, "q", thread="b")
    assert out["final_text"].startswith("partial") and "cut off" in out["final_text"]
    assert out["messages"][-1]["content"][0]["is_error"] is True


def test_usage_accumulates(warehouse):
    fake = FakeClaude(([tool_use(1, "find_player", name="Stopper")], "tool_use"), ([text("x")], "end_turn"))
    out = run(fake, "q")
    assert len(out["usage"]) == 2
