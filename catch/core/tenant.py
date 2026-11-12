"""Session 24 (see docs/public-architecture.md §6): who owns this request's data.

One mechanism for both deployments. The personal Pi has exactly one owner, the constant "owner";
the public build has one owner per request — the validated Supabase user id — held in a ContextVar.
Nothing here ever reads an owner from a request body, a query string or an AI tool argument.

Fail closed: in a public deployment, touching an owned table with no owner set raises
`NoTenantContext`; there is no default owner there. (In a personal deployment the default is the
constant, so the single-user code paths and the whole existing test-suite are unchanged.)"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

from sqlalchemy import Column, ForeignKey, String
from sqlmodel import Field

from catch.core import config

PERSONAL_OWNER = "owner"

_owner: ContextVar[Optional[str]] = ContextVar("catch_owner", default=None)
_system: ContextVar[bool] = ContextVar("catch_system", default=False)


class NoTenantContext(RuntimeError):
    """An owned table was touched with no authenticated owner (public deployment)."""


class TenantViolation(RuntimeError):
    """A write named a different owner than the request's — never legitimate, always a bug or an attack."""


class ParentNotFound(LookupError):
    """A row referenced a parent id that does not exist *for this owner*. Reported as 'not found'
    (never 'forbidden') so a foreign id is indistinguishable from a missing one."""


def is_public() -> bool:
    return config.settings.deployment == "public"


def owner_or_none() -> Optional[str]:
    owner = _owner.get()
    if owner is not None:
        return owner
    return None if is_public() else PERSONAL_OWNER


def current_owner() -> str:
    owner = owner_or_none()
    if owner is None:
        raise NoTenantContext("no authenticated owner for this operation")
    return owner


def in_system_context() -> bool:
    return _system.get()


def set_owner(owner: Optional[str]):
    return _owner.set(owner)


def reset_owner(token) -> None:
    _owner.reset(token)


@contextmanager
def use_owner(owner: str) -> Iterator[str]:
    """Run a block as `owner` — a scheduled job iterating users, or a test acting as a second user."""
    if not owner:
        raise NoTenantContext("empty owner")
    token = _owner.set(owner)
    try:
        yield owner
    finally:
        _owner.reset(token)


@contextmanager
def system() -> Iterator[None]:
    """A pre-authentication or seeding block. On Postgres the connection stays the unprivileged
    `catch_api` role (no table grants at all — only the few SECURITY DEFINER functions it may EXECUTE);
    for seeds it allows writing rows whose owner is NULL (global reference data)."""
    token = _system.set(True)
    try:
        yield
    finally:
        _system.reset(token)


def pk(*rest: Any) -> tuple:
    """Primary key for `session.get` on a table whose key is (owner_id, ...rest)."""
    return (current_owner(), *rest)


class OwnedStrict:
    """Marker: every row belongs to exactly one owner (NOT NULL `owner_id`)."""


class OwnedOrShared:
    """Marker: `owner_id IS NULL` rows are global, read-only reference data (seeded exercises, foods
    from public databases, example templates); non-NULL rows belong to one owner."""


def owner_field(*, primary_key: bool = False, shared: bool = False, index: Optional[bool] = None):
    """The one definition of the tenant column: TEXT on both engines (the Pi's owner is not a uuid;
    on Postgres the value is the Supabase user id's text form), a foreign key to `user_profiles`
    with ON DELETE CASCADE, indexed unless it leads a composite key."""
    col = Column(
        "owner_id",
        String,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        primary_key=primary_key,
        nullable=shared and not primary_key,
        index=(not primary_key) if index is None else index,
    )
    if shared:
        return Field(default=None, sa_column=col)
    return Field(default_factory=current_owner, sa_column=col)
