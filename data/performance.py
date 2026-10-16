"""player_performance: one headline StatsBomb event profile per Transfermarkt player.

Picks the linked competition season with the latest year, then the most
minutes, and lays out each metric as <metric>_value and <metric>_pct.
"""
import duckdb

from data.config import SB_YEARS
from data.statsbomb_per90 import ALL_METRICS, PER90_METRICS


def _value_col(m: str) -> str:
    return f"{m}_p90" if m in PER90_METRICS else m


def build_player_performance(con: duckdb.DuckDBPyConnection) -> None:
    years = ", ".join(f"({c}, {s}, {y})" for (c, s), y in SB_YEARS.items())
    metric_cols = ",\n            ".join(
        f"v.{_value_col(m)} AS {m}_value, q.{m} AS {m}_pct" for m in ALL_METRICS
    )
    con.execute(f"""
        CREATE OR REPLACE TABLE player_performance AS
        WITH yr(competition_id, season_id, year) AS (VALUES {years})
        SELECT
            l.tm_player_id AS player_id,
            v.sb_player_id,
            v.competition AS event_competition,
            yr.year AS event_year,
            round(v.minutes) AS event_minutes,
            v.matches AS event_matches,
            v.position_group AS event_position_group,
            {metric_cols}
        FROM sb_player_per90 v
        JOIN player_links l ON l.sb_player_id = v.sb_player_id AND l.tm_player_id IS NOT NULL
        LEFT JOIN sb_percentiles q
          ON q.sb_player_id = v.sb_player_id AND q.competition_id = v.competition_id AND q.season_id = v.season_id
        LEFT JOIN yr ON yr.competition_id = v.competition_id AND yr.season_id = v.season_id
        QUALIFY row_number() OVER (PARTITION BY l.tm_player_id ORDER BY yr.year DESC, v.minutes DESC) = 1
    """)
