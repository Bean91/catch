"""Session 24 (docs/public-architecture.md §6): the ORM-level half of tenant isolation, plus the
Postgres request-identity hook. Installed once on SQLAlchemy's `Session` class (import of
catch.core.models), so it covers every session — the request's, the scheduler's, the tests'.

1. do_orm_execute  — every ORM SELECT/UPDATE/DELETE on an owned model gets `owner_id = <owner>`
   (shared reference models: `owner_id = <owner> OR owner_id IS NULL` for reads, strictly the owner for
   writes). Applied to `session.get`, relationship loads and bulk statements alike.
2. before_flush    — new/changed/deleted owned rows must carry the request's owner (TenantViolation
   otherwise); a row's references to other rows (declared FKs + the undeclared integer ids listed below)
   must resolve *for this owner* (ParentNotFound otherwise — foreign-key checks bypass RLS, so this is
   not something the database can be left to do alone).
3. after_begin     — on a Postgres engine flagged `catch_rls`, every transaction (not every request:
   `commit()` ends a transaction and `SET LOCAL` dies with it) is switched to the `authenticated`
   role with the request's JWT claims, so the RLS policies see the right `auth.uid()`."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import column as _column
from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session, with_loader_criteria
from sqlmodel import SQLModel

from catch.core import tenant
from catch.core.tenant import NoTenantContext, OwnedOrShared, OwnedStrict, ParentNotFound, TenantViolation

# Integer ids that name another owned row but carry no declared ForeignKey in the model.
EXTRA_REFS: tuple[tuple[str, str, str], ...] = (
    ("merge_log", "canonical_id", "canonical_activities"),
    ("technique_notes", "canonical_id", "canonical_activities"),
    ("technique_notes", "piece_id", "pieces"),
    ("coach_feedback", "canonical_id", "canonical_activities"),
    ("coach_feedback", "event_id", "events"),
    ("coach_feedback", "planned_id", "planned_workouts"),
    ("coach_feedback_revisions", "feedback_id", "coach_feedback"),
    ("workout_templates", "duplicated_from_id", "workout_templates"),
    ("planned_workouts", "template_id", "workout_templates"),
)

_installed = False
_refs_cache: dict[type, list[tuple[str, type]]] | None = None


def _owned_classes() -> dict[str, type]:
    return {
        m.class_.__tablename__: m.class_
        for m in SQLModel._sa_registry.mappers
        if issubclass(m.class_, (OwnedStrict, OwnedOrShared))
    }


def reference_columns() -> list[tuple[str, str, str]]:
    """(child table, child column, parent table) for every cross-row reference between owned tables."""
    owned = _owned_classes()
    out: list[tuple[str, str, str]] = []
    for name, cls in owned.items():
        table = SQLModel.metadata.tables[name]
        for col in table.columns:
            if col.name == "owner_id":
                continue
            for fk in col.foreign_keys:
                parent = fk.column.table.name
                if parent in owned:
                    out.append((name, col.name, parent))
    out.extend(EXTRA_REFS)
    return sorted(set(out))


def _refs_for(cls: type) -> list[tuple[str, type]]:
    global _refs_cache
    if _refs_cache is None:
        owned = _owned_classes()
        cache: dict[type, list[tuple[str, type]]] = {}
        for child, col, parent in reference_columns():
            cache.setdefault(owned[child], []).append((col, owned[parent]))
        _refs_cache = cache
    return _refs_cache.get(cls, [])


def _owner_col(cls):
    # SQLAlchemy analyses a loader-criteria lambda once against the unmapped marker class, where the real
    # column doesn't exist; every mapped subclass has it.
    return getattr(cls, "owner_id", None) if hasattr(cls, "owner_id") else _column("owner_id")


def _scope(state) -> None:
    owned_involved = any(issubclass(m.class_, (OwnedStrict, OwnedOrShared)) for m in state.all_mappers)
    if state.execution_options.get("tenant_unscoped"):
        return
    owner = tenant.owner_or_none()
    if owner is None:
        if owned_involved and not tenant.in_system_context():
            raise NoTenantContext("owned table accessed with no authenticated owner")
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    read = state.is_select
    state.statement = state.statement.options(
        with_loader_criteria(OwnedStrict, lambda cls: _owner_col(cls) == owner, include_aliases=True),
        with_loader_criteria(
            OwnedOrShared,
            (lambda cls: or_(_owner_col(cls) == owner, _owner_col(cls).is_(None)))
            if read
            else (lambda cls: _owner_col(cls) == owner),
            include_aliases=True,
        ),
    )


def _owner_for_write(obj: Any, owner: str | None) -> None:
    shared = isinstance(obj, OwnedOrShared)
    current = obj.owner_id
    if current is None:
        if shared and tenant.in_system_context():
            return
        if owner is None:
            raise NoTenantContext("owned row written with no authenticated owner")
        obj.owner_id = owner
        return
    if owner is None:
        raise NoTenantContext("owned row written with no authenticated owner")
    if current != owner:
        raise TenantViolation(f"{type(obj).__name__} belongs to a different owner than this request")


def _check_refs(session: Session, obj: Any, cache: dict) -> None:
    if not tenant.is_public():
        return  # a one-owner install can't name another owner's row; keep its write path exactly as it was
    for col, parent_cls in _refs_for(type(obj)):
        value = getattr(obj, col, None)
        if value is None:
            continue
        key = (parent_cls, value)
        if key not in cache:
            pk_col = list(parent_cls.__table__.primary_key.columns)
            id_col = next((c for c in pk_col if c.name != "owner_id"), pk_col[0])
            # Goes through do_orm_execute, so the owner filter applies to this lookup too.
            cache[key] = session.execute(select(id_col).where(id_col == value).limit(1)).first() is not None
        if not cache[key]:
            raise ParentNotFound(f"{parent_cls.__tablename__} {value} not found")


def _before_flush(session: Session, flush_context, instances) -> None:
    owner = tenant.owner_or_none()
    cache: dict = {}
    with session.no_autoflush:
        for obj in list(session.new):
            if isinstance(obj, (OwnedStrict, OwnedOrShared)):
                _owner_for_write(obj, owner)
                if obj.owner_id is not None:
                    _check_refs(session, obj, cache)
        for obj in list(session.dirty):
            if not isinstance(obj, (OwnedStrict, OwnedOrShared)) or not session.is_modified(obj):
                continue
            if obj.owner_id is None and (tenant.in_system_context() or not tenant.is_public()):
                pass  # a seeded/global row: editable by the single owner of a personal install only
            else:
                if owner is None:
                    raise NoTenantContext("owned row written with no authenticated owner")
                if obj.owner_id != owner:
                    raise TenantViolation(f"{type(obj).__name__} belongs to a different owner than this request")
            _check_refs(session, obj, cache)
        for obj in list(session.deleted):
            if isinstance(obj, (OwnedStrict, OwnedOrShared)):
                if obj.owner_id is None and (tenant.in_system_context() or not tenant.is_public()):
                    continue
                if owner is None:
                    raise NoTenantContext("owned row deleted with no authenticated owner")
                if obj.owner_id != owner:
                    raise TenantViolation(f"{type(obj).__name__} belongs to a different owner than this request")


def claims_json(owner: str) -> str:
    return json.dumps({"sub": owner, "role": "authenticated", "aud": "authenticated"})


def _after_begin(session: Session, transaction, connection) -> None:
    if connection.dialect.name != "postgresql" or not getattr(connection.engine, "catch_rls", False):
        return
    owner = tenant.owner_or_none()
    if owner is None:
        if tenant.in_system_context():
            connection.exec_driver_sql("SELECT set_config('search_path', 'catch, public', true)")
            return
        raise NoTenantContext("transaction begun with no authenticated owner")
    connection.exec_driver_sql("SET LOCAL ROLE authenticated")
    # auth.uid() reads request.jwt.claim.sub, falling back to request.jwt.claims->>'sub'
    # (pg_get_functiondef on the real Supabase stack); both are set so either reader sees the owner.
    connection.exec_driver_sql(
        "SELECT set_config('request.jwt.claims', %s, true), set_config('request.jwt.claim.sub', %s, true),"
        " set_config('search_path', 'catch, public', true)",
        (claims_json(owner), owner),
    )


def install() -> None:
    global _installed
    if _installed:
        return
    event.listen(Session, "do_orm_execute", _scope)
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_begin", _after_begin)
    _installed = True
