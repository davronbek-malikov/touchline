"""Fetch Wikipedia "Style of play" sections for warehouse players.

Players map to English Wikipedia through Wikidata's Transfermarkt player ID
(P2446), so no name matching is involved. Each page is cached as
raw/wikipedia/<tm_player_id>.json (also when it has no style section).
Text is CC BY-SA 4.0: the title, URL and revision id are stored for attribution.

Usage: python -m data.wikipedia_fetch [--top 800]
"""
import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import duckdb
import requests

from data.config import RAW, WAREHOUSE

WIKI_DIR = RAW / "wikipedia"
SPARQL = "https://query.wikidata.org/sparql"
API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "Touchline/0.1 (football scouting research project; "
                         "https://github.com/davronbek-malikov/touchline)"}
STYLE_HEADING = re.compile(r"style of play|playing style|player profile|style and reception", re.I)
_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)


def candidates(top: int) -> list[int]:
    """Players with event data, plus the most valuable active players."""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    ids = con.execute(f"""
        SELECT player_id FROM player_performance
        UNION
        SELECT player_id FROM (SELECT player_id FROM players WHERE is_active
                               ORDER BY market_value_eur DESC NULLS LAST LIMIT {top})
    """).fetchall()
    return sorted(i for (i,) in ids)


def wikidata_titles(tm_ids: list[int], batch: int = 200) -> dict[int, str]:
    out = {}
    for i in range(0, len(tm_ids), batch):
        values = " ".join(f'"{t}"' for t in tm_ids[i:i + batch])
        q = f"""SELECT ?tm ?article WHERE {{
            VALUES ?tm {{ {values} }}
            ?item wdt:P2446 ?tm .
            ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
        }}"""
        r = requests.get(SPARQL, params={"query": q, "format": "json"}, headers=HEADERS, timeout=60)
        r.raise_for_status()
        for b in r.json()["results"]["bindings"]:
            title = requests.utils.unquote(b["article"]["value"].rsplit("/wiki/", 1)[1]).replace("_", " ")
            out[int(b["tm"]["value"])] = title
        time.sleep(1)
    return out


def style_section(text: str) -> str | None:
    """Text under the first style-of-play heading, including its subsections."""
    heads = [(m.start(), m.end(), len(m.group(1)), m.group(2)) for m in _HEADING.finditer(text)]
    for i, (_, end, level, title) in enumerate(heads):
        if STYLE_HEADING.search(title):
            stop = next((s for s, _, lvl, _ in heads[i + 1:] if lvl <= level), len(text))
            body = _HEADING.sub("", text[end:stop]).strip()
            return re.sub(r"\n{3,}", "\n\n", body) or None
    return None


def fetch_page(tm_id: int, title: str) -> dict:
    path = WIKI_DIR / f"{tm_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    r = requests.get(API, headers=HEADERS, timeout=60, params={
        "action": "query", "format": "json", "formatversion": 2, "redirects": 1, "titles": title,
        "prop": "extracts|revisions|info", "explaintext": 1, "exsectionformat": "wiki",
        "rvprop": "ids", "inprop": "url",
    })
    r.raise_for_status()
    page = r.json()["query"]["pages"][0]
    doc = {
        "tm_player_id": tm_id, "title": page.get("title", title), "url": page.get("fullurl"),
        "revision_id": (page.get("revisions") or [{}])[0].get("revid"),
        "licence": "CC BY-SA 4.0", "style_of_play": style_section(page.get("extract", "")),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def main(top: int, workers: int = 3) -> None:
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    ids = candidates(top)
    titles = wikidata_titles(ids)
    print(f"wikipedia: {len(ids)} candidates, {len(titles)} have an English article")

    def job(item):
        try:
            return fetch_page(*item)
        except requests.RequestException as e:
            print(f"  failed {item}: {e}")
            return None

    docs = []
    with ThreadPoolExecutor(workers) as pool:
        for i, d in enumerate(pool.map(job, titles.items()), 1):
            docs.append(d)
            if i % 100 == 0:
                print(f"  {i}/{len(titles)}")
    with_style = sum(1 for d in docs if d and d["style_of_play"])
    print(f"wikipedia: {with_style} pages with a style-of-play section")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=800, help="also fetch the N most valuable active players")
    main(ap.parse_args().top)
