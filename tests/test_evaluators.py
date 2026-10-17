import json

from eval.evaluators import (cost_usd, fact_correct, filter_accuracy, numeric_grounding, player_names,
                             precision_recall_at_10, score_all, text_numbers, trap_handled)
from eval.target import turn_tool_calls


def run(text, *calls):
    return {"final_text": text, "tool_calls": list(calls), "usage": [], "latency_s": 1.0}


def call(name, inp, out, is_error=False):
    return {"name": name, "input": inp, "output": out, "is_error": is_error}


SEARCH_OUT = {"total_matches": 2, "players": [
    {"player_id": 3, "name": "Pablo Builder", "age": 21, "market_value_eur": 9_000_000, "contract_until": "2027-06-30",
     "prog_passes": 9.0, "prog_passes_pct": 100.0},
    {"player_id": 5, "name": "Market Only CB", "age": 20, "market_value_eur": 3_000_000, "contract_until": "2026-06-30"},
]}
GOLD = {"gold_filter": {"position_groups": ["CB"], "foot": "left", "age_max": 22, "value_max_eur": 10_000_000},
        "gold_player_ids": [3, 5]}


# --- numbers ---------------------------------------------------------------------

def test_text_numbers_units_and_indices():
    nums = text_numbers("1. Pablo is valued at €9M, 2,500 minutes, 94.3% passes\n| 2 | x |")
    assert (9_000_000, 500_000) in nums
    assert (2500, 0.5) in nums and (94.3, 0.05) in nums
    assert all(v not in (1, 2) for v, _ in nums)  # list and table indices skipped


def test_numeric_grounding(warehouse):
    good = run("Pablo Builder (21) is valued at €9M, contract to 30 June 2027, 9.0 progressive passes per 90.",
               call("search_players", {}, SEARCH_OUT))
    assert numeric_grounding(good)["score"] == 1.0
    bad = run("Pablo Builder is valued at €12.5M with 14 goals.", call("search_players", {}, SEARCH_OUT))
    r = numeric_grounding(bad)
    assert r["score"] == 0.0 and "ungrounded" in r["comment"]
    # Numbers the scout wrote are fair to repeat.
    assert numeric_grounding(run("Nobody under €10M fits."), "under €10M")["score"] == 1.0
    assert numeric_grounding(run("No numbers here.")) is None


# --- players -----------------------------------------------------------------------

def test_presented_players_and_precision(warehouse):
    out = run("Top pick: Market Only CB. Also Pablo Builder.", call("search_players", {}, SEARCH_OUT))
    pr = precision_recall_at_10(out, GOLD)
    assert pr == {"precision@10": 1.0, "recall@10": 1.0}
    half = run("Only Pablo Builder fits.", call("search_players", {}, SEARCH_OUT))
    assert precision_recall_at_10(half, GOLD) == {"precision@10": 1.0, "recall@10": 0.5}


def test_hallucinated_and_ungrounded_players(warehouse):
    out = run("Pablo Builder fits. Also consider Pablo Rashwell and Rugged Stopper.",
              call("search_players", {}, SEARCH_OUT))
    r = player_names(out)
    assert r["hallucinated_players"] == 1      # Pablo Rashwell: not in the warehouse
    assert r["ungrounded_players"] == 1        # Rugged Stopper: real, but no tool returned him
    clean = run("Pablo Builder fits; he plays for Real Club in LaLiga.", call("search_players", {}, SEARCH_OUT))
    assert player_names(clean)["hallucinated_players"] == 0


# --- filters / facts / traps ---------------------------------------------------------

def test_filter_accuracy():
    exact = run("", call("search_players", {"position_groups": ["CB"], "foot": "left", "age_max": 22,
                                            "value_max_eur": 10_000_000, "limit": 10}, SEARCH_OUT))
    assert filter_accuracy(exact, GOLD)["score"] == 1.0
    partial = run("", call("search_players", {"position_groups": ["CB"], "foot": "left", "age_max": 23}, SEARCH_OUT))
    r = filter_accuracy(partial, GOLD)
    assert r["score"] == 0.5 and "age_max" in r["comment"] and "value_max_eur" in r["comment"]
    # The best of several calls counts; failed calls don't.
    both = run("", partial["tool_calls"][0], exact["tool_calls"][0] | {"is_error": True})
    assert filter_accuracy(both, GOLD)["score"] == 0.5
    assert filter_accuracy(run(""), GOLD)["score"] == 0.0
    metric_gold = {"gold_filter": {"metric_filters": [{"metric": "xa", "percentile_min": 75}]}}
    swapped = run("", call("search_players", {"metric_filters": [{"metric": "xa", "percentile_min": 75}]}, {}))
    assert filter_accuracy(swapped, metric_gold)["score"] == 1.0


def test_fact_correct():
    assert fact_correct(run("He is valued at €200M."), {"gold_value": 200_000_000})["score"] == 1.0
    assert fact_correct(run("He is valued at €150M."), {"gold_value": 200_000_000})["score"] == 0.0
    assert fact_correct(run("His deal runs until 30 June 2027."), {"gold_value": "2027-06-30"})["score"] == 1.0
    assert fact_correct(run("He plays for Werder Bremen."), {"gold_value": "SV Werder Bremen"})["score"] == 1.0
    assert fact_correct(run("7.48 progressive carries per 90"), {"gold_value": 7.48})["score"] == 1.0


def test_trap_handled(warehouse):
    ref = {"expect_no_data": True}
    assert trap_handled(run("I don't have injury data in the database."), ref)["score"] == 1.0
    assert trap_handled(run("He had three hamstring injuries."), ref)["score"] == 0.0
    assert trap_handled(run("Not covered, but try Pablo Rashwell."), ref)["score"] == 0.0


def test_cost():
    out = {"usage": [{"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000,
                      "cache_creation_input_tokens": 0}]}
    assert cost_usd(out) == 4.0 + 2.0 + 0.2


def test_score_all_filter_item(warehouse):
    item = {"type": "filter", "query": "left-footed CB under 23, under €10M", "reference": GOLD}
    out = run("Pablo Builder (21, €9M) and Market Only CB (20, €3M).",
              call("search_players", {"position_groups": ["CB"], "foot": "left", "age_max": 22,
                                      "value_max_eur": 10_000_000}, SEARCH_OUT))
    s = score_all(item, out)["scores"]
    assert s["filter_accuracy"] == 1.0 and s["precision@10"] == 1.0 and s["recall@10"] == 1.0
    assert s["numeric_grounding"] == 1.0 and s["hallucinated_players"] == 0


def test_turn_tool_calls_only_latest_turn():
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "find_player", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "{}"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "b", "name": "search_players", "input": {"x": 1}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "b", "is_error": True,
                                      "content": json.dumps({"error": "bad"})}]},
    ]
    calls = turn_tool_calls(msgs)
    assert calls == [{"name": "search_players", "input": {"x": 1}, "output": {"error": "bad"}, "is_error": True}]
