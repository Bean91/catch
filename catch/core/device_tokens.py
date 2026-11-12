"""Device bearer tokens (MCP / coach), resolved to the owner who minted them.

A token is looked up *before* any owner is known, so on Postgres this goes through the one SECURITY DEFINER
function the runtime role may execute (catch_private.resolve_api_token) rather than a table read."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlmodel import Session, select

from catch.core import tenant
from catch.core.models import ApiToken


@dataclass(frozen=True)
class ResolvedToken:
    token_id: int
    owner_id: str
    role: Optional[str]
    display_name: Optional[str]


def resolve(session: Session, token_hash: str) -> ResolvedToken | None:
    with tenant.system():
        if session.get_bind().dialect.name == "postgresql":
            row = session.connection().execute(
                text("SELECT token_id, owner_id, role, display_name FROM catch_private.resolve_api_token(:h)"),
                {"h": token_hash},
            ).first()
            session.rollback()
        else:
            row = session.exec(
                select(ApiToken.id, ApiToken.owner_id, ApiToken.role, ApiToken.display_name)
                .where(ApiToken.token_hash == token_hash)
                .execution_options(tenant_unscoped=True)
            ).first()
    return ResolvedToken(row[0], row[1], row[2], row[3]) if row else None


def touch(session: Session, resolved: ResolvedToken) -> None:
    """Best-effort `last_used_at`, written under the token owner's own context."""
    with tenant.use_owner(resolved.owner_id):
        row = session.get(ApiToken, resolved.token_id)
        if row is not None:
            row.last_used_at = datetime.now(timezone.utc)
            session.commit()
