"""LLM-as-judge for scouting report quality (1-5 rubric).

Not trusted until calibrated: rate ~30 reports by hand and compare with the
judge's scores before quoting it in the results table. Runs only with --judge.
"""
import json
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from agent.claude import MODEL

RUBRIC = """You grade scouting reports written for a football recruitment team. You see the report, the
profile data and source passages it was written from, and the scout's brief. Score each criterion 1-5
(5 = excellent, 3 = acceptable, 1 = failing) and keep each justification to one sentence.

- role_fit: does the report judge the player against the brief and the role, not just describe him?
- evidence_backed_strengths: are strengths specific and supported by the data or a cited passage?
- weaknesses_stated: are real weaknesses and risks named (small samples, missing data, injuries if sourced)?
- clear_recommendation: is there a clear pursue / monitor / pass call with a concrete next step?
- no_unsupported_claims: is everything traceable to the data or passages? Penalise style claims from
  general knowledge, invented numbers, or players not in the evidence."""


class Criterion(BaseModel):
    score: Literal[1, 2, 3, 4, 5]
    why: str = Field(description="One sentence.")


class ReportGrade(BaseModel):
    role_fit: Criterion
    evidence_backed_strengths: Criterion
    weaknesses_stated: Criterion
    clear_recommendation: Criterion
    no_unsupported_claims: Criterion

    def overall(self) -> float:
        return round(sum(c.score for c in self.__dict__.values()) / 5, 2)


def grade_report(report_text: str, profile: dict, passages: list[dict], brief: str,
                 client: anthropic.Anthropic | None = None) -> ReportGrade:
    client = client or anthropic.Anthropic()
    evidence = json.dumps({"profile": profile, "passages": [{"source_id": p["source_id"], "text": p["text"]}
                                                           for p in passages]}, ensure_ascii=False)
    r = client.messages.parse(
        model=MODEL, max_tokens=4000, output_config={"effort": "low"},
        system=RUBRIC,
        messages=[{"role": "user", "content": f"Brief: {brief}\n\nEvidence:\n{evidence}\n\nReport:\n{report_text}"}],
        output_format=ReportGrade,
    )
    if r.stop_reason == "refusal" or r.parsed_output is None:
        raise ValueError(f"judge returned no grade (stop_reason={r.stop_reason})")
    return r.parsed_output
