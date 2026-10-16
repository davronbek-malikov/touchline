"""similar_players: cosine similarity on z-scored event profiles.

v1 baseline. Milestone 6 swaps in the TacticalDNA engine behind the same interface.
"""
import numpy as np
import pandas as pd

from agent.schemas import METRIC_DESCRIPTIONS, SimilarPlayersInput
from agent.tools.db import ToolError, cursor, data_as_of
from data.statsbomb_per90 import ALL_METRICS

TRAIT_Z = 0.5  # both players at least this many std devs above the group mean


def _profiles() -> pd.DataFrame:
    cols = ", ".join(f"pp.{m}_value AS {m}" for m in ALL_METRICS)
    return cursor().execute(f"""
        SELECT pp.player_id, p.name, p.age, p.club_name, p.league_id, p.market_value_eur, p.is_active,
               pp.event_position_group AS position_group, pp.event_competition, {cols}
        FROM player_performance pp JOIN players p USING (player_id)
        WHERE pp.event_position_group <> 'GK'
    """).df()


def similar_players(args: SimilarPlayersInput) -> dict:
    df = _profiles()
    ref = df[df["player_id"] == args.player_id]
    if ref.empty:
        raise ToolError("this player has no StatsBomb event profile (or is a goalkeeper), so similarity "
                        "can't be computed; use search_players with position and value filters instead")
    ref = ref.iloc[0]
    pool = df[df["position_group"] == ref["position_group"]] if args.same_position else df

    # z-score within each position group so a CB's 3 progressive passes and a CM's 6 are both "high".
    feats = df[ALL_METRICS].astype(float)
    z = (feats - feats.groupby(df["position_group"]).transform("mean")) / feats.groupby(
        df["position_group"]).transform("std").replace(0, np.nan)
    z = z.fillna(0.0)

    ref_vec = z.loc[ref.name].to_numpy()
    cand = pool[(pool["player_id"] != args.player_id) & pool["is_active"]]
    if args.value_max_eur is not None:
        cand = cand[cand["market_value_eur"] <= args.value_max_eur]
    if args.age_max is not None:
        cand = cand[cand["age"] <= args.age_max]
    if cand.empty:
        return {"reference": _ref(ref), "players": [], "data_as_of": data_as_of(),
                "notes": ["No candidates match the constraints."]}

    mat = z.loc[cand.index].to_numpy()
    sims = mat @ ref_vec / (np.linalg.norm(mat, axis=1) * np.linalg.norm(ref_vec) + 1e-9)
    top = np.argsort(-sims)[: args.limit]

    out = []
    for i in top:
        idx = cand.index[i]
        shared = [(m, min(ref_vec[j], z.at[idx, m])) for j, m in enumerate(ALL_METRICS)
                  if ref_vec[j] >= TRAIT_Z and z.at[idx, m] >= TRAIT_Z]
        shared.sort(key=lambda t: -t[1])
        row = cand.loc[idx]
        out.append({
            "player_id": int(row["player_id"]), "name": row["name"], "age": _int(row["age"]),
            "club_name": row["club_name"], "league_id": row["league_id"],
            "market_value_eur": _int(row["market_value_eur"]), "position_group": row["position_group"],
            "event_competition": row["event_competition"],
            "similarity": round(float(sims[i]), 3),
            "shared_traits": [METRIC_DESCRIPTIONS[m] for m, _ in shared[:4]],
        })
    return {"reference": _ref(ref), "players": out, "data_as_of": data_as_of(),
            "notes": ["Similarity uses StatsBomb event profiles, so only ~600 players with event data are candidates."]}


def _ref(ref: pd.Series) -> dict:
    return {"player_id": int(ref["player_id"]), "name": ref["name"], "position_group": ref["position_group"],
            "event_competition": ref["event_competition"], "market_value_eur": _int(ref["market_value_eur"])}


def _int(v):
    return None if pd.isna(v) else int(v)
