"""Shared helpers for the multi-user tests (session 24): two fixed users, a local ES256 key standing in for the
Supabase project's signing key, and a generator that can build one valid row for any owned table."""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timezone
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from sqlmodel import SQLModel

ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"
SUPABASE_URL = "https://test-project.supabase.co"
KID = "test-key-1"

_PRIVATE = ec.generate_private_key(ec.SECP256R1())
_OTHER_PRIVATE = ec.generate_private_key(ec.SECP256R1())


def _jwk(private, kid: str) -> dict:
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(private.public_key(), as_dict=True)
    return {**jwk, "kid": kid, "alg": "ES256", "use": "sig"}


def jwks() -> dict:
    return {"keys": [_jwk(_PRIVATE, KID)]}


def mint(
    sub: str = ALICE,
    *,
    session_id: str | None = None,
    expires_in: int = 3600,
    audience: str = "authenticated",
    issuer: str | None = None,
    role: str = "authenticated",
    kid: str = KID,
    algorithm: str = "ES256",
    key: Any = None,
    extra: dict | None = None,
    drop: tuple[str, ...] = (),
    email: str = "user@example.com",
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": issuer or f"{SUPABASE_URL}/auth/v1",
        "aud": audience,
        "sub": sub,
        "role": role,
        "email": email,
        "session_id": session_id or str(uuid.uuid5(uuid.NAMESPACE_URL, sub)),
        "aal": "aal1",
        "is_anonymous": False,
        "iat": now,
        "exp": now + expires_in,
    }
    claims.update(extra or {})
    for name in drop:
        claims.pop(name, None)
    return jwt.encode(claims, key if key is not None else _PRIVATE, algorithm=algorithm, headers={"kid": kid})


def foreign_key():
    """A different EC key — a token signed with it must be refused."""
    return _OTHER_PRIVATE


# --- one valid row for any owned table -----------------------------------------------------------------------------

_DUMMY_DATE = date(2026, 11, 2)
_DUMMY_DT = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)


def _dummy(cls: type, col) -> Any:
    import typing

    ann = cls.model_fields[col.name].annotation
    if typing.get_origin(ann) in (typing.Union, getattr(__import__("types"), "UnionType", None)):
        ann = next(a for a in typing.get_args(ann) if a is not type(None))
    if ann is bool:
        return False
    if ann is int:
        return 1
    if ann is float:
        return 1.0
    if ann is bytes:
        return b"x"
    if ann is datetime:
        return _DUMMY_DT
    if ann is date:
        return _DUMMY_DATE
    return f"x-{col.table.name}"


def owned_classes() -> list[type]:
    import catch.core.models  # noqa: F401  (registers the tables)
    from catch.core.tenant import OwnedOrShared, OwnedStrict

    return sorted(
        (m.class_ for m in SQLModel._sa_registry.mappers if issubclass(m.class_, (OwnedStrict, OwnedOrShared))),
        key=lambda c: c.__tablename__,
    )


def build_row(cls: type, parents: dict[str, dict]) -> Any:
    """Every column filled with a deterministic dummy (so two users get *identical* natural keys — the overlapping
    dates / same external ids the isolation tests need), foreign keys pointed at this owner's own parent rows."""
    values: dict[str, Any] = {}
    for col in cls.__table__.columns:
        if col.name == "owner_id":
            continue
        if col.primary_key and col.name == "id":
            continue
        if col.foreign_keys:
            parent_table = next(iter(col.foreign_keys)).column.table.name
            if parent_table == "user_profiles":
                continue
            parent = parents.get(parent_table)
            if parent is not None:
                values[col.name] = parent["id"] if "id" in parent else next(iter(parent.values()))
            elif not col.nullable:
                raise AssertionError(f"{cls.__tablename__}.{col.name} needs a {parent_table} row first")
            continue
        if not col.nullable or col.primary_key:
            values[col.name] = _dummy(cls, col)
    return cls(**values)
