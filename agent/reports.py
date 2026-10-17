"""Cited scouting reports, one Claude call per approved player.

Passages from search_notes go in as document blocks with citations enabled; the
player profile goes in as plain JSON for the numbers. Citations and structured
output can't share a request, so this call returns prose with citation spans.
"""
import json
from pathlib import Path
from typing import Protocol

import anthropic
from langsmith import traceable

from agent.claude import EFFORT, FALLBACK_BETA, MODEL
from agent.tools import run_tool

PROMPT = (Path(__file__).parent / "prompts" / "report.md").read_text(encoding="utf-8")
EVIDENCE_QUERIES = ["style of play, strengths and role", "weaknesses, risks and areas to improve"]
MAX_PASSAGES = 8


class ReportWriter(Protocol):
    def write(self, player_id: int, brief: str | None = None) -> dict: ...


def gather_evidence(player_id: int) -> tuple[dict, list[dict]]:
    """The player's profile and up to MAX_PASSAGES distinct passages about them."""
    profile_json, is_error = run_tool("get_player_profile", {"player_id": player_id})
    if is_error:
        raise ValueError(json.loads(profile_json)["error"])
    seen, passages = set(), []
    for q in EVIDENCE_QUERIES:
        out, err = run_tool("search_notes", {"query": q, "player_id": player_id, "limit": MAX_PASSAGES})
        for p in [] if err else json.loads(out)["passages"]:
            if p["source_id"] not in seen and len(passages) < MAX_PASSAGES:
                seen.add(p["source_id"])
                passages.append(p)
    return json.loads(profile_json), passages


def build_request(profile: dict, passages: list[dict], brief: str | None) -> list[dict]:
    docs = [{"type": "document", "title": p["title"],
             "source": {"type": "text", "media_type": "text/plain", "data": p["text"]},
             "context": f"source_id={p['source_id']}; licence={p.get('licence')}; url={p.get('url') or 'internal'}",
             "citations": {"enabled": True}} for p in passages]
    ask = (f"Scouting brief: {brief}\n\n" if brief else "") + \
        f"Profile data (JSON):\n{json.dumps(profile, ensure_ascii=False)}\n\n" \
        f"Write the scouting report on {profile['player']['name']}."
    return [{"role": "user", "content": docs + [{"type": "text", "text": ask}]}]


def parse_report(content: list[dict], passages: list[dict]) -> list[dict]:
    """Text blocks with their citations mapped back to passage sources."""
    blocks = []
    for b in content:
        if b.get("type") != "text":
            continue
        cites = []
        for c in b.get("citations") or []:
            p = passages[c["document_index"]] if c.get("document_index") is not None and \
                c["document_index"] < len(passages) else {}
            cites.append({"cited_text": c.get("cited_text"), "source_id": p.get("source_id"),
                          "title": p.get("title") or c.get("document_title"), "url": p.get("url"),
                          "source": p.get("source")})
        blocks.append({"text": b["text"], "citations": cites})
    return blocks


class ClaudeReportWriter:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL, effort: str = EFFORT):
        self.client = client or anthropic.Anthropic()
        self.model, self.effort = model, effort
        self._system = [{"type": "text", "text": PROMPT, "cache_control": {"type": "ephemeral"}}]

    @traceable(run_type="chain", name="write_report")
    def write(self, player_id: int, brief: str | None = None) -> dict:
        profile, passages = gather_evidence(player_id)
        r = self.client.beta.messages.create(
            model=self.model, max_tokens=16000, betas=[FALLBACK_BETA], fallbacks="default",
            output_config={"effort": self.effort}, system=self._system,
            messages=build_request(profile, passages, brief),
        )
        content = [b.model_dump(mode="json", exclude_none=True) for b in r.content]
        if r.stop_reason == "refusal":
            blocks = [{"text": "The report request was declined by the model's safety filters.", "citations": []}]
        else:
            blocks = parse_report(content, passages)
        return {
            "player_id": player_id, "name": profile["player"]["name"], "blocks": blocks,
            "sources": passages, "profile": profile, "stop_reason": r.stop_reason,
            "usage": {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
                      "cache_read_input_tokens": r.usage.cache_read_input_tokens or 0,
                      "cache_creation_input_tokens": r.usage.cache_creation_input_tokens or 0},
        }


def report_text(report: dict, with_refs: bool = True) -> str:
    """Render a report for the terminal: citations as [n] with a source list."""
    refs, out = {}, []
    for b in report["blocks"]:
        text = b["text"]
        if with_refs:
            for c in b["citations"]:
                key = c["source_id"] or c["title"]
                refs.setdefault(key, (len(refs) + 1, c))
            nums = sorted({refs[c["source_id"] or c["title"]][0] for c in b["citations"]})
            if nums:
                text += "".join(f"[{n}]" for n in nums)
        out.append(text)
    body = "".join(out).strip()
    if with_refs and refs:
        body += "\n\nSources:\n" + "\n".join(
            f"  [{n}] {c['title']}" + (f" <{c['url']}>" if c.get("url") else "") for n, c in refs.values())
    return body
