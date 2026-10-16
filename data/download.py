"""Download raw sources: the Transfermarkt DuckDB file and StatsBomb open data.

Usage: python -m data.download [--tm] [--sb]
Files already on disk are skipped, so the script is safe to re-run.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from data.config import RAW, SB_BASE, SB_COMPETITIONS, SB_DIR, TM_DUCKDB, TM_URL


def _fetch(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest


def download_transfermarkt() -> None:
    RAW.mkdir(exist_ok=True)
    _fetch(TM_URL, TM_DUCKDB)
    print(f"transfermarkt: {TM_DUCKDB} ({TM_DUCKDB.stat().st_size / 1e6:.0f} MB)")


def download_statsbomb(workers: int = 16) -> None:
    _fetch(f"{SB_BASE}/competitions.json", SB_DIR / "competitions.json")
    match_ids: list[int] = []
    for comp_id, season_id, label in SB_COMPETITIONS:
        path = _fetch(f"{SB_BASE}/matches/{comp_id}/{season_id}.json",
                      SB_DIR / "matches" / str(comp_id) / f"{season_id}.json")
        matches = json.loads(path.read_text(encoding="utf-8"))
        match_ids += [m["match_id"] for m in matches]
        print(f"statsbomb: {label}: {len(matches)} matches")

    jobs = []
    for mid in match_ids:
        jobs.append((f"{SB_BASE}/events/{mid}.json", SB_DIR / "events" / f"{mid}.json"))
        jobs.append((f"{SB_BASE}/lineups/{mid}.json", SB_DIR / "lineups" / f"{mid}.json"))
    with ThreadPoolExecutor(workers) as pool:
        for i, _ in enumerate(pool.map(lambda j: _fetch(*j), jobs), 1):
            if i % 200 == 0:
                print(f"statsbomb: {i}/{len(jobs)} files")
    print(f"statsbomb: {len(match_ids)} matches downloaded")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tm", action="store_true")
    ap.add_argument("--sb", action="store_true")
    args = ap.parse_args()
    both = not (args.tm or args.sb)
    if args.tm or both:
        download_transfermarkt()
    if args.sb or both:
        download_statsbomb()
