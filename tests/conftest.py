"""A tiny warehouse built through the real build functions, for tool tests."""
import duckdb
import pandas as pd
import pytest

from agent.tools.db import set_warehouse
from data.build_warehouse import build_market_layer
from data.performance import build_player_performance
from data.statsbomb_per90 import ALL_METRICS, PER90_METRICS

# player_id, name, dob, sub_position, foot, height, nationality, club, league, contract, value, last_season
TM_PLAYERS = [
    (1, "Left Back Kid", "2004-03-01", "Left-Back", "left", 178, "England", "Some FC", "GB1", "2027-06-30", 8_000_000, "2025"),
    (2, "Old Striker", "1990-01-01", "Centre-Forward", "right", 185, "Spain", "Other FC", "GB1", None, 500_000, "2022"),
    (3, "Pablo Builder", "2005-02-01", "Centre-Back", "left", 188, "Spain", "Real Club", "ES1", "2027-06-30", 9_000_000, "2025"),
    (4, "Rugged Stopper", "2002-01-01", "Centre-Back", "right", 193, "Spain", "Real Club", "ES1", "2028-06-30", 4_000_000, "2025"),
    (5, "Market Only CB", "2006-01-01", "Centre-Back", "left", 186, "Netherlands", "Dutch FC", "NL1", "2026-06-30", 3_000_000, "2025"),
    (6, "Pablo Builder Senior", "2000-01-01", "Centre-Back", "left", 189, "Spain", "Big Club", "ES1", "2029-06-30", 30_000_000, "2025"),
    (7, "Pablo Builder Clone", "2003-01-01", "Centre-Back", "left", 187, "France", "French FC", "FR1", "2028-06-30", 7_000_000, "2025"),
]

# sb_player_id -> (tm_player_id, position_group, per-metric value)
SB = {
    101: (1, "FB", 1.0),
    103: (3, "CB", 9.0),   # elite build-up
    104: (4, "CB", 1.0),   # low build-up
    106: (6, "CB", 8.0),
    107: (7, "CB", 8.8),
}


def _make_tm(path):
    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE competitions AS SELECT * FROM (VALUES
        ('GB1', 'premier-league', 'England', 'domestic_league', 'europa'),
        ('ES1', 'laliga', 'Spain', 'domestic_league', 'europa'),
        ('NL1', 'eredivisie', 'Netherlands', 'domestic_league', 'europa'),
        ('FR1', 'ligue-1', 'France', 'domestic_league', 'europa'))
        t(competition_id, name, country_name, type, confederation)""")
    df = pd.DataFrame(TM_PLAYERS, columns=[
        "player_id", "name", "date_of_birth", "sub_position", "foot", "height_in_cm", "country_of_citizenship",
        "current_club_name", "current_club_domestic_competition_id", "contract_expiration_date",
        "market_value_in_eur", "last_season"])
    df["date_of_birth"] = pd.to_datetime(df["date_of_birth"])
    df["contract_expiration_date"] = pd.to_datetime(df["contract_expiration_date"])
    df["position"] = "x"
    df["country_of_birth"] = df["country_of_citizenship"]
    df["current_club_id"] = df["player_id"].astype(str)
    df["highest_market_value_in_eur"] = df["market_value_in_eur"]
    df["international_caps"] = 1
    df["international_goals"] = 0
    df["image_url"] = df["url"] = ""
    con.register("p", df)
    con.execute("CREATE TABLE players AS SELECT * FROM p")
    con.execute("""CREATE TABLE appearances AS SELECT * FROM (VALUES
        (1, DATE '2025-09-01', 'GB1', 2000, 1, 3, 0, 0),
        (3, DATE '2025-09-01', 'ES1', 2500, 2, 1, 4, 0),
        (4, DATE '2025-09-01', 'ES1', 900, 0, 0, 2, 1),
        (5, DATE '2025-09-01', 'NL1', 1500, 0, 0, 1, 0),
        (3, DATE '2024-09-01', 'ES1', 1200, 0, 0, 1, 0))
        t(player_id, date, competition_id, minutes_played, goals, assists, yellow_cards, red_cards)""")
    con.execute("""CREATE TABLE player_valuations AS SELECT * FROM (VALUES
        (3, DATE '2025-01-01', 5000000, 'Real Club', 3, 'ES1'),
        (3, DATE '2026-01-01', 9000000, 'Real Club', 3, 'ES1'))
        t(player_id, date, market_value_in_eur, current_club_name, current_club_id, player_club_domestic_competition_id)""")
    con.close()


def _add_events(con):
    per90, pct, links = [], [], []
    cb_vals = sorted(v for _, g, v in SB.values() if g == "CB")
    for sb_id, (tm_id, group, v) in SB.items():
        row = {"sb_player_id": sb_id, "competition_id": 55, "season_id": 282, "competition": "UEFA Euro 2024",
               "team_name": "Team", "minutes": 450.0, "matches": 5, "position_group": group, "sb_position": "x"}
        # prog_passes and pass_cmp_pct carry the signal; aerial_win_pct is inverted for variety.
        for m in ALL_METRICS:
            col = f"{m}_p90" if m in PER90_METRICS else m
            row[col] = (10 - v) if m == "aerial_win_pct" else v
        per90.append(row)
        rank = (cb_vals.index(v) + 1) / len(cb_vals) * 100 if group == "CB" else 100.0
        p = {"sb_player_id": sb_id, "competition_id": 55, "season_id": 282, "position_group": group}
        for m in ALL_METRICS:
            p[m] = (100 - rank + 100 / len(cb_vals)) if m == "aerial_win_pct" else rank
        pct.append(p)
        links.append({"sb_player_id": sb_id, "tm_player_id": tm_id, "name_score": 100.0, "team_match": False,
                      "method": "name+country", "runner_up_score": 0.0})
    for name, rows_ in [("sb_player_per90", per90), ("sb_percentiles", pct), ("player_links", links)]:
        con.register("t", pd.DataFrame(rows_))
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM t")
        con.unregister("t")


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory):
    d = tmp_path_factory.mktemp("wh")
    _make_tm(d / "tm.duckdb")
    path = d / "touchline.duckdb"
    con = duckdb.connect(str(path))
    build_market_layer(con, d / "tm.duckdb")
    _add_events(con)
    build_player_performance(con)
    con.close()
    set_warehouse(path)
    yield path
    set_warehouse(None)


PASSAGES = {
    3: ["Pablo Builder is a calm ball-playing defender who breaks lines with progressive passes and stays "
        "composed under pressure.", "He can be caught out by quick forwards in open space."],
    4: ["Rugged Stopper is dominant in the air and wins most of his duels, but he is slow on the turn and "
        "rarely plays forward passes."],
}


@pytest.fixture(scope="session")
def passage_index(warehouse, tmp_path_factory):
    """In-memory Qdrant index with a few Wikipedia-style passages, plus a temp notes DB."""
    from qdrant_client import QdrantClient

    from rag.index import PassageIndex, set_index
    from rag.notes import set_db

    index = PassageIndex(QdrantClient(":memory:"))
    chunks = [{"chunk_id": f"wiki:{pid}:1:{i}", "player_id": pid, "source": "wikipedia",
               "source_id": f"wiki:{pid}:{i}", "title": f"Wikipedia: player {pid} (Style of play)",
               "url": f"https://en.wikipedia.org/wiki/P{pid}", "licence": "CC BY-SA 4.0", "text": t}
              for pid, texts in PASSAGES.items() for i, t in enumerate(texts)]
    index.upsert(chunks)
    set_index(index)
    set_db(tmp_path_factory.mktemp("notes") / "notes.sqlite")
    yield index
    set_index(None)
    set_db(None)
