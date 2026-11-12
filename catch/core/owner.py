"""The one place a request's owner id comes from.

Personal install: the single athlete, "owner". Public deployment: the signed-in user's verified id. Everything that is
scoped per user (AI credentials, coach settings, conversations, AI usage, rate limits) takes its
owner id from here and nowhere else, so the public build can swap in a real user id by changing
this dependency, and tests can override it to act as a second owner."""

from __future__ import annotations

from fastapi import Depends

from catch.api.deps import require_auth
from catch.core import tenant
from catch.core.principal import OWNER_ID


def current_owner_id(_: None = Depends(require_auth)) -> str:
    return tenant.current_owner()


__all__ = ["OWNER_ID", "current_owner_id"]
