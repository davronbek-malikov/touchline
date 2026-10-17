"""Build warehouse/touchline.duckdb from the raw sources.

Usage: python -m data.build_warehouse [--skip-statsbomb]

Market layer (Transfermarkt) tables:
  leagues, players, player_seasons, value_history
Performance layer (StatsBomb, see data/statsbomb_per90.py):
  sb_players, sb_player_per90, sb_percentiles
Linking (see data/link_players.py, data/performance.py):
  player_links, player_performance
"""
import argparse
from pathlib import Path

import duckdb

from data.config import SB_DIR, TM_DUCKDB, WAREHOUSE

DATA_AS_OF = "2026-07-06"

# Transfermarkt sub_position -> Touchline position group.
POSITION_GROUPS = {
    "Goalkeeper": "GK",
    "Centre-Back": "CB",
    "Left-Back": "FB",
    "Right-Back": "FB",
    "Defensive Midfield": "DM",
    "Central Midfield": "CM",
    "Left Midfield": "W",
    "Right Midfield": "W",
    "Attacking Midfield": "AM",
    "Left Winger": "W",
    "Right Winger": "W",
    "Second Striker": "ST",
    "Centre-Forward": "ST",
}


def build_market_layer(con: duckdb.DuckDBPyConnection, tm_path: Path) -> None:
    con.execute(f"ATTACH '{tm_path.as_posix()}' AS tm (READ_ONLY)")
    con.execute("CREATE OR REPLACE TABLE meta AS SELECT 'data_as_of' AS key, ? AS value", [DATA_AS_OF])

    con.execute("""
        CREATE OR REPLACE TABLE leagues AS
        SELECT competition_id AS league_id, name AS league_slug, country_name, type, confederation
        FROM tm.competitions
    """)

    mapping = ", ".join(f"('{k}', '{v}')" for k, v in POSITION_GROUPS.items())
    con.execute(f"""
        CREATE OR REPLACE TABLE players AS
        WITH pg(sub_position, position_group) AS (VALUES {mapping})
        SELECT
            p.player_id,
            p.name,
            CAST(p.date_of_birth AS DATE) AS date_of_birth,
            -- whole years: subtract one if the birthday hasn't happened yet that year
            year(DATE '{DATA_AS_OF}') - year(p.date_of_birth)
              - CASE WHEN strftime(DATE '{DATA_AS_OF}', '%m%d') < strftime(p.date_of_birth, '%m%d') THEN 1 ELSE 0 END
              AS age,
            p.position,
            p.sub_position,
            pg.position_group,
            NULLIF(p.foot, '') AS foot,
            p.height_in_cm,
            p.country_of_citizenship AS nationality,
            p.country_of_birth,
            TRY_CAST(p.current_club_id AS INTEGER) AS club_id,
            p.current_club_name AS club_name,
            p.current_club_domestic_competition_id AS league_id,
            l.country_name AS league_country,
            CAST(p.contract_expiration_date AS DATE) AS contract_until,
            p.market_value_in_eur AS market_value_eur,
            p.highest_market_value_in_eur AS highest_market_value_eur,
            p.international_caps,
            p.international_goals,
            TRY_CAST(p.last_season AS INTEGER) AS last_season,
            TRY_CAST(p.last_season AS INTEGER) >= 2025 AS is_active,
            p.image_url,
            p.url AS tm_url
        FROM tm.players p
        LEFT JOIN pg USING (sub_position)
        LEFT JOIN tm.competitions l ON l.competition_id = p.current_club_domestic_competition_id
    """)

    # Seasons run July -> June; "2024" means 2024/25.
    con.execute("""
        CREATE OR REPLACE TABLE player_seasons AS
        SELECT
            a.player_id,
            CASE WHEN month(a.date) >= 7 THEN year(a.date) ELSE year(a.date) - 1 END AS season,
            a.competition_id,
            c.type AS competition_type,
            count(*) AS appearances,
            sum(a.minutes_played) AS minutes,
            sum(a.goals) AS goals,
            sum(a.assists) AS assists,
            sum(a.yellow_cards) AS yellow_cards,
            sum(a.red_cards) AS red_cards
        FROM tm.appearances a
        LEFT JOIN tm.competitions c USING (competition_id)
        GROUP BY ALL
    """)

    con.execute("""
        CREATE OR REPLACE TABLE value_history AS
        SELECT player_id, date, market_value_in_eur AS market_value_eur, current_club_name AS club_name
        FROM tm.player_valuations
        ORDER BY player_id, date
    """)
    con.execute("DETACH tm")


def build(skip_statsbomb: bool = False) -> None:
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE))
    build_market_layer(con, TM_DUCKDB)
    if not skip_statsbomb:
        from data.statsbomb_per90 import build_performance_layer
        from data.link_players import build_links

        from data.performance import build_player_performance

        build_performance_layer(con, SB_DIR)
        build_links(con)
        build_player_performance(con)
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall():
        print(f"{t:20s} {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>10,}")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-statsbomb", action="store_true")
    build(ap.parse_args().skip_statsbomb)
