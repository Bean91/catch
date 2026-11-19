"""Server-side confirmation for the in-app coach (session 28).

A write tool previews unless `confirm` is exactly true — but that is only a convention the model follows: a model that has been
steered by injected text can pass confirm=true on its first call. For the in-app coach the server therefore refuses to honour a
confirm unless this conversation already holds a *preview of the same call* from an EARLIER turn and the athlete has sent a message
since. A preview and its confirm inside one turn (the shape an injected instruction would produce) is downgraded to a preview.

Two further conditions (session 28 review): the preview must come from the **immediately preceding** turn — no athlete message in between —
and the athlete's reply must read as agreement ("yes", "go ahead", "save it"…) and not as a negation or a change of subject. The wording check is a
heuristic (English); anything it doesn't recognise just previews again, which fails safe. It stops the two-turn trick where an invisible injected
preview is "confirmed" by an unrelated "thanks, what about tomorrow?".

MCP and REST callers are not covered by this: their confirmation is mediated by the client (the MCP client's own tool-approval
prompt) and limited by the token's scope. docs/security.md says so."""

from __future__ import annotations

import hashlib
import json
import re

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
    last_human = 0  # id of the latest athlete-typed message before the current one
    rows = session.exec(
        select(CoachMessage).where(CoachMessage.conversation_id == conversation_id, CoachMessage.id < before_message_id).order_by(CoachMessage.id)  # type: ignore[arg-type]
    ).all()
    pending: dict[str, str] = {}  # call id -> fingerprint, for calls with this name
    previewed_at: dict[str, int] = {}
    found_at: int | None = None
    for row in rows:
        blocks = _blocks(row)
        if row.role == "user" and any(b.get("type") == "text" for b in blocks):
            last_human = row.id or 0
        for block in blocks:
            if block.get("type") == "tool_call" and block.get("name") == name and isinstance(block.get("input"), dict):
                pending[block["id"]] = fingerprint(name, block["input"])
                previewed_at[block["id"]] = row.id or 0
            elif block.get("type") == "tool_result" and pending.get(block.get("id")) == want:
                output = block.get("output")
                if isinstance(output, dict) and output.get("saved") is False and output.get("preview") is not None and not block.get("is_error"):
                    found_at = max(found_at or 0, previewed_at.get(block["id"], 0))
    # Only the immediately preceding turn counts: the preview must be newer than the athlete's previous message.
    return found_at is not None and found_at > last_human


_AGREE = re.compile(r"\b(yes|yep|yeah|yup|ok|okay|sure|confirm|confirmed|approve|approved|correct|agreed|go ahead|do it|save it|add it|log it|schedule it|looks good|sounds good|that's right|that is right|please do|go for it)\b", re.I)
_DISAGREE = re.compile(r"\b(no|nope|don't|dont|do not|not|cancel|stop|wait|instead|change|actually|but|never)\b", re.I)


def is_affirmation(text: str) -> bool:
    text = (text or "").strip()
    return 0 < len(text) <= 120 and bool(_AGREE.search(text)) and not _DISAGREE.search(text)
