import pandas as pd
import pytest

from data.statsbomb_per90 import aggregate, match_player_stats, percentiles


def _lineups():
    return [
        {"team_name": "Home", "lineup": [
            {"player_id": 1, "player_name": "Alpha One", "player_nickname": None, "country": {"name": "Spain"},
             "positions": [{"position": "Left Wing", "from": "00:00", "to": None, "from_period": 1}]},
            {"player_id": 2, "player_name": "Beta Two", "player_nickname": "Beta", "country": {"name": "Spain"},
             "positions": [{"position": "Center Back", "from": "00:00", "to": "60:00", "from_period": 1},
                           {"position": "Left Back", "from": "60:00", "to": None, "from_period": 2}]},
            {"player_id": 3, "player_name": "Bench Guy", "player_nickname": None, "country": {"name": "Spain"},
             "positions": []},
        ]},
    ]


def _ev(i, t, player, minute=10, **extra):
    return {"id": f"e{i}", "period": 1, "minute": minute, "second": 0, "type": {"name": t},
            "player": {"id": player}, **extra}


def _events():
    return [
        _ev(1, "Pass", 2, location=[50, 40],
            **{"pass": {"end_location": [90, 40], "shot_assist": True}}),  # progressive, final third, key pass
        _ev(2, "Shot", 1, location=[105, 40],
            shot={"type": {"name": "Open Play"}, "statsbomb_xg": 0.3, "outcome": {"name": "Goal"}, "key_pass_id": "e1"}),
        _ev(3, "Shot", 1, shot={"type": {"name": "Penalty"}, "statsbomb_xg": 0.76, "outcome": {"name": "Goal"}}),
        _ev(4, "Pass", 2, location=[20, 40], under_pressure=True,
            **{"pass": {"end_location": [30, 40], "outcome": {"name": "Incomplete"}}}),
        _ev(5, "Pass", 2, **{"pass": {"type": {"name": "Throw-in"}, "end_location": [1, 1]}}, location=[0, 0]),
        _ev(6, "Carry", 1, location=[60, 40], carry={"end_location": [80, 40]}),
        _ev(7, "Dribble", 1, dribble={"outcome": {"name": "Complete"}}),
        _ev(8, "Duel", 2, duel={"type": {"name": "Tackle"}, "outcome": {"name": "Won"}}),
        _ev(9, "Duel", 2, duel={"type": {"name": "Aerial Lost"}}),
        _ev(10, "Clearance", 2, clearance={"aerial_won": True}),
        _ev(11, "Pressure", 1),
        _ev(12, "Half End", 1, minute=90) | {"player": {"id": 1}},
    ]


def test_match_player_stats_counts_and_minutes():
    rows = {r["sb_player_id"]: r for r in match_player_stats(_events(), _lineups())}
    assert set(rows) == {1, 2}  # unused sub dropped

    a, b = rows[1], rows[2]
    assert a["minutes"] == pytest.approx(90)
    assert b["position_minutes"] == {"Center Back": 60, "Left Back": 30}

    assert a["shots"] == 1 and a["np_goals"] == 1  # penalty excluded
    assert a["np_xg"] == pytest.approx(0.3)
    assert b["xa"] == pytest.approx(0.3) and b["key_passes"] == 1
    assert b["passes_att"] == 2 and b["passes_cmp"] == 1  # throw-in excluded
    assert b["up_passes_att"] == 1 and b["up_passes_cmp"] == 0
    assert b["prog_passes"] == 1 and b["final_third_passes"] == 1
    assert a["prog_carries"] == 1 and a["dribbles_cmp"] == 1 and a["pressures"] == 1
    assert b["tackles_won"] == 1 and b["aerials_won"] == 1 and b["aerials_lost"] == 1


def _match_df(n_matches=4):
    rows = []
    for m in range(n_matches):
        for r in match_player_stats(_events(), _lineups()):
            rows.append(r | {"match_id": m, "competition_id": 55, "season_id": 282, "competition": "Euro"})
    return pd.DataFrame(rows)


def test_aggregate_per90_and_position_group():
    agg = aggregate(_match_df()).set_index("sb_player_id")
    assert agg.loc[1, "minutes"] == pytest.approx(360)
    assert agg.loc[1, "np_xg_p90"] == pytest.approx(0.3)
    assert agg.loc[2, "position_group"] == "CB"  # 240 CB minutes vs 120 LB
    assert agg.loc[1, "position_group"] == "W"
    assert pd.isna(agg.loc[2, "pass_cmp_pct"])  # 8 passes < minimum attempts


def test_percentiles_within_position_group():
    df = pd.DataFrame({
        "sb_player_id": [1, 2, 3], "competition_id": 1, "season_id": 1,
        "position_group": ["CB", "CB", "ST"],
        **{c: [1.0, 2.0, 3.0] for c in aggregate(_match_df()).columns if c.endswith("_p90")},
        **{c: [50.0, 60.0, 70.0] for c in ["pass_cmp_pct", "pass_cmp_under_pressure_pct", "aerial_win_pct",
                                           "ground_duel_win_pct", "dribble_success_pct"]},
    })
    pct = percentiles(df).set_index("sb_player_id")
    assert pct.loc[2, "np_xg"] == 100 and pct.loc[1, "np_xg"] == 50
    assert pct.loc[3, "np_xg"] == 100  # alone in its group
