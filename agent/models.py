"""Model choice: Claude models through the Anthropic SDK, and local models through Ollama.

The agent graph calls `create(messages, model=...)`. ModelRouter sends `ollama:<name>`
ids to a local Ollama server and everything else to Claude. Messages stay in
Anthropic format throughout; OllamaChat converts them on the way in and out.
"""
import json
import os
import uuid
from copy import deepcopy

import requests

from agent.claude import ClaudeResponse, system_prompt
from agent.tools import TOOLS

DEFAULT_MODEL = "claude-opus-5-5"
CLAUDE_MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "Most capable; the default"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "Faster and cheaper"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "note": "Fastest, lowest cost"},
]
OLLAMA_PREFIX = "ollama:"


def ollama_url() -> str:
    return os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")


def list_models() -> list[dict]:
    """Every model the dropdown can offer, with whether this server can run it now."""
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    models = [m | {"provider": "anthropic", "available": has_key,
                   "reason": None if has_key else "No Anthropic API key on this server"} for m in CLAUDE_MODELS]
    try:
        tags = requests.get(f"{ollama_url()}/api/tags", timeout=1.5).json().get("models", [])
    except (requests.RequestException, ValueError):
        tags = None
    if tags is None:
        models.append({"id": f"{OLLAMA_PREFIX}*", "label": "Local models (Ollama)", "provider": "ollama",
                       "available": False, "note": "Runs on your own machine",
                       "reason": f"Ollama isn't running at {ollama_url()}"})
    for t in tags or []:
        models.append({"id": f"{OLLAMA_PREFIX}{t['name']}", "label": t["name"], "provider": "ollama",
                       "available": True, "note": "Local model via Ollama; needs tool-calling support",
                       "reason": None})
    return models


def is_known(model: str | None) -> bool:
    return model is None or model in {m["id"] for m in CLAUDE_MODELS} or (
        model.startswith(OLLAMA_PREFIX) and len(model) > len(OLLAMA_PREFIX) and "*" not in model)


# --- Ollama ---------------------------------------------------------------------------------

def _inline_refs(schema: dict) -> dict:
    """Small local models handle flat schemas better than $ref/$defs."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


OLLAMA_TOOLS = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": _inline_refs(t["input_schema"])}} for t in TOOLS]


def to_ollama(messages: list[dict], system: str) -> list[dict]:
    """Anthropic-format history -> Ollama chat messages. Thinking blocks are dropped;
    documents become text; PDFs (no text layer here) are mentioned by name only."""
    out = [{"role": "system", "content": system}]
    tool_names: dict[str, str] = {}
    for m in messages:
        if isinstance(m["content"], str):
            out.append({"role": m["role"], "content": m["content"]})
            continue
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in m["content"] if b.get("type") == "text")
            calls = []
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    tool_names[b["id"]] = b["name"]
                    calls.append({"function": {"name": b["name"], "arguments": b["input"]}})
            out.append({"role": "assistant", "content": text, **({"tool_calls": calls} if calls else {})})
            continue
        texts, images = [], []
        for b in m["content"]:
            t = b.get("type")
            if t == "tool_result":
                out.append({"role": "tool", "tool_name": tool_names.get(b["tool_use_id"], ""),
                            "content": b["content"] if isinstance(b["content"], str) else json.dumps(b["content"])})
            elif t == "text":
                texts.append(b["text"])
            elif t == "image":
                images.append(b["source"]["data"])
            elif t == "document":
                src = b["source"]
                if src.get("type") == "text":
                    texts.append(f"[Attached document: {b.get('title', 'file')}]\n{src['data']}")
                else:
                    texts.append(f"[Attached PDF: {b.get('title', 'file')} (not readable by local models)]")
        if texts or images:
            out.append({"role": "user", "content": "\n\n".join(texts), **({"images": images} if images else {})})
    return out


class OllamaChat:
    def __init__(self, base_url: str | None = None, session: requests.Session | None = None):
        self.base_url = (base_url or ollama_url()).rstrip("/")
        self.http = session or requests.Session()
        self._system = None

    def create(self, messages: list[dict], model: str) -> ClaudeResponse:
        name = model.removeprefix(OLLAMA_PREFIX)
        if self._system is None:
            self._system = system_prompt()
        r = self.http.post(f"{self.base_url}/api/chat", timeout=600, json={
            "model": name, "messages": to_ollama(messages, self._system), "tools": OLLAMA_TOOLS, "stream": False})
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {})
        content = []
        if msg.get("content"):
            content.append({"type": "text", "text": msg["content"]})
        for call in msg.get("tool_calls") or []:
            fn = call.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            content.append({"type": "tool_use", "id": f"toolu_local_{uuid.uuid4().hex[:12]}",
                            "name": fn.get("name", ""), "input": args})
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else (
            "max_tokens" if data.get("done_reason") == "length" else "end_turn")
        usage = {"input_tokens": data.get("prompt_eval_count", 0), "output_tokens": data.get("eval_count", 0),
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "provider": "ollama"}
        return ClaudeResponse(content=content, stop_reason=stop, model=model, usage=usage)


class ModelRouter:
    """One client for the graph: picks Claude or Ollama per request."""

    def __init__(self, claude=None, ollama=None):
        self._claude, self._ollama = claude, ollama

    def create(self, messages: list[dict], model: str | None = None) -> ClaudeResponse:
        model = model or DEFAULT_MODEL
        if model.startswith(OLLAMA_PREFIX):
            if self._ollama is None:
                self._ollama = OllamaChat()
            return self._ollama.create(messages, model)
        if self._claude is None:
            from agent.claude import AnthropicClaude
            self._claude = AnthropicClaude()
        return self._claude.create(messages, model=model)
