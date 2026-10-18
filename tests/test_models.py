import json

import pytest

from agent.models import OLLAMA_TOOLS, ModelRouter, OllamaChat, is_known, to_ollama
from agent.cost import usage_cost


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload, self.sent = payload, []

    def post(self, url, json=None, timeout=None):
        self.sent.append((url, json))
        return FakeResponse(self.payload)


HISTORY = [
    {"role": "user", "content": [{"type": "text", "text": "Attached files: a.png (image)"},
                                 {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
                                 {"type": "document", "title": "notes.txt",
                                  "source": {"type": "text", "media_type": "text/plain", "data": "fast winger"}},
                                 {"type": "text", "text": "who is this?"}]},
    {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "s"},
                                      {"type": "tool_use", "id": "t1", "name": "find_player", "input": {"name": "Yamal"}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{\"candidates\": []}"}]},
]


def test_to_ollama_converts_blocks_and_tool_turns():
    out = to_ollama(HISTORY, "SYSTEM")
    assert out[0] == {"role": "system", "content": "SYSTEM"}
    assert out[1]["images"] == ["QUJD"] and "fast winger" in out[1]["content"] and "who is this?" in out[1]["content"]
    assert out[2] == {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "find_player",
                                                                                    "arguments": {"name": "Yamal"}}}]}
    assert out[3] == {"role": "tool", "tool_name": "find_player", "content": "{\"candidates\": []}"}


def test_ollama_tools_have_no_refs():
    assert "$ref" not in json.dumps(OLLAMA_TOOLS) and len(OLLAMA_TOOLS) == 7


def test_ollama_chat_parses_tool_calls(warehouse):
    sess = FakeSession({"message": {"role": "assistant", "content": "",
                                    "tool_calls": [{"function": {"name": "search_players",
                                                                 "arguments": {"position_groups": ["CB"]}}}]},
                        "prompt_eval_count": 900, "eval_count": 40})
    r = OllamaChat("http://ollama:11434", session=sess).create([{"role": "user", "content": "CBs"}], "ollama:qwen3:8b")
    url, body = sess.sent[0]
    assert url == "http://ollama:11434/api/chat" and body["model"] == "qwen3:8b" and body["stream"] is False
    assert r.stop_reason == "tool_use" and r.content[0]["name"] == "search_players"
    assert r.content[0]["input"] == {"position_groups": ["CB"]} and r.content[0]["id"].startswith("toolu_local_")
    assert usage_cost([r.usage]) == 0.0  # local tokens are free


def test_ollama_chat_plain_answer(warehouse):
    sess = FakeSession({"message": {"role": "assistant", "content": "Hello"}, "done_reason": "stop"})
    r = OllamaChat("http://x", session=sess).create([{"role": "user", "content": "hi"}], "ollama:llama3.1")
    assert r.stop_reason == "end_turn" and r.content == [{"type": "text", "text": "Hello"}]


def test_router_sends_by_prefix():
    calls = []

    class Stub:
        def __init__(self, tag):
            self.tag = tag

        def create(self, messages, model=None):
            calls.append((self.tag, model))

    router = ModelRouter(claude=Stub("claude"), ollama=Stub("ollama"))
    router.create([], "ollama:qwen3")
    router.create([], "claude-haiku-5-5")
    router.create([], None)
    assert calls == [("ollama", "ollama:qwen3"), ("claude", "claude-haiku-5-5"), ("claude", "claude-opus-5-5")]


@pytest.mark.parametrize("model,ok", [("claude-opus-5-5", True), ("ollama:qwen3:8b", True), (None, True),
                                      ("gpt-9", False), ("ollama:", False), ("ollama:*", False)])
def test_is_known(model, ok):
    assert is_known(model) is ok


def test_cost_per_model():
    u = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    assert usage_cost([u | {"model": "claude-haiku-5-5"}]) == 0.1
    assert usage_cost([u | {"model": "claude-sonnet-5-5"}]) == 2.0
    assert usage_cost([u]) == 4.0
