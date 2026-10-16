"""find_player, search_players, get_player_profile, compare_players."""
from rapidfuzz import fuzz

from agent.schemas import (LEAGUES, METRIC_DESCRIPTIONS, ComparePlayersInput, FindPlayerInput,
                           PlayerIdInput, SearchPlayersInput)
from agent.tools.db import ToolError, data_as_of, rows
from data.config import LATEST_SEASON
from data.link_players import norm
from data.statsbomb_per90 import ALL_METRICS

MAX_METRIC_FILTERS = 6

_BASE_COLUMNS = """
    p.player_id, p.name, p.age, p.position_group, p.sub_position, p.foot, p.height_in_cm,
    p.nationality, p.club_name, p.league_id, p.market_value_eur, p.contract_until,
    coalesce(m.minutes, 0) AS minutes_2025_26,
    CASE WHEN pp.player_id IS NULL THEN 'market only' ELSE 'market + events' END AS coverage
"""

_JOINS = f"""
    FROM players p
    LEFT JOIN (SELECT player_id, sum(minutes) AS minutes FROM player_seasons
               WHERE season = {LATEST_SEASON} GROUP BY player_id) m USING (player_id)
    LEFT JOIN player_performance pp USING (player_id)
"""


def find_player(args: FindPlayerInput) -> dict:
    """Fuzzy name lookup. Exact and prefix matches first, then by name score and market value."""
    q = norm(args.name)
    if not q:
        raise ToolError("empty name")
    tokens = q.split()
    # Cheap SQL prefilter on any query token, then score in Python.
    like = " OR ".join(["strip_accents(lower(name)) LIKE ?"] * len(tokens))
    cands = rows(f"""
        SELECT player_id, name, age, position_group, club_name, nationality, market_value_eur, is_active
        FROM players WHERE {like}
    """, [f"%{t}%" for t in tokens])
    scored = []
    for c in cands:
        s = _name_match(q, norm(c["name"]))
        if s >= 70:
            scored.append((s, c["is_active"], c["market_value_eur"] or 0, c))
    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    out = [dict(c, match_score=round(s)) for s, _, _, c in scored[: args.limit]]
    return {"query": args.name, "candidates": out,
            "note": None if out else "No player with a similar name is in the database."}


def _name_match(q: str, n: str) -> float:
    """Exact > every query token present (fewer extra tokens first) > fuzzy."""
    if q == n:
        return 101
    qt, nt = q.split(), n.split()
    if set(qt) <= set(nt):
        return 95 - 2 * (len(nt) - len(qt))  # "yamal" -> "lamine yamal" = 93
    return max(0.6 * fuzz.token_set_ratio(q, n) + 0.4 * fuzz.token_sort_ratio(q, n), fuzz.ratio(q, n))


def search_players(args: SearchPlayersInput) -> dict:
    where, params = ["p.is_active"], []

    def add(cond: str, *vals):
        where.append(cond)
        params.extend(vals)

    if args.position_groups:
        add(f"p.position_group IN ({_ph(args.position_groups)})", *args.position_groups)
    if args.sub_positions:
        add(f"p.sub_position IN ({_ph(args.sub_positions)})", *args.sub_positions)
    if args.age_min is not None:
        add("p.age >= ?", args.age_min)
    if args.age_max is not None:
        add("p.age <= ?", args.age_max)
    if args.value_min_eur is not None:
        add("p.market_value_eur >= ?", args.value_min_eur)
    if args.value_max_eur is not None:
        add("p.market_value_eur <= ?", args.value_max_eur)
    if args.foot:
        add("p.foot = ?", args.foot)
    if args.height_min_cm is not None:
        add("p.height_in_cm >= ?", args.height_min_cm)
    if args.contract_until_max:
        add("p.contract_until <= ?", args.contract_until_max)
    if args.leagues:
        add(f"p.league_id IN ({_ph(args.leagues)})", *args.leagues)
    if args.nationalities:
        add(f"lower(p.nationality) IN ({_ph(args.nationalities)})", *[n.lower() for n in args.nationalities])
    if args.min_minutes is not None:
        add("coalesce(m.minutes, 0) >= ?", args.min_minutes)

    metric_filters = args.metric_filters or []
    if len(metric_filters) > MAX_METRIC_FILTERS:
        raise ToolError(f"at most {MAX_METRIC_FILTERS} metric filters")
    metric_cols = ""
    for f in metric_filters:
        m = f.metric
        add(f"pp.{m}_pct >= ?", f.percentile_min)  # m is an enum value, safe to inline
        metric_cols += f", pp.{m}_value AS {m}, pp.{m}_pct AS {m}_pct"
    if metric_filters:
        metric_cols += ", pp.event_competition, pp.event_minutes"

    if args.sort_by == "metric_filters_desc" and not metric_filters:
        raise ToolError("sort_by metric_filters_desc needs at least one metric filter")
    order = {
        "market_value_desc": "p.market_value_eur DESC NULLS LAST",
        "market_value_asc": "p.market_value_eur ASC NULLS LAST",
        "age_asc": "p.age ASC, p.market_value_eur DESC NULLS LAST",
        "minutes_desc": "minutes_2025_26 DESC",
        "metric_filters_desc": "(" + " + ".join(f"pp.{f.metric}_pct" for f in metric_filters) + ") DESC"
        if metric_filters else "",
    }[args.sort_by]

    sql_where = " AND ".join(where)
    total = rows(f"SELECT count(*) AS n {_JOINS} WHERE {sql_where}", params)[0]["n"]
    result = rows(f"""
        SELECT {_BASE_COLUMNS}{metric_cols}
        {_JOINS}
        WHERE {sql_where}
        ORDER BY {order}, p.player_id
        LIMIT {args.limit}
    """, params)

    notes = []
    if metric_filters:
        notes.append("Metric filters only match players with StatsBomb event data (~600 players from "
                     "Euro 2024, Copa América 2024, World Cup 2022, AFCON 2023 and selected club seasons). "
                     "Percentiles are within position group.")
    if not result:
        notes.append("No players match. Consider relaxing the strictest filter.")
    return {"total_matches": total, "returned": len(result), "players": result,
            "data_as_of": data_as_of(), "notes": notes}


def get_player_profile(args: PlayerIdInput) -> dict:
    bio = rows(f"""
        SELECT {_BASE_COLUMNS}, p.date_of_birth, p.highest_market_value_eur, p.international_caps,
               p.international_goals, p.country_of_birth, p.is_active
        {_JOINS} WHERE p.player_id = ?
    """, [args.player_id])
    if not bio:
        raise ToolError(f"no player with id {args.player_id}")
    bio = bio[0]
    bio["league"] = LEAGUES.get(bio["league_id"], bio["league_id"])

    seasons = rows(f"""
        SELECT season, sum(appearances) AS appearances, sum(minutes) AS minutes, sum(goals) AS goals,
               sum(assists) AS assists, sum(yellow_cards) AS yellow_cards, sum(red_cards) AS red_cards
        FROM player_seasons WHERE player_id = ? AND season >= ?
        GROUP BY season ORDER BY season DESC
    """, [args.player_id, LATEST_SEASON - 3])
    for s in seasons:
        s["season"] = f"{s['season']}/{str(s['season'] + 1)[-2:]}"

    history = rows("""
        SELECT date, market_value_eur, club_name FROM value_history
        WHERE player_id = ? ORDER BY date DESC LIMIT 12
    """, [args.player_id])

    perf = _event_profile(args.player_id)
    return {
        "player": bio,
        "seasons": seasons,
        "market_value_history": history[::-1],
        "event_profile": perf,
        "archetype": None,  # TacticalDNA archetypes arrive in milestone 6
        "data_as_of": data_as_of(),
        "notes": [] if perf else ["No StatsBomb event data for this player (market only)."],
    }


def _event_profile(player_id: int) -> dict | None:
    r = rows("SELECT * FROM player_performance WHERE player_id = ?", [player_id])
    if not r:
        return None
    r = r[0]
    return {
        "competition": r["event_competition"],
        "minutes": r["event_minutes"],
        "matches": r["event_matches"],
        "position_group": r["event_position_group"],
        "metrics": {m: {"value": r[f"{m}_value"], "percentile": r[f"{m}_pct"],
                        "description": METRIC_DESCRIPTIONS[m]} for m in ALL_METRICS},
    }


def compare_players(args: ComparePlayersInput) -> dict:
    if len(set(args.player_ids)) != len(args.player_ids):
        raise ToolError("player_ids must be distinct")
    players = []
    for pid in args.player_ids:
        bio = rows(f"SELECT {_BASE_COLUMNS} {_JOINS} WHERE p.player_id = ?", [pid])
        if not bio:
            raise ToolError(f"no player with id {pid}")
        perf = _event_profile(pid)
        players.append({**bio[0], "event_profile": perf})
    groups = {p["event_profile"]["position_group"] for p in players if p["event_profile"]}
    notes = []
    if len(groups) > 1:
        notes.append("Players were profiled in different position groups, so percentiles are not directly comparable.")
    if any(p["event_profile"] is None for p in players):
        notes.append("Some players have no event data (market only); only market fields can be compared for them.")
    return {"players": players, "data_as_of": data_as_of(), "notes": notes}


def _ph(values) -> str:
    return ", ".join("?" * len(values))
