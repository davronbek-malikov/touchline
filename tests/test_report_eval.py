from agent.graph import build_graph
from eval.evaluators import citation_coverage, score_all
from eval.target import run_query
from tests.test_shortlist import FakeClaude, FakeWriter, propose

CITE = [{"source_id": "wiki:3:0", "title": "W", "url": None, "cited_text": "x", "source": "wikipedia"}]


def test_citation_coverage_counts_qualitative_sentences_only():
    out = {"reports": [{"blocks": [
        {"text": "**Strengths**", "citations": []},                                        # heading: skipped
        {"text": "He breaks lines with forward passes into midfield.", "citations": CITE},  # cited
        {"text": "He is comfortable receiving on the half-turn under pressure.", "citations": []},  # uncited
        {"text": "He played 450 minutes at the Euro.", "citations": []},                   # has a number: skipped
    ]}]}
    r = citation_coverage(out)
    assert r["score"] == 0.5 and r["comment"] == "1/2 qualitative sentences cited"
    assert citation_coverage({"reports": []}) is None


def test_eval_target_auto_approves_and_scores_report(warehouse):
    fake = FakeClaude((propose(3), "tool_use"), ([{"type": "text", "text": "Report delivered."}], "end_turn"))
    writer = FakeWriter()
    g = build_graph(fake, report_writer=writer)
    out = run_query(g, "Write a scouting report on Pablo Builder.")
    assert out["shortlists"] == [[3]] and [r["player_id"] for r in out["reports"]] == [3]
    assert out["reports"][0]["text"] == "Calm on the ball."

    item = {"type": "report", "query": "Write a scouting report on Pablo Builder.",
            "reference": {"player_id": 3, "player": "Pablo Builder"}}
    s = score_all(item, out)["scores"]
    assert s["report_written"] == 1.0
    assert s["hallucinated_players"] == 0


def test_report_numbers_are_checked_against_report_evidence(warehouse):
    base = {"final_text": "Done.", "usage": [], "tool_calls": [
        {"name": "report_evidence", "input": {"player_id": 3},
         "output": {"profile": {"player": {"player_id": 3, "name": "Pablo Builder", "market_value_eur": 9_000_000}},
                    "passages": []}, "is_error": False}]}
    item = {"type": "report", "query": "report", "reference": {"player_id": 3}}
    good = base | {"reports": [{"player_id": 3, "blocks": [], "text": "Valued at €9M."}]}
    bad = base | {"reports": [{"player_id": 3, "blocks": [], "text": "Valued at €40M."}]}
    assert score_all(item, good)["scores"]["numeric_grounding"] == 1.0
    assert score_all(item, bad)["scores"]["numeric_grounding"] == 0.0
