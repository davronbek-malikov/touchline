"""Helpers for Anthropic-format history where a user turn may carry attachments.

A scout's message is either a plain string or a list of blocks: an "Attached files"
text block, then image/document blocks, then the question as the last text block.
Tool results are also role "user"; they are not turns.
"""
ATTACH_PREFIX = "Attached files: "


def is_user_turn(m: dict) -> bool:
    if m["role"] != "user":
        return False
    if isinstance(m["content"], str):
        return True
    return not any(b.get("type") == "tool_result" for b in m["content"])


def user_text(m: dict) -> str:
    """The question itself, without the attachment list."""
    if isinstance(m["content"], str):
        return m["content"]
    texts = [b["text"] for b in m["content"] if b.get("type") == "text" and not b["text"].startswith(ATTACH_PREFIX)]
    return texts[-1] if texts else ""


def attachment_names(m: dict) -> list[str]:
    if isinstance(m["content"], str):
        return []
    for b in m["content"]:
        if b.get("type") == "text" and b["text"].startswith(ATTACH_PREFIX):
            return [n.strip() for n in b["text"][len(ATTACH_PREFIX):].split(";") if n.strip()]
    return []


def user_message(text: str, attachment_blocks: list[dict] | None = None, names: list[str] | None = None) -> dict:
    if not attachment_blocks:
        return {"role": "user", "content": text}
    head = [{"type": "text", "text": ATTACH_PREFIX + "; ".join(names or [])}] if names else []
    return {"role": "user", "content": head + attachment_blocks + [{"type": "text", "text": text}]}


def turn_starts(messages: list[dict]) -> list[int]:
    return [i for i, m in enumerate(messages) if is_user_turn(m)]
