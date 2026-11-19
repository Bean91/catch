"""Row level security for EVERY strictly owned table, with two real GoTrue identities and the ORM's own tenant filter out of the
picture (session 28). tests/tenancy proves the ORM layer on SQLite; this proves the database layer on Postgres: even if a query
forgot its owner filter, `authenticated` could not read, change, delete or forge another user's row in any table.

Rows come from the same generator the tenancy suite uses, inserted as the table owner (the admin login) for both users so every
table has something of Alice's to attack."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, SQLModel

from catch.core import tenant, tenant_hooks
from catch.core.tenant import OwnedStrict
from tests.pg.conftest import signup
from tests.pg.test_rls import as_user
from tests.tenancy import kit

pytestmark = pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")

# Tables whose generated placeholder row can't be inserted on Postgres because of a CHECK/enum the generator can't know. Each is
# covered by hand elsewhere (named here so a new exclusion is a visible decision, never a silent skip).
UNGENERATABLE: set[str] = set()


def _ordered(strict_only: bool):
    by_table = {c.__tablename__: c for c in kit.owned_classes() if issubclass(c, OwnedStrict) or not strict_only}
    return [by_table[t.name] for t in SQLModel.metadata.sorted_tables if t.name in by_table]


def _strict_classes():
    return _ordered(True)


@pytest.fixture()
def seeded(clean, admin, monkeypatch):
    monkeypatch.setattr(tenant_hooks, "_check_refs", lambda *a, **k: None)
    a, b = signup("rls-all-a"), signup("rls-all-b")
    created: dict[str, set[str]] = {}
    with admin.connect() as conn:
        conn.exec_driver_sql("SET search_path TO catch, public")
        conn.exec_driver_sql("SET session_replication_role = replica")  # the generator uses placeholder ids; FK triggers off, CHECKs stay on
        for user in (a, b):
            parents: dict[str, dict] = {}
            with tenant.use_owner(user.id), Session(bind=conn) as s:
                for cls in _ordered(False):  # the shared-reference tables too: strict tables point at them
                    if cls.__tablename__ in UNGENERATABLE:
                        continue
                    row = kit.build_row(cls, parents)
                    s.add(row)
                    s.flush()
                    s.refresh(row)
                    parents[cls.__tablename__] = {c.name: getattr(row, c.name) for c in cls.__table__.primary_key.columns if c.name != "owner_id"}
                    if issubclass(cls, OwnedStrict):
                        created.setdefault(cls.__tablename__, set()).add(user.id)
                s.commit()
        conn.commit()  # the Session joined this connection's transaction; committing it does not commit the connection's
    return a, b, sorted(created)


def test_the_generator_reached_every_strictly_owned_table(seeded):
    _, _, tables = seeded
    assert set(tables) == {c.__tablename__ for c in _strict_classes()} - UNGENERATABLE


def test_bob_can_neither_see_change_delete_nor_forge_alices_rows_in_any_table(runtime, admin, seeded):
    a, b, tables = seeded
    failures = []
    for table in tables:
        with as_user(runtime, b.id) as conn:
            q = f"catch.{table}"
            seen = conn.execute(text(f"SELECT count(*) FROM {q} WHERE owner_id = :a"), {"a": a.id}).scalar()
            own = conn.execute(text(f"SELECT count(*) FROM {q}")).scalar()
            if seen != 0:
                failures.append(f"{table}: Bob can read {seen} of Alice's rows")
            if own < 1:
                failures.append(f"{table}: Bob can't read his own row")
            for verb, sql in (
                ("update", f"UPDATE {q} SET owner_id = owner_id WHERE owner_id = :a"),
                ("delete", f"DELETE FROM {q} WHERE owner_id = :a"),
            ):
                if conn.execute(text(sql), {"a": a.id}).rowcount != 0:
                    failures.append(f"{table}: Bob's {verb} touched Alice's rows")
        # Forge: Bob inserts a copy of Alice's row, owner_id and all.
        with admin.connect() as conn:
            alice_row = conn.execute(text(f"SELECT to_jsonb(whole_row) FROM catch.{table} whole_row WHERE owner_id = :a LIMIT 1"), {"a": a.id}).scalar()
        with as_user(runtime, b.id) as conn:
            try:
                conn.execute(text(f"INSERT INTO catch.{table} SELECT * FROM jsonb_populate_record(NULL::catch.{table}, CAST(:j AS jsonb))"), {"j": json.dumps(alice_row)})
                failures.append(f"{table}: Bob inserted a row owned by Alice")
            except DBAPIError as exc:
                if "row-level security" not in str(exc):
                    failures.append(f"{table}: forged insert failed for the wrong reason: {str(exc)[:120]}")
        # Hand-over: Alice may not re-assign her own row to Bob.
        with as_user(runtime, a.id) as conn:
            try:
                conn.execute(text(f"UPDATE catch.{table} SET owner_id = :b"), {"b": b.id})
                failures.append(f"{table}: Alice re-assigned her row to Bob")
            except DBAPIError as exc:
                if "row-level security" not in str(exc):
                    failures.append(f"{table}: re-assignment failed for the wrong reason: {str(exc)[:120]}")
    assert not failures, "\n".join(failures)


def test_anon_and_the_bare_runtime_role_have_no_grant_on_any_owned_table(runtime, admin, seeded):
    _, _, tables = seeded
    with admin.connect() as conn:
        for role in ("anon", "service_role", "catch_api", "PUBLIC"):
            for table in tables:
                if role == "PUBLIC":
                    ok = conn.execute(text("SELECT NOT has_table_privilege('public', :t, 'SELECT')"), {"t": f"catch.{table}"}).scalar()
                else:
                    ok = conn.execute(text("SELECT NOT has_table_privilege(:r, :t, 'SELECT,INSERT,UPDATE,DELETE')"), {"r": role, "t": f"catch.{table}"}).scalar()
                assert ok, f"{role} has a privilege on catch.{table}"
