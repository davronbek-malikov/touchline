"""The real AnthropicClaude client against a mocked HTTP transport: request shape and parsing."""
import json

import anthropic
import httpx2 as httpx

from agent.claude import FALLBACK_BETA, AnthropicClaude

RESPONSE = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
    "content": [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "Checking."},
        {"type": "tool_use", "id": "toolu_1", "name": "find_player", "input": {"name": "Rodri"}},
    ],
    "stop_reason": "tool_use", "stop_sequence": None,
    "usage": {"input_tokens": 12, "output_tokens": 30, "cache_read_input_tokens": 4000,
              "cache_creation_input_tokens": 0},
}


def _client(captured: list):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=RESPONSE)

    http = anthropic.DefaultHttpxClient(transport=httpx.MockTransport(handler))
    return AnthropicClaude(client=anthropic.Anthropic(api_key="test", http_client=http, max_retries=0))


def test_request_shape(warehouse):
    captured = []
    _client(captured).create([{"role": "user", "content": "left-footed CB under 23"}])
    req = captured[0]
    body = json.loads(req.content)

    assert FALLBACK_BETA in req.headers["anthropic-beta"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["output_config"] == {"effort": "medium"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "2026-07-06" in body["system"][0]["text"] and "{data_as_of}" not in body["system"][0]["text"]
    # Rejected on Opus 5.5: sampling params, explicit thinking config, forced tool choice.
    for banned in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
        assert banned not in body
    assert {t["name"] for t in body["tools"]} == {
        "find_player", "search_players", "get_player_profile", "similar_players", "compare_players"}
    assert all(t["strict"] is True for t in body["tools"])


def test_response_is_plain_dicts(warehouse):
    r = _client([]).create([{"role": "user", "content": "x"}])
    assert r.stop_reason == "tool_use"
    assert r.content[0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    assert r.content[2] == {"type": "tool_use", "id": "toolu_1", "name": "find_player",
                            "input": {"name": "Rodri"}}
    assert r.usage["cache_read_input_tokens"] == 4000
    json.dumps(r.content)  # checkpointable


def test_system_prompt_is_byte_stable(warehouse):
    a, b = [], []
    _client(a).create([{"role": "user", "content": "x"}])
    _client(b).create([{"role": "user", "content": "y"}])
    ja, jb = json.loads(a[0].content), json.loads(b[0].content)
    assert ja["system"] == jb["system"] and ja["tools"] == jb["tools"]
