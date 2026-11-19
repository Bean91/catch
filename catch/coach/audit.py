"""The tool-call audit log (session 28): who called which tool through which door, whether it wrote, and how it ended — never what
was asked or answered (only a hash of the arguments). Best effort: a failure here must never break the call it describes."""

from __future__ import annotations

import hashlib
import json
import logging

from sqlmodel import Session

from catch.core.models import ToolCallLog
from catch.core.principal import Principal

logger = logging.getLogger("catch.coach.audit")


def _kind(principal) -> str:
    return principal.role if isinstance(principal, Principal) else "none"


def record(session: Session, *, name: str, args: dict, ctx: dict, is_write: bool, confirmed: bool, outcome: str) -> None:
    via = ctx.get("via") or "other"
    # Reads from the in-app coach are not logged (every chat turn makes several); everything else about it, and everything over
    # MCP/REST, is — so the Privacy page can answer "what has an outside client done with my account".
    if via == "ai_coach" and not is_write and outcome in ("ok", "preview"):
        return
    try:
        body = json.dumps({k: v for k, v in sorted((args or {}).items()) if k != "confirm"}, sort_keys=True, default=str)
        session.add(ToolCallLog(
            tool=name, via=via, principal_kind=_kind(ctx.get("principal")), is_write=is_write, confirmed=confirmed, outcome=outcome,
            args_hash=hashlib.sha256(body.encode()).hexdigest()[:32],
        ))
        session.commit()
    except Exception:  # noqa: BLE001 — never let the log break the call
        session.rollback()
        logger.warning("could not write a tool-call log row for %s", name)
