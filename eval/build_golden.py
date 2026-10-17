"""Build eval/golden.jsonl from eval/golden_spec.py using the warehouse.

Usage: python -m eval.build_golden
Fails if a reference player can't be resolved or a gold search returns nothing.
"""
import json
from pathlib import Path

from agent.tools import run_tool
from agent.tools.db import rows
from data.config import LATEST_SEASON
from eval import golden_spec as spec

OUT = Path(__file__).parent / "golden.jsonl"
GOLD_K = 10


def _call(name: str, args: dict) -> dict:
    out, is_error = run_tool(name, args)
    data = json.loads(out)
    if is_error:
        raise ValueError(f"{name}({args}) failed: {data}")
    return data


def resolve(name: str) -> dict:
    cands = _call("find_player", {"name": name, "limit": 3})["candidates"]
    if not cands or cands[0]["match_score"] < 93:
        raise ValueError(f"can't resolve {name!r}: {cands[:1]}")
    return cands[0]


def fact_value(pid: int, key: str):
    if key in ("market_value_eur", "age", "club_name", "contract_until", "height_in_cm", "foot",
               "highest_market_value_eur", "nationality", "international_caps"):
        return rows(f"SELECT {key} FROM players WHERE player_id = ?", [pid])[0][key]
    if key == "minutes_2025_26":
        return rows("SELECT coalesce(sum(minutes), 0) AS v FROM player_seasons WHERE player_id = ? AND season = ?",
                    [pid, LATEST_SEASON])[0]["v"]
    if key.startswith(("goals_", "assists_")):
        stat, season = key.split("_", 1)
        return rows(f"SELECT coalesce(sum({stat}), 0) AS v FROM player_seasons WHERE player_id = ? AND season = ?",
                    [pid, int(season[:4])])[0]["v"]
    if key == "value_june_2026":
        r = rows("""SELECT market_value_eur AS v FROM value_history WHERE player_id = ?
                    AND date < DATE '2026-07-01' ORDER BY date DESC LIMIT 1""", [pid])
        return r[0]["v"]
    if key.endswith(("_value", "_pct")):
        return rows(f"SELECT {key} AS v FROM player_performance WHERE player_id = ?", [pid])[0]["v"]
    raise KeyError(key)


def build() -> list[dict]:
    items = []

    def add(kind: str, i: int, query: str, reference: dict, tags=()):
        item_id = f"{kind}-{i:02d}"
        items.append({"id": item_id, "type": kind, "query": query, "tags": list(tags),
                      "ci": item_id in spec.CI_IDS, "reference": reference})

    for i, entry in enumerate(spec.FILTER, 1):
        query, gold = entry[0], entry[1]
        tags = entry[2:] or ("explicit",)
        res = _call("search_players", gold | {"limit": GOLD_K})
        if not res["total_matches"]:
            raise ValueError(f"filter-{i:02d} has an empty gold set: {query}")
        add("filter", i, query, {"gold_filter": gold, "total_matches": res["total_matches"],
                                 "gold_player_ids": [p["player_id"] for p in res["players"]],
                                 "gold_player_names": [p["name"] for p in res["players"]]}, tags)

    for i, (query, name, extra) in enumerate(spec.SIMILAR, 1):
        ref = resolve(name)
        args = {"player_id": ref["player_id"], **extra}
        res = _call("similar_players", args)
        if not res["players"]:
            raise ValueError(f"similar-{i:02d} has an empty gold set")
        add("similar", i, query, {"reference_player": ref["name"], "gold_args": args,
                                  "gold_player_ids": [p["player_id"] for p in res["players"]],
                                  "gold_player_names": [p["name"] for p in res["players"]]})

    for i, (query, name, key) in enumerate(spec.FACT, 1):
        ref = resolve(name)
        value = fact_value(ref["player_id"], key)
        if value is None:
            raise ValueError(f"fact-{i:02d}: {key} is NULL for {name}")
        add("fact", i, query, {"player_id": ref["player_id"], "player": ref["name"], "fact": key,
                               "gold_value": value})

    for i, name in enumerate(spec.REPORT, 1):
        ref = resolve(name)
        add("report", i, f"Write a scouting report on {name}.", {"player_id": ref["player_id"], "player": ref["name"]})

    for i, (query, reason) in enumerate(spec.TRAP, 1):
        add("trap", i, query, {"reason": reason, "expect_no_data": True})

    missing = set(spec.CI_IDS) - {it["id"] for it in items}
    if missing:
        raise ValueError(f"CI ids not in the set: {missing}")
    return items


if __name__ == "__main__":
    items = build()
    OUT.write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
    by_type = {}
    for it in items:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    print(f"{len(items)} items -> {OUT}  {by_type}  ci={sum(it['ci'] for it in items)}")
