"""Server-side confirmation for the in-app coach (session 28).

A write tool previews unless `confirm` is exactly true — but that is only a convention the model follows: a model that has been
steered by injected text can pass confirm=true on its first call. For the in-app coach the server therefore refuses to honour a
confirm unless this conversation already holds a *preview of the same call* from an EARLIER turn and the athlete has sent a message
since. A preview and its confirm inside one turn (the shape an injected instruction would produce) is downgraded to a preview.

MCP and REST callers are not covered by this: their confirmation is mediated by the client (the MCP client's own tool-approval
prompt) and limited by the token's scope. docs/security.md says so."""

from __future__ import annotations

import hashlib
import json

from sqlmodel import Session, select

from catch.core.models import CoachMessage


def fingerprint(name: str, args: dict) -> str:
    """Stable over the arguments *without* `confirm`, so a preview and its later confirmation match."""
    body = {k: v for k, v in sorted(args.items()) if k != "confirm"}
    return hashlib.sha256((name + "\0" + json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)).encode()).hexdigest()


def _blocks(row: CoachMessage) -> list[dict]:
    try:
        data = json.loads(row.blocks_json)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def preview_exists(session: Session, conversation_id: int, name: str, args: dict, *, before_message_id: int) -> bool:
    """True when a message older than `before_message_id` (the athlete's current message) holds a tool call with this name and
    fingerprint whose result was a preview (not an error, not a saved write)."""
    want = fingerprint(name, args)
    rows = session.exec(
        select(CoachMessage).where(CoachMessage.conversation_id == conversation_id, CoachMessage.id < before_message_id).order_by(CoachMessage.id)  # type: ignore[arg-type]
    ).all()
    pending: dict[str, str] = {}  # call id -> fingerprint, for calls with this name
    for row in rows:
        for block in _blocks(row):
            if block.get("type") == "tool_call" and block.get("name") == name and isinstance(block.get("input"), dict):
                pending[block["id"]] = fingerprint(name, block["input"])
            elif block.get("type") == "tool_result" and pending.get(block.get("id")) == want:
                output = block.get("output")
                if isinstance(output, dict) and output.get("saved") is False and output.get("preview") is not None and not block.get("is_error"):
                    return True
    return False
