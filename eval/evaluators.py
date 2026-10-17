"""Deterministic evaluators for a Touchline run.

A run output is a dict:
    final_text   str
    tool_calls   [{name, input, output (parsed JSON or None), is_error}]
    usage        [{input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens}]
    latency_s    float

Every evaluator returns a score in [0, 1] (or a count / dollars, noted below), or
None when it doesn't apply to the item.
"""
import re
from functools import lru_cache

from rapidfuzz import fuzz, process

from agent.tools.db import rows
from data.link_players import norm

# Claude Opus 5.5 list prices, $ per million tokens (5-minute cache writes are 1.25x input).
PRICE = {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00}

NO_DATA = re.compile(
    r"\b(no data|don'?t have|do not have|doesn'?t (?:have|include|cover)|does not (?:have|include|cover)|"
    r"isn'?t (?:in|covered|available)|is not (?:in|covered|available)|not (?:in|covered by) (?:the|our|my) "
    r"(?:database|data)|couldn'?t find|could not find|no record|not available|no (?:player|match|information)|"
    r"outside (?:the|our) (?:data|coverage)|can'?t (?:answer|provide|predict|forecast)|cannot (?:answer|provide|"
    r"predict|forecast)|not covered|no (?:statsbomb|event) data)\b", re.I)


# --- helpers -----------------------------------------------------------------------

def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def returned_players(outputs: dict) -> dict[int, str]:
    """Every player (id -> name) that any tool returned in this run."""
    found = {}
    for call in outputs.get("tool_calls", []):
        for node in _walk(call.get("output")):
            if isinstance(node.get("player_id"), int) and isinstance(node.get("name"), str):
                found[node["player_id"]] = node["name"]
    return found


def presented_players(outputs: dict) -> list[int]:
    """Tool-returned players named in the final answer, in order of first mention."""
    text = norm(outputs.get("final_text", ""))
    positions = []
    for pid, name in returned_players(outputs).items():
        m = re.search(rf"\b{re.escape(norm(name))}\b", text)
        if m:
            positions.append((m.start(), pid))
    return [pid for _, pid in sorted(positions)]


_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(bn|billion|m|million|k)?(?![\w])", re.I)
_LIST_INDEX = re.compile(r"^\s*(?:\d+[.)]\s|\|\s*\d+\s*\|)", re.M)
_UNIT_PHRASES = re.compile(r"\b(?:per|/)\s?90\b|\bp90\b|\b90s\b", re.I)


def text_numbers(text: str) -> list[tuple[float, float]]:
    """(value, tolerance) for each number in prose, skipping list/table rank indices.
    "€8.5M" -> (8_500_000, 50_000): half a unit in the last displayed digit."""
    text = _UNIT_PHRASES.sub(" ", _LIST_INDEX.sub(" ", text))
    out = []
    for raw, unit in _NUM.findall(text):
        digits = raw.replace(",", "")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale = {"bn": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6, "k": 1e3}.get((unit or "").lower(), 1)
        out.append((float(digits) * scale, 0.5 * 10 ** -decimals * scale))
    return out


def tool_numbers(outputs: dict, query: str = "") -> set[float]:
    """All numbers the answer may legitimately use: tool values (and their usual display
    transforms), digits inside dates and seasons, and numbers the scout wrote."""
    nums: set[float] = set()

    def add(v: float):
        nums.update({v, v / 1e6, v / 1e3})
        if 0 < abs(v) <= 1:
            nums.add(v * 100)

    for call in outputs.get("tool_calls", []):
        for node in _walk(call.get("output")):
            for v in node.values():
                if isinstance(v, list):  # "that's 10 players" counts a returned list
                    add(float(len(v)))
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)):
                    add(float(v))
                elif isinstance(v, str):
                    for d in re.findall(r"\d+(?:\.\d+)?", v):
                        add(float(d))
    for v, _ in text_numbers(query):
        add(v)
    return nums


def _grounded(value: float, tol: float, pool: set[float]) -> bool:
    tol = max(tol, abs(value) * 0.005) + 1e-9  # at least half a percent for large rounded figures
    return any(abs(value - p) <= tol for p in pool)


# --- warehouse vocabularies for name checks ---------------------------------------------

@lru_cache(maxsize=1)
def _vocab():
    names = [r["name"] for r in rows("SELECT name FROM players WHERE name IS NOT NULL")]
    normed = sorted({norm(n) for n in names})
    first = {n.split()[0] for n in normed if len(n.split()) > 1}
    non_person = set()
    for col in ("club_name", "nationality", "country_of_birth"):
        non_person |= {norm(r["v"]) for r in rows(f"SELECT DISTINCT {col} AS v FROM players WHERE {col} IS NOT NULL")}
    non_person |= {norm(r["v"]) for r in rows("SELECT DISTINCT club_name AS v FROM value_history WHERE club_name IS NOT NULL")}
    non_person |= {norm(r["v"]) for r in rows("SELECT DISTINCT competition AS v FROM sb_player_per90")}
    return normed, set(normed), first, non_person


_ENGLISH = {"the", "a", "an", "top", "best", "strong", "key", "high", "low", "good", "great", "young", "older",
            "market", "value", "contract", "summary", "pick", "player", "players", "note", "notes", "why",
            "what", "data", "per", "real", "club", "league", "euro", "copa", "world", "cup", "bundesliga",
            "premier", "serie", "ligue", "laliga", "liga", "saudi", "pro", "major", "soccer", "statsbomb",
            "transfermarkt", "next", "steps", "recommendation", "option", "options", "alternative",
            "alternatives", "verdict", "role", "fit", "risk", "risks", "strengths", "weaknesses", "profile"}

_PHRASE = re.compile(r"\b([A-ZÀ-Ý][\w'’\-]+(?:\s+(?:(?:van|de|da|dos|das|di|del|der|den|el|al|le|la|von|ter|ben|bin)\s+)?"
                     r"[A-ZÀ-Ý][\w'’\-]+){1,3})")


def name_phrases(text: str) -> list[str]:
    """Capitalised 2-4 word phrases that start with a known footballer first name."""
    _, _, first, non_person = _vocab()
    out = []
    for raw in _PHRASE.findall(text):
        phrase = re.sub(r"['’]s$", "", raw)
        n = norm(phrase)
        tokens = n.split()
        if len(tokens) < 2 or tokens[0] in _ENGLISH or tokens[0] not in first:
            continue
        if n in non_person or any(fuzz.partial_ratio(n, c) >= 95 for c in non_person if len(c) > 5 and n in c):
            continue
        out.append(phrase)
    return out


def _is_known_player(phrase: str) -> bool:
    normed, normed_set, _, _ = _vocab()
    n = norm(phrase)
    if n in normed_set:
        return True
    hit = process.extractOne(n, normed, scorer=fuzz.token_set_ratio, score_cutoff=92)
    return hit is not None and len(set(n.split()) & set(hit[0].split())) >= 1


# --- evaluators --------------------------------------------------------------------------

def _norm_field(key, v):
    if v is None:
        return None
    if key == "metric_filters":
        return frozenset((f["metric"], int(f["percentile_min"])) for f in v)
    if isinstance(v, list):
        return frozenset(str(x).lower() for x in v)
    if isinstance(v, str):
        return v.lower()
    return v


def filter_accuracy(outputs: dict, reference: dict) -> dict | None:
    """Field-by-field match of the best search_players call against the gold filter."""
    gold = reference.get("gold_filter")
    if gold is None:
        return None
    calls = [c["input"] for c in outputs.get("tool_calls", []) if c["name"] == "search_players" and not c["is_error"]]
    if not calls:
        return {"score": 0.0, "comment": "no successful search_players call"}

    def score(pred):
        keys = (set(gold) | set(pred)) - {"limit"}
        g_sort, p_sort = gold.get("sort_by", "market_value_desc"), pred.get("sort_by", "market_value_desc")
        keys.discard("sort_by")
        hits = sum(_norm_field(k, gold.get(k)) == _norm_field(k, pred.get(k)) for k in keys)
        total = len(keys)
        if g_sort != "market_value_desc" or p_sort != "market_value_desc":
            total += 1
            hits += g_sort == p_sort
        wrong = sorted(k for k in keys if _norm_field(k, gold.get(k)) != _norm_field(k, pred.get(k)))
        return (hits / total if total else 1.0), wrong

    best, wrong = max((score(p) for p in calls), key=lambda t: t[0])
    return {"score": round(best, 3), "comment": f"mismatched: {', '.join(wrong)}" if wrong else "exact"}


def precision_recall_at_10(outputs: dict, reference: dict) -> dict | None:
    gold = reference.get("gold_player_ids")
    if gold is None:
        return None
    shown = presented_players(outputs)[:10]
    gold10 = set(gold[:10])
    hit = len(set(shown) & gold10)
    return {"precision@10": round(hit / len(shown), 3) if shown else 0.0,
            "recall@10": round(hit / len(gold10), 3) if gold10 else None}


def numeric_grounding(outputs: dict, query: str = "") -> dict | None:
    """Share of numbers in the answer that appear in this run's tool outputs (or the query)."""
    nums = text_numbers(outputs.get("final_text", ""))
    if not nums:
        return None
    pool = tool_numbers(outputs, query)
    bad = [v for v, t in nums if not _grounded(v, t, pool)]
    return {"score": round(1 - len(bad) / len(nums), 3),
            "comment": f"ungrounded: {bad[:8]}" if bad else f"{len(nums)} numbers grounded"}


def player_names(outputs: dict) -> dict:
    """hallucinated = person-like names not in the warehouse (target 0).
    ungrounded = warehouse players named in the answer that no tool returned this run."""
    phrases = name_phrases(outputs.get("final_text", ""))
    returned = {norm(n) for n in returned_players(outputs).values()}
    hallucinated, ungrounded = [], []
    for p in dict.fromkeys(phrases):
        n = norm(p)
        if any(n == r or set(n.split()) <= set(r.split()) for r in returned):
            continue
        (ungrounded if _is_known_player(p) else hallucinated).append(p)
    return {"hallucinated_players": len(hallucinated), "ungrounded_players": len(ungrounded),
            "comment": f"hallucinated={hallucinated} ungrounded={ungrounded}"}


def trap_handled(outputs: dict, reference: dict) -> dict | None:
    if not reference.get("expect_no_data"):
        return None
    says_no = bool(NO_DATA.search(outputs.get("final_text", "")))
    invented = player_names(outputs)["hallucinated_players"]
    return {"score": float(says_no and invented == 0),
            "comment": f"no-data phrase={'yes' if says_no else 'no'}, invented players={invented}"}


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]


def fact_correct(outputs: dict, reference: dict) -> dict | None:
    if "gold_value" not in reference:
        return None
    gold, text = reference["gold_value"], outputs.get("final_text", "")
    ntext = norm(text)
    if isinstance(gold, bool):
        ok = False
    elif isinstance(gold, (int, float)):
        ok = any(_grounded(v, t, {float(gold), float(gold) / 1e6}) for v, t in text_numbers(text))
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", gold):
        y, m, d = map(int, gold.split("-"))
        ok = gold in text or (str(y) in text and (_MONTHS[m - 1] in ntext or f"{m:02d}/{y}" in text
                                                    or f"{d}/{m}/{y}" in text))
    else:
        g = norm(gold)
        ok = g in ntext or fuzz.partial_ratio(g, ntext) >= 90
    return {"score": float(ok), "comment": f"gold={gold}"}


def cost_usd(outputs: dict) -> float:
    total = 0.0
    for u in outputs.get("usage", []):
        total += (u["input_tokens"] * PRICE["input"] + u["output_tokens"] * PRICE["output"]
                  + u["cache_read_input_tokens"] * PRICE["cache_read"]
                  + u["cache_creation_input_tokens"] * PRICE["cache_write"]) / 1e6
    return round(total, 5)


def score_all(item: dict, outputs: dict) -> dict:
    """Every applicable metric for one golden item -> {metric: value}, plus comments."""
    ref, scores, comments = item["reference"], {}, {}

    def put(name, result, key="score"):
        if result is None:
            return
        if result.get(key) is not None:
            scores[name] = result[key]
        if result.get("comment"):
            comments[name] = result["comment"]

    if item["type"] == "filter":
        put("filter_accuracy", filter_accuracy(outputs, ref))
    if item["type"] in ("filter", "similar"):
        pr = precision_recall_at_10(outputs, ref)
        scores["precision@10"] = pr["precision@10"]
        if pr["recall@10"] is not None:
            scores["recall@10"] = pr["recall@10"]
    if item["type"] == "fact":
        put("fact_correct", fact_correct(outputs, ref))
    if item["type"] == "trap":
        put("trap_handled", trap_handled(outputs, ref))
    put("numeric_grounding", numeric_grounding(outputs, item["query"]))
    names = player_names(outputs)
    scores["hallucinated_players"] = names["hallucinated_players"]
    scores["ungrounded_players"] = names["ungrounded_players"]
    comments["player_names"] = names["comment"]
    calls = outputs.get("tool_calls", [])
    scores["tool_error_rate"] = round(sum(c["is_error"] for c in calls) / len(calls), 3) if calls else 0.0
    scores["cost_usd"] = cost_usd(outputs)
    if outputs.get("latency_s") is not None:
        scores["latency_s"] = round(outputs["latency_s"], 2)
    return {"scores": scores, "comments": comments}

