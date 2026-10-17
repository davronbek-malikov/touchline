"""Anthropic client wrapper: one traced call per agent step, returning plain dicts.

Responses are serialised with model_dump so LangGraph checkpoints stay JSON-able.
Content blocks (thinking, fallback, text, tool_use) are kept exactly as returned
and appended to history unchanged: Opus 5.5 thinking blocks are only valid in
the conversation that produced them, so history is append-only.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import anthropic
from langsmith import traceable

from agent.tools import TOOLS
from agent.tools.db import data_as_of

MODEL = os.environ.get("TOUCHLINE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("TOUCHLINE_EFFORT", "medium")
MAX_TOKENS = 16000
MAX_TOOL_ROUNDS = 8
PROMPT_VERSION = "v1"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

PROMPTS = Path(__file__).parent / "prompts"


def system_prompt() -> str:
    # Values filled here are fixed per deployment, so the cached prefix stays byte-stable.
    text = (PROMPTS / "system.md").read_text(encoding="utf-8")
    return text.replace("{data_as_of}", data_as_of()).replace("{max_tool_rounds}", str(MAX_TOOL_ROUNDS))


@dataclass
class ClaudeResponse:
    content: list[dict]
    stop_reason: str | None
    model: str
    usage: dict
    stop_details: dict | None = None


class ClaudeClient(Protocol):
    def create(self, messages: list[dict]) -> ClaudeResponse: ...


class AnthropicClaude:
    """The real client. Tests substitute a scripted fake with the same create()."""

    def __init__(self, model: str = MODEL, effort: str = EFFORT, client: anthropic.Anthropic | None = None):
        self.model = model
        self.effort = effort
        self.client = client or anthropic.Anthropic()
        self._system = [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]

    def create(self, messages: list[dict]) -> ClaudeResponse:
        return _traced_create(self, messages)

    def _request(self, messages: list[dict]) -> ClaudeResponse:
        r = self.client.beta.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",  # a declined request is re-run server-side on a fallback model
            output_config={"effort": self.effort},
            system=self._system,
            tools=TOOLS,
            cache_control={"type": "ephemeral"},  # also cache the growing conversation each round
            messages=messages,
        )
        return ClaudeResponse(
            content=[b.model_dump(mode="json", exclude_none=True) for b in r.content],
            stop_reason=r.stop_reason,
            model=r.model,
            usage={
                "input_tokens": r.usage.input_tokens,
                "output_tokens": r.usage.output_tokens,
                "cache_read_input_tokens": r.usage.cache_read_input_tokens or 0,
                "cache_creation_input_tokens": r.usage.cache_creation_input_tokens or 0,
            },
            stop_details=r.stop_details.model_dump(mode="json") if getattr(r, "stop_details", None) else None,
        )


def _usage_metadata(outputs: ClaudeResponse) -> dict:
    u = outputs.usage
    inp = u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"]
    return {
        "content": outputs.content,
        "stop_reason": outputs.stop_reason,
        "usage_metadata": {
            "input_tokens": inp,
            "output_tokens": u["output_tokens"],
            "total_tokens": inp + u["output_tokens"],
            "input_token_details": {"cache_read": u["cache_read_input_tokens"],
                                    "cache_creation": u["cache_creation_input_tokens"]},
        },
    }


@traceable(run_type="llm", name="claude", process_outputs=_usage_metadata,
           process_inputs=lambda inputs: {"messages": inputs["messages"]},
           metadata={"ls_provider": "anthropic", "ls_model_name": MODEL, "prompt_version": PROMPT_VERSION})
def _traced_create(client: AnthropicClaude, messages: list[dict]) -> ClaudeResponse:
    return client._request(messages)
