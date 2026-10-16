"""StatsBomb open data -> per-90 event metrics and position-group percentiles.

Grain: one row per (sb_player_id, competition season), minimum MIN_MINUTES.
Tables: sb_players, sb_player_per90, sb_percentiles.
"""
import json
import math
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import duckdb
import pandas as pd

from data.config import MIN_MINUTES, SB_COMPETITIONS, SB_DIR

GOAL = (120.0, 40.0)
SET_PIECES = {"Throw-in", "Corner", "Kick Off", "Goal Kick"}
TACKLE_WON = {"Won", "Success", "Success In Play", "Success Out"}

# StatsBomb position name -> Touchline position group.
SB_POSITION_GROUPS = {
    "Goalkeeper": "GK",
    "Center Back": "CB", "Left Center Back": "CB", "Right Center Back": "CB",
    "Left Back": "FB", "Right Back": "FB", "Left Wing Back": "FB", "Right Wing Back": "FB",
    "Center Defensive Midfield": "DM", "Left Defensive Midfield": "DM", "Right Defensive Midfield": "DM",
    "Center Midfield": "CM", "Left Center Midfield": "CM", "Right Center Midfield": "CM",
    "Center Attacking Midfield": "AM", "Left Attacking Midfield": "AM", "Right Attacking Midfield": "AM",
    "Left Midfield": "W", "Right Midfield": "W", "Left Wing": "W", "Right Wing": "W",
    "Center Forward": "ST", "Left Center Forward": "ST", "Right Center Forward": "ST", "Secondary Striker": "ST",
}

COUNT_FIELDS = [
    "shots", "np_goals", "np_xg", "xa", "key_passes", "assists",
    "passes_att", "passes_cmp", "prog_passes", "prog_carries", "final_third_passes", "box_passes",
    "dribbles_att", "dribbles_cmp", "dribbled_past", "pressures", "tackles", "tackles_won",
    "interceptions", "recoveries", "aerials_won", "aerials_lost", "up_passes_att", "up_passes_cmp",
]

# Metrics exposed to search/percentiles. Volume metrics are per 90; *_pct are rates.
PER90_METRICS = [
    "np_goals", "np_xg", "xa", "shots", "key_passes", "prog_passes", "prog_carries",
    "final_third_passes", "box_passes", "dribbles_cmp", "pressures", "tackles_interceptions", "recoveries",
]
RATE_METRICS = {
    "pass_cmp_pct": ("passes_cmp", "passes_att"),
    "pass_cmp_under_pressure_pct": ("up_passes_cmp", "up_passes_att"),
    "aerial_win_pct": ("aerials_won", "aerials_total"),
    "ground_duel_win_pct": ("ground_duels_won", "ground_duels"),
    "dribble_success_pct": ("dribbles_cmp", "dribbles_att"),
}
# Minimum total attempts before a rate is shown (otherwise NULL).
RATE_MIN_ATTEMPTS = {"aerial_win_pct": 10, "ground_duel_win_pct": 15, "dribble_success_pct": 10,
                     "pass_cmp_under_pressure_pct": 20, "pass_cmp_pct": 50}
ALL_METRICS = PER90_METRICS + list(RATE_METRICS)


def _clock(t: str) -> float:
    m, s = t.split(":")
    return int(m) * 60 + int(s)


def _dist(p) -> float:
    return math.hypot(GOAL[0] - p[0], GOAL[1] - p[1])


def _progressive(start, end) -> bool:
    return start[0] >= 48 and _dist(end) <= 0.75 * _dist(start)


def _in_box(p) -> bool:
    return p[0] >= 102 and 18 <= p[1] <= 62


def match_player_stats(events: list[dict], lineups: list[dict]) -> list[dict]:
    """One row per player who played in the match: minutes, position, raw counts."""
    end_clock = max((e["minute"] * 60 + e["second"] for e in events if e["period"] <= 4), default=90 * 60)

    rows: dict[int, dict] = {}
    for team in lineups:
        for p in team["lineup"]:
            pos_minutes: Counter = Counter()
            for stint in p["positions"]:
                if stint.get("from_period", 1) > 4:
                    continue
                start = _clock(stint["from"])
                stop = _clock(stint["to"]) if stint.get("to") else end_clock
                pos_minutes[stint["position"]] += max(stop - start, 0) / 60
            minutes = sum(pos_minutes.values())
            if minutes <= 0:
                continue
            rows[p["player_id"]] = {
                "sb_player_id": p["player_id"],
                "player_name": p["player_name"],
                "player_nickname": p.get("player_nickname"),
                "country": (p.get("country") or {}).get("name"),
                "team_name": team["team_name"],
                "minutes": minutes,
                "position_minutes": dict(pos_minutes),
                **{f: 0.0 for f in COUNT_FIELDS},
            }

    by_id = {e["id"]: e for e in events}
    for e in events:
        if e["period"] > 4 or "player" not in e:
            continue
        r = rows.get(e["player"]["id"])
        if r is None:
            continue
        t = e["type"]["name"]

        if t == "Shot":
            shot = e["shot"]
            if shot["type"]["name"] == "Penalty":
                continue
            r["shots"] += 1
            r["np_xg"] += shot.get("statsbomb_xg", 0.0)
            r["np_goals"] += shot["outcome"]["name"] == "Goal"
            if shot.get("aerial_won"):
                r["aerials_won"] += 1
            kp = by_id.get(shot.get("key_pass_id"))
            if kp and "player" in kp and kp["player"]["id"] in rows:
                rows[kp["player"]["id"]]["xa"] += shot.get("statsbomb_xg", 0.0)

        elif t == "Pass":
            ps = e["pass"]
            if ps.get("aerial_won"):
                r["aerials_won"] += 1
            ptype = (ps.get("type") or {}).get("name")
            if ptype in SET_PIECES:
                continue
            completed = "outcome" not in ps
            r["passes_att"] += 1
            r["passes_cmp"] += completed
            if e.get("under_pressure"):
                r["up_passes_att"] += 1
                r["up_passes_cmp"] += completed
            if ps.get("shot_assist") or ps.get("goal_assist"):
                r["key_passes"] += 1
            if ps.get("goal_assist"):
                r["assists"] += 1
            if completed:
                start, end = e["location"], ps["end_location"]
                r["prog_passes"] += _progressive(start, end)
                r["final_third_passes"] += start[0] < 80 <= end[0]
                r["box_passes"] += _in_box(end) and not _in_box(start)

        elif t == "Carry":
            start, end = e["location"], e["carry"]["end_location"]
            if math.dist(start, end) >= 5 and _progressive(start, end):
                r["prog_carries"] += 1

        elif t == "Dribble":
            r["dribbles_att"] += 1
            r["dribbles_cmp"] += e["dribble"]["outcome"]["name"] == "Complete"

        elif t == "Dribbled Past":
            r["dribbled_past"] += 1

        elif t == "Pressure":
            r["pressures"] += 1

        elif t == "Duel":
            dtype = e["duel"]["type"]["name"]
            if dtype == "Tackle":
                r["tackles"] += 1
                r["tackles_won"] += (e["duel"].get("outcome") or {}).get("name") in TACKLE_WON
            elif dtype == "Aerial Lost":
                r["aerials_lost"] += 1

        elif t == "Interception":
            r["interceptions"] += 1

        elif t == "Ball Recovery":
            if not (e.get("ball_recovery") or {}).get("recovery_failure"):
                r["recoveries"] += 1

        elif t in ("Clearance", "Miscontrol"):
            if (e.get(t.lower()) or {}).get("aerial_won"):
                r["aerials_won"] += 1

    return list(rows.values())


def _process_match(args: tuple[Path, int]) -> list[dict]:
    sb_dir, match_id = args
    events = json.loads((sb_dir / "events" / f"{match_id}.json").read_text(encoding="utf-8"))
    lineups = json.loads((sb_dir / "lineups" / f"{match_id}.json").read_text(encoding="utf-8"))
    out = match_player_stats(events, lineups)
    for r in out:
        r["match_id"] = match_id
    return out


def aggregate(match_rows: pd.DataFrame) -> pd.DataFrame:
    """Sum match rows to (player, competition season) and derive per-90 metrics and rates."""
    keys = ["sb_player_id", "competition_id", "season_id"]
    pos = defaultdict(Counter)
    for r in match_rows.itertuples():
        for name, mins in r.position_minutes.items():
            pos[(r.sb_player_id, r.competition_id, r.season_id)][name] += mins

    agg = match_rows.groupby(keys).agg(
        player_name=("player_name", "last"),
        player_nickname=("player_nickname", "last"),
        country=("country", "last"),
        team_name=("team_name", lambda s: s.value_counts().index[0]),
        competition=("competition", "first"),
        matches=("match_id", "nunique"),
        minutes=("minutes", "sum"),
        **{f: (f, "sum") for f in COUNT_FIELDS},
    ).reset_index()

    agg["sb_position"] = [pos[k].most_common(1)[0][0] for k in zip(*(agg[c] for c in keys))]
    agg["position_group"] = agg["sb_position"].map(SB_POSITION_GROUPS)
    agg["tackles_interceptions"] = agg["tackles"] + agg["interceptions"]
    agg["aerials_total"] = agg["aerials_won"] + agg["aerials_lost"]
    agg["ground_duels_won"] = agg["tackles_won"] + agg["dribbles_cmp"]
    agg["ground_duels"] = agg["tackles"] + agg["dribbles_att"] + agg["dribbled_past"]

    nineties = agg["minutes"] / 90
    for m in PER90_METRICS:
        agg[f"{m}_p90"] = agg[m] / nineties
    for m, (num, den) in RATE_METRICS.items():
        rate = 100 * agg[num] / agg[den].where(agg[den] > 0)
        agg[m] = rate.where(agg[den] >= RATE_MIN_ATTEMPTS[m])
    return agg


def percentiles(per90: pd.DataFrame) -> pd.DataFrame:
    """Percentile (0-100) of each metric within position group, outfield players only."""
    cols = [f"{m}_p90" for m in PER90_METRICS] + list(RATE_METRICS)
    df = per90[per90["position_group"].ne("GK")].copy()
    out = df[["sb_player_id", "competition_id", "season_id", "position_group"]].copy()
    for c, m in zip(cols, ALL_METRICS):
        out[m] = (df.groupby("position_group")[c].rank(pct=True) * 100).round(1)
    return out


def build_performance_layer(con: duckdb.DuckDBPyConnection, sb_dir: Path = SB_DIR, workers: int = 8) -> None:
    jobs, comp_of = [], {}
    for comp_id, season_id, label in SB_COMPETITIONS:
        path = sb_dir / "matches" / str(comp_id) / f"{season_id}.json"
        for m in json.loads(path.read_text(encoding="utf-8")):
            comp_of[m["match_id"]] = (comp_id, season_id, label)
            jobs.append((sb_dir, m["match_id"]))

    rows = []
    with ProcessPoolExecutor(workers) as pool:
        for chunk in pool.map(_process_match, jobs, chunksize=8):
            rows.extend(chunk)
    df = pd.DataFrame(rows)
    df["competition_id"] = df["match_id"].map(lambda m: comp_of[m][0])
    df["season_id"] = df["match_id"].map(lambda m: comp_of[m][1])
    df["competition"] = df["match_id"].map(lambda m: comp_of[m][2])

    agg = aggregate(df)
    sb_players = agg[["sb_player_id", "competition_id", "season_id", "competition", "player_name",
                      "player_nickname", "country", "team_name", "matches", "minutes",
                      "sb_position", "position_group"]]
    per90 = agg[agg["minutes"] >= MIN_MINUTES]
    per90 = per90[["sb_player_id", "competition_id", "season_id", "competition", "team_name", "minutes",
                   "matches", "position_group", "sb_position"]
                  + [f"{m}_p90" for m in PER90_METRICS] + list(RATE_METRICS)]
    pct = percentiles(per90)

    con.register("sb_players_df", sb_players)
    con.register("per90_df", per90)
    con.register("pct_df", pct)
    con.execute("CREATE OR REPLACE TABLE sb_players AS SELECT * FROM sb_players_df")
    con.execute("CREATE OR REPLACE TABLE sb_player_per90 AS SELECT * FROM per90_df")
    con.execute("CREATE OR REPLACE TABLE sb_percentiles AS SELECT * FROM pct_df")
    for v in ("sb_players_df", "per90_df", "pct_df"):
        con.unregister(v)
