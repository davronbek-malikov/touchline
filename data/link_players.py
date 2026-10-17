"""Link StatsBomb players to Transfermarkt players.

StatsBomb open-data lineups carry name, nickname, nationality and team but no
date of birth, so a match needs a strong name score plus agreement on
nationality or on a club the player was valued at.

Table: player_links (sb_player_id -> tm_player_id, with scores and method).
Also writes data/labels/link_sample.csv for hand labelling (see eval_links.py).
"""
import re
import unicodedata
from collections import defaultdict

import duckdb
import pandas as pd
from rapidfuzz import fuzz, process

from data.config import ROOT

NAME_MIN = 87      # best name score must reach this
MARGIN = 2         # and beat the runner-up by this much
TEAM_MIN = 80      # partial-ratio for a club-name agreement
FULL_NAME_PENALTY = 10  # legal full names ("Daniel Olmo Carvajal") contain other players' surnames

# StatsBomb country name -> Transfermarkt nationality.
COUNTRY_ALIASES = {
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Congo, (Kinshasa)": "DR Congo",
    "Congo (Brazzaville)": "Congo",
    "Côte d'Ivoire": "Cote d'Ivoire",
    "Gambia": "The Gambia",
    "Turkey": "Türkiye",
    "Iran, Islamic Republic of": "Iran",
    "Korea (South)": "Korea, South",
    "Macedonia, Republic of": "North Macedonia",
    "Tanzania, United Republic of": "Tanzania",
    "United States of America": "United States",
    "Venezuela (Bolivarian Republic)": "Venezuela",
}

_CLUB_NOISE = re.compile(r"\b(fc|cf|sc|ac|afc|ssc|as|sv|vfb|vfl|tsg|club|de|futbol|football|calcio|s\.?p\.?a\.?)\b")


def norm(s: str | None) -> str:
    if not isinstance(s, str) or not s:
        return ""
    s = unicodedata.normalize("NFKD", s.replace("\xa0", " "))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("ø", "o").replace("ß", "ss").replace("ł", "l").replace("đ", "d").replace("ı", "i")
    return " ".join(re.sub(r"[^a-z ]+", " ", s).split())


def norm_club(s: str | None) -> str:
    return " ".join(_CLUB_NOISE.sub(" ", norm(s)).split())


def country(sb_country: str | None) -> str | None:
    if sb_country is None:
        return None
    c = sb_country.replace("\xa0", " ")
    return COUNTRY_ALIASES.get(c, c)


def name_score(sb_names: list[str], tm_name: str) -> float:
    """Best match between any StatsBomb name form and the TM name (roughly 0-105).

    token_set_ratio lets "Lamine Yamal Nasraoui Ebana" match "Lamine Yamal",
    but it also scores 100 when the only overlap is one token ("Alisson" vs
    "Alisson Santos"), so single-token overlaps fall back to token_sort_ratio.
    Exact matches get a bonus, and a small token_sort term breaks near-ties.
    sb_names[0] is the name football knows (nickname when there is one); later
    forms are legal full names and score FULL_NAME_PENALTY lower, so "Daniel Olmo
    Carvajal" (nickname "Daniel Olmo") matches Dani Olmo, not Daniel Carvajal.
    """
    tm = norm(tm_name)
    tm_tokens = tm.split()
    best = 0.0
    for rank, n in enumerate(sb_names):
        n = norm(n)
        if not n:
            continue
        n_tokens = n.split()
        s = fuzz.token_set_ratio(n, tm)
        shared = set(n_tokens) & set(tm_tokens)
        if len(shared) <= 1 and (len(n_tokens) > 1 or len(tm_tokens) > 1):
            s = fuzz.token_sort_ratio(n, tm)
        # "Dayotchanculle Upamecano" vs "Dayot Upamecano": same surname, first name is a prefix.
        if (len(n_tokens) > 1 and len(tm_tokens) > 1 and n_tokens[-1] == tm_tokens[-1]
                and (n_tokens[0].startswith(tm_tokens[0]) or tm_tokens[0].startswith(n_tokens[0]))):
            s = max(s, 92)
        s = max(s, fuzz.ratio(n, tm))
        s += 4 * (n == tm) + 1.5 * fuzz.token_sort_ratio(n, tm) / 100
        best = max(best, s - (FULL_NAME_PENALTY if rank > 0 else 0))
    return best


def link(sb: pd.DataFrame, tm: pd.DataFrame, tm_clubs: dict[int, set[str]]) -> pd.DataFrame:
    """sb: one row per sb_player_id with player_name, player_nickname, country, teams (list).
    tm: player_id, name, nationality, international_caps, highest_market_value_eur.
    tm_clubs: player_id -> normalised club names.

    Ties on name (two "Luis Díaz" from Colombia) are broken by club agreement,
    then by international caps, then by peak market value.
    """
    by_country: dict[str, list[int]] = defaultdict(list)
    for r in tm.itertuples():
        by_country[r.nationality].append(r.Index)
    tm_norm = tm["name"].map(norm)

    out = []
    for r in sb.itertuples():
        sb_names = [x for x in (r.player_nickname, r.player_name) if isinstance(x, str) and x]
        teams = {norm_club(t) for t in r.teams}
        pool = by_country.get(country(r.country), [])
        method = "name+country"
        if not pool:
            # Nationality missing or unmatched: look across everyone, require a club agreement.
            query = norm(sb_names[0])
            pool = [i for _, _, i in process.extract(query, tm_norm, scorer=fuzz.token_set_ratio,
                                                     limit=25, score_cutoff=NAME_MIN)]
            method = "name+club"

        scored = []
        for i in pool:
            s = name_score(sb_names, tm.at[i, "name"])
            if s < NAME_MIN - 10:
                continue
            clubs = tm_clubs.get(int(tm.at[i, "player_id"]), set())
            team_ok = any(fuzz.partial_ratio(t, c) >= TEAM_MIN for t in teams for c in clubs if t and c)
            capped = (tm.at[i, "international_caps"] or 0) > 0
            total = s + (5 if team_ok else 0) + (3 if capped else 0)
            peak = tm.at[i, "highest_market_value_eur"] or 0
            scored.append((total, peak, s, team_ok, i))
        scored.sort(reverse=True)

        row = {"sb_player_id": r.sb_player_id, "tm_player_id": None, "name_score": None,
               "team_match": None, "method": "unmatched", "runner_up_score": None}
        if scored:
            total, _, s, team_ok, i = scored[0]
            runner = scored[1][0] if len(scored) > 1 else 0.0
            ok = s >= NAME_MIN and total - runner >= MARGIN
            suffix = "+club" if team_ok and method == "name+country" else ""
            # Exact namesakes (two capped "Ladislav Krejčí"): the far more valuable one
            # is the one who plays at these tournaments. Tagged so evaluation can audit it.
            if s >= NAME_MIN and not ok and total - runner < MARGIN and len(scored) > 1:
                peak, runner_peak = scored[0][1], scored[1][1]
                if peak >= 3 * max(runner_peak, 1):
                    ok, suffix = True, suffix + "+value_tiebreak"
            if method == "name+club":
                ok = ok and team_ok
            row.update(name_score=s, team_match=team_ok, runner_up_score=runner)
            if ok:
                row.update(tm_player_id=int(tm.at[i, "player_id"]), method=method + suffix)
        out.append(row)
    return _one_to_one(pd.DataFrame(out))


def _one_to_one(links: pd.DataFrame) -> pd.DataFrame:
    """A Transfermarkt player can be one StatsBomb player only: keep the strongest name match."""
    linked = links[links["tm_player_id"].notna()]
    best = linked.sort_values("name_score", ascending=False).drop_duplicates("tm_player_id")
    losers = linked.index.difference(best.index)
    links.loc[losers, ["tm_player_id", "method"]] = [None, "conflict"]
    return links


def build_links(con: duckdb.DuckDBPyConnection, sample_size: int = 150) -> pd.DataFrame:
    sb = con.execute("""
        SELECT sb_player_id, last(player_name) AS player_name, last(player_nickname) AS player_nickname,
               last(country) AS country, list(DISTINCT team_name) AS teams
        FROM sb_players GROUP BY sb_player_id
    """).df()
    tm = con.execute("""
        SELECT player_id, name, nationality, coalesce(international_caps, 0) AS international_caps,
               coalesce(highest_market_value_eur, 0) AS highest_market_value_eur FROM players
        WHERE last_season >= 2020 AND name IS NOT NULL
    """).df()
    clubs: dict[int, set[str]] = defaultdict(set)
    for pid, club in con.execute("""
        SELECT DISTINCT player_id, club_name FROM value_history WHERE date >= DATE '2020-07-01'
        UNION SELECT player_id, club_name FROM players
    """).fetchall():
        if club:
            clubs[pid].add(norm_club(club))

    links = link(sb, tm, clubs)
    links["tm_player_id"] = links["tm_player_id"].astype("Int64")
    con.register("links_df", links)
    con.execute("CREATE OR REPLACE TABLE player_links AS SELECT * FROM links_df")
    con.unregister("links_df")

    matched = links["tm_player_id"].notna().mean()
    print(f"player_links: {len(links)} StatsBomb players, {matched:.1%} linked")
    _write_label_sample(con, sample_size)
    return links


def _write_label_sample(con: duckdb.DuckDBPyConnection, n: int) -> None:
    path = ROOT / "data" / "labels" / "link_sample.csv"
    if path.exists():
        return  # never overwrite hand labels
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT l.sb_player_id, s.player_name AS sb_name, s.player_nickname AS sb_nickname,
                   s.country AS sb_country, s.team_name AS sb_team,
                   l.tm_player_id, p.name AS tm_name, p.nationality AS tm_nationality,
                   p.date_of_birth AS tm_dob, p.club_name AS tm_club, l.method, l.name_score,
                   NULL AS is_correct, NULL AS correct_tm_player_id
            FROM player_links l
            JOIN (SELECT * FROM sb_players QUALIFY row_number() OVER (PARTITION BY sb_player_id ORDER BY minutes DESC) = 1) s
              USING (sb_player_id)
            LEFT JOIN players p ON p.player_id = l.tm_player_id
            USING SAMPLE {n} ROWS (reservoir, 42)
        ) TO '{path.as_posix()}' (HEADER)
    """)
    print(f"label sample: {path}")
