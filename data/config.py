"""Paths and source selection shared by the data pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
TM_DUCKDB = RAW / "transfermarkt.duckdb"
SB_DIR = RAW / "statsbomb"
WAREHOUSE = ROOT / "warehouse" / "touchline.duckdb"

TM_URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.duckdb"
SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# (competition_id, season_id, label). Recent men's competitions whose players
# overlap with the Transfermarkt snapshot (current to 6 July 2026).
SB_COMPETITIONS = [
    (55, 282, "UEFA Euro 2024"),
    (223, 282, "Copa America 2024"),
    (43, 106, "FIFA World Cup 2022"),
    (1267, 107, "AFCON 2023"),
    (9, 281, "Bundesliga 2023/24"),
    (44, 107, "MLS 2023"),
    (7, 235, "Ligue 1 2022/23"),
    (7, 108, "Ligue 1 2021/22"),
]

MIN_MINUTES = 270
