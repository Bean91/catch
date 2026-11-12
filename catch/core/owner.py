"""The one place a request's owner id comes from.

There are no user accounts yet: the Pi has a single athlete, "owner". Everything that is
scoped per user (AI credentials, coach settings, conversations, AI usage, rate limits) takes its
owner id from here and nowhere else, so the public build can swap in a real user id by changing
this dependency, and tests can override it to act as a second owner."""

from __future__ import annotations

from fastapi import Depends

from catch.api.deps import require_auth
from catch.core.principal import ATHLETE, OWNER_ID


def current_owner_id(_: None = Depends(require_auth)) -> str:
    return ATHLETE.id


__all__ = ["OWNER_ID", "current_owner_id"]
