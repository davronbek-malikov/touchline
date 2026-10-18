import json

import eval.run_experiment as rx
from agent.claude import ClaudeResponse

USAGE = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


class ScriptedClaude:
    """Searches once, then names the first player it got back."""

    def create(self, messages, model=None):
        last = messages[-1]
        if isinstance(last["content"], str):
            return ClaudeResponse([{"type": "tool_use", "id": "t1", "name": "search_players",
                                    "input": {"position_groups": ["CB"], "foot": "left", "age_max": 22,
                                              "value_max_eur": 10_000_000}}], "tool_use", "fake", USAGE)
        players = json.loads(last["content"][0]["content"])["players"]
        top = players[0]
        text = f"Top pick: {top['name']}, valued at €{top['market_value_eur'] / 1e6:g}M."
        return ClaudeResponse([{"type": "text", "text": text}], "end_turn", "fake", USAGE)


def test_run_local_end_to_end(warehouse, tmp_path, monkeypatch):
    monkeypatch.setattr(rx, "AnthropicClaude", ScriptedClaude)
    monkeypatch.setattr(rx, "RESULTS", tmp_path)
    item = {"id": "filter-01", "type": "filter", "query": "left-footed CB under 23, under €10M", "tags": [],
            "ci": True, "reference": {"gold_filter": {"position_groups": ["CB"], "foot": "left", "age_max": 22,
                                                      "value_max_eur": 10_000_000},
                                      "gold_player_ids": [3, 5]}}
    summary = rx.run_local([item], "smoke", concurrency=1, max_cost=None)

    assert summary["n"] == 1
    assert summary["filter_accuracy"] == 1.0
    assert summary["precision@10"] == 1.0 and summary["recall@10"] == 0.5
    assert summary["hallucinated_players"] == 0 and summary["numeric_grounding"] == 1.0
    assert summary["cost_usd_total"] == round(2 * (1000 * 4 + 200 * 20) / 1e6, 4)
    row = json.loads((tmp_path / "smoke.jsonl").read_text(encoding="utf-8"))
    assert row["outputs"]["tool_calls"][0]["name"] == "search_players"
    assert (tmp_path / "smoke.summary.json").exists()


def test_ci_subset_is_30():
    assert len(rx.load_items(ci=True)) == 30
    assert {it["type"] for it in rx.load_items(ci=True)} == {"filter", "similar", "fact", "trap"}
