import json

import pytest

from agent.schemas import SearchPlayersInput, strict_schema
from agent.tools import REGISTRY, TOOLS, run_tool


def call(tool, **args):
    out, is_error = run_tool(tool, args)
    return json.loads(out), is_error


def ids(result):
    return [p["player_id"] for p in result["players"]]


# --- schemas -----------------------------------------------------------------

def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_definitions_are_strict_compatible(tool):
    assert tool["strict"] is True
    schema = tool["input_schema"]
    banned = {"minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength", "default", "title"}
    for node in _walk(schema):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
        assert not banned & set(node) - {"properties"}


def test_search_schema_requires_nothing():
    assert strict_schema(SearchPlayersInput)["required"] == []


# --- find_player ---------------------------------------------------------------

def test_find_player_ranks_exact_and_active_first(warehouse):
    r, err = call("find_player", name="pablo builder")
    assert not err
    assert r["candidates"][0]["player_id"] == 3
    assert {c["player_id"] for c in r["candidates"]} >= {3, 6, 7}


def test_find_player_surname_only(warehouse):
    r, _ = call("find_player", name="Stopper")
    assert r["candidates"][0]["player_id"] == 4


def test_find_player_unknown(warehouse):
    r, err = call("find_player", name="Zzyzx Qwerty")
    assert not err and r["candidates"] == [] and r["note"]


# --- search_players --------------------------------------------------------------

def test_search_plan_example(warehouse):
    """'left-footed centre-back under 23, under €10M, contract ending by 2027'"""
    r, err = call("search_players", position_groups=["CB"], foot="left", age_max=22,
                  value_max_eur=10_000_000, contract_until_max="2027-12-31")
    assert not err
    assert ids(r) == [3, 5]  # value desc; 7 is over 22, 6 over budget
    assert r["total_matches"] == 2
    assert [p["coverage"] for p in r["players"]] == ["market + events", "market only"]


def test_search_excludes_inactive(warehouse):
    r, _ = call("search_players", sub_positions=["Centre-Forward"])
    assert r["players"] == [] and r["notes"]


def test_search_metric_filter_and_sort(warehouse):
    r, err = call("search_players", position_groups=["CB"],
                  metric_filters=[{"metric": "prog_passes", "percentile_min": 50}], sort_by="metric_filters_desc")
    assert not err
    assert ids(r) == [3, 7, 6]  # market-only 5 and low-percentile 4 drop out
    assert r["players"][0]["prog_passes_pct"] == 100
    assert r["players"][0]["event_competition"] == "UEFA Euro 2024"


def test_search_minutes_and_league(warehouse):
    r, _ = call("search_players", leagues=["ES1"], min_minutes=1000)
    assert ids(r) == [3]
    assert r["players"][0]["minutes_2025_26"] == 2500


def test_search_validation_errors(warehouse):
    for bad in [{"limit": 40}, {"age_max": 99}, {"foot": "middle"}, {"bogus": 1},
                {"sort_by": "metric_filters_desc"}]:
        r, err = call("search_players", **bad)
        assert err, bad
        assert "error" in r


def test_search_rejects_sql_injection_via_enum(warehouse):
    r, err = call("search_players", metric_filters=[{"metric": "np_xg; DROP TABLE players", "percentile_min": 1}])
    assert err


# --- profile / compare / similar ---------------------------------------------------

def test_profile(warehouse):
    r, err = call("get_player_profile", player_id=3)
    assert not err
    assert r["player"]["name"] == "Pablo Builder" and r["player"]["league"] == "LaLiga (Spain)"
    assert [s["season"] for s in r["seasons"]] == ["2025/26", "2024/25"]
    assert r["market_value_history"][-1]["market_value_eur"] == 9_000_000
    assert r["event_profile"]["metrics"]["prog_passes"]["percentile"] == 100


def test_profile_market_only_and_missing(warehouse):
    r, _ = call("get_player_profile", player_id=5)
    assert r["event_profile"] is None and r["notes"]
    _, err = call("get_player_profile", player_id=999)
    assert err


def test_compare(warehouse):
    r, err = call("compare_players", player_ids=[3, 4, 5])
    assert not err and [p["player_id"] for p in r["players"]] == [3, 4, 5]
    assert r["notes"]  # 5 is market only
    for bad in [[3], [3, 3], [1, 2, 3, 4, 5]]:
        assert call("compare_players", player_ids=bad)[1]


def test_similar_players(warehouse):
    r, err = call("similar_players", player_id=3)
    assert not err
    assert set(ids(r)[:2]) == {6, 7}  # builders, not the stopper
    assert ids(r)[-1] == 4
    assert r["players"][0]["shared_traits"]


def test_similar_players_constraints(warehouse):
    r, _ = call("similar_players", player_id=3, value_max_eur=10_000_000)
    assert 6 not in ids(r)
    r, _ = call("similar_players", player_id=3, same_position=False)
    assert 1 in ids(r)
    _, err = call("similar_players", player_id=5)  # no event data
    assert err


def test_unknown_tool():
    r, err = run_tool("drop_tables", {})
    assert err and "unknown tool" in r


def test_registry_names_match_definitions():
    assert [t["name"] for t in TOOLS] == list(REGISTRY)
