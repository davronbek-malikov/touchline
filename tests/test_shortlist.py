import copy
import json

import anthropic
import httpx2 as httpx
from langgraph.types import Command

from agent.claude import ClaudeResponse
from agent.graph import build_graph, user_turn
from agent.reports import ClaudeReportWriter, parse_report, report_text

USAGE = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


class FakeClaude:
    def __init__(self, *responses):
        self.responses, self.seen = list(responses), []

    def create(self, messages, model=None):
        self.seen.append(copy.deepcopy(messages))
        content, stop = self.responses.pop(0)
        return ClaudeResponse(content=content, stop_reason=stop, model="fake", usage=USAGE)


class FakeWriter:
    def __init__(self):
        self.calls = []

    def write(self, player_id, brief=None):
        self.calls.append((player_id, brief))
        return {"player_id": player_id, "name": f"P{player_id}", "blocks": [
            {"text": "Calm on the ball.", "citations": [{"source_id": "wiki:3:0", "title": "W", "url": None,
                                                         "cited_text": "calm", "source": "wikipedia"}]}],
                "sources": [], "usage": USAGE}


def propose(*ids):
    return [{"type": "tool_use", "id": "s1", "name": "propose_shortlist",
             "input": {"candidates": [{"player_id": i, "reason": "fits"} for i in ids]}}]


def test_shortlist_pauses_then_writes_only_approved_reports(warehouse):
    fake = FakeClaude((propose(3, 4, 6), "tool_use"), ([{"type": "text", "text": "Reports are ready."}], "end_turn"))
    writer = FakeWriter()
    g = build_graph(fake, report_writer=writer)
    cfg = {"configurable": {"thread_id": "s"}}

    first = g.invoke(user_turn("Reports on left-footed CBs"), cfg)
    pending = first["__interrupt__"][0].value
    assert [c["player_id"] for c in pending["candidates"]] == [3, 4, 6]
    assert pending["candidates"][0]["name"] == "Pablo Builder"
    assert writer.calls == []  # nothing written before approval
    assert g.get_state(cfg).next == ("review_shortlist",)

    done = g.invoke(Command(resume={"approved": [6, 3], "comment": "skip the stopper"}), cfg)
    assert [pid for pid, _ in writer.calls] == [3, 6]  # proposal order, approved only
    assert writer.calls[0][1] == "Reports on left-footed CBs"  # brief passed through
    assert done["final_text"] == "Reports are ready."
    assert [r["player_id"] for r in done["reports"]] == [3, 6]

    result = json.loads(fake.seen[1][-1]["content"][0]["content"])
    assert result["approved"] == ["Pablo Builder", "Pablo Builder Senior"]
    assert result["not_approved"] == ["Rugged Stopper"] and result["scout_comment"] == "skip the stopper"


def test_shortlist_rejecting_everyone_writes_nothing(warehouse):
    fake = FakeClaude((propose(3), "tool_use"), ([{"type": "text", "text": "ok"}], "end_turn"))
    writer = FakeWriter()
    g = build_graph(fake, report_writer=writer)
    cfg = {"configurable": {"thread_id": "r"}}
    g.invoke(user_turn("report on Pablo"), cfg)
    out = g.invoke(Command(resume={"approved": []}), cfg)
    assert writer.calls == [] and out["reports"] == []


def test_shortlist_with_unknown_ids_errors_without_pausing(warehouse):
    fake = FakeClaude((propose(3, 999), "tool_use"), ([{"type": "text", "text": "sorry"}], "end_turn"))
    out = build_graph(fake, report_writer=FakeWriter()).invoke(user_turn("q"), {"configurable": {"thread_id": "u"}})
    assert "__interrupt__" not in out
    res = fake.seen[1][-1]["content"][0]
    assert res["is_error"] is True and "999" in res["content"]


# --- report writer ----------------------------------------------------------------------

REPORT_RESPONSE = {
    "id": "msg_r", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
    "content": [
        {"type": "text", "text": "**Verdict** Pursue. "},
        {"type": "text", "text": "He stays composed under pressure",
         "citations": [{"type": "char_location", "cited_text": "stays composed under pressure.", "document_index": 0,
                        "document_title": "Wikipedia: player 3 (Style of play)", "start_char_index": 70,
                        "end_char_index": 100}]},
        {"type": "text", "text": ", with 9.0 progressive passes per 90."},
    ],
    "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 900, "output_tokens": 120, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
}


def test_report_writer_sends_cited_documents_and_maps_citations(passage_index):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=REPORT_RESPONSE)

    http = anthropic.DefaultHttpxClient(transport=httpx.MockTransport(handler))
    writer = ClaudeReportWriter(client=anthropic.Anthropic(api_key="test", http_client=http, max_retries=0))
    report = writer.write(3, brief="ball-playing CB")

    body = captured[0]
    assert "tools" not in body and "output_config" in body and body["fallbacks"] == "default"
    content = body["messages"][0]["content"]
    docs = [b for b in content if b["type"] == "document"]
    assert docs and all(d["citations"] == {"enabled": True} for d in docs)
    assert content[-1]["type"] == "text" and "Profile data" in content[-1]["text"]
    assert "ball-playing CB" in content[-1]["text"]

    cited = [b for b in report["blocks"] if b["citations"]]
    assert cited[0]["citations"][0]["source_id"] == report["sources"][0]["source_id"]
    rendered = report_text(report)
    assert "[1]" in rendered and "Sources:" in rendered


def test_parse_report_ignores_non_text_blocks():
    blocks = parse_report([{"type": "thinking", "thinking": ""}, {"type": "text", "text": "x"}], [])
    assert blocks == [{"text": "x", "citations": []}]
