"""Row level security with separate identities, over the same connection path the app uses (session 24):
login as `catch_api`, then take a user's identity for one transaction."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from tests.pg.conftest import signup


@contextmanager
def as_user(engine, uid: str | None):
    """One transaction as `authenticated` with `uid`'s claims — what tenant_hooks does on every begin."""
    with engine.connect() as conn:
        if uid is not None:
            conn.exec_driver_sql("SET LOCAL ROLE authenticated")
            conn.exec_driver_sql(
                "SELECT set_config('request.jwt.claims', %s, true), set_config('request.jwt.claim.sub', %s, true),"
                " set_config('search_path', 'catch, public', true)",
                (json.dumps({"sub": uid, "role": "authenticated"}), uid),
            )
        yield conn
        conn.rollback()


@pytest.fixture()
def two(clean):
    return signup("rls-a"), signup("rls-b")


def _insert_note(conn, uid, text_="n"):
    conn.execute(text("INSERT INTO notes (owner_id, date, text, created_at) VALUES (:o, '2026-11-02', :t, now())"), {"o": uid, "t": text_})


def test_each_user_sees_only_their_own_rows_even_with_identical_dates(runtime, admin, two):
    a, b = two
    with admin.begin() as conn:
        for u in (a, b):
            conn.execute(text("INSERT INTO catch.notes (owner_id, date, text, created_at) VALUES (:i, '2026-11-02', :t, now())"), {"i": u.id, "t": f"note of {u.id}"})
            conn.execute(text("INSERT INTO catch.daily_wellness (owner_id, date, source, updated_at) VALUES (:i, '2026-11-02', 'garmin', now())"), {"i": u.id})
    for me, other in ((a, b), (b, a)):
        with as_user(runtime, me.id) as conn:
            assert [r[0] for r in conn.execute(text("SELECT text FROM notes")).all()] == [f"note of {me.id}"]
            assert conn.execute(text("SELECT count(*) FROM daily_wellness")).scalar() == 1
            assert conn.execute(text("SELECT count(*) FROM notes WHERE owner_id = :o"), {"o": other.id}).scalar() == 0


def test_a_user_cannot_update_or_delete_another_users_rows(runtime, admin, two):
    a, b = two
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO catch.notes (owner_id, date, text, created_at) VALUES (:i, '2026-11-02', 'alice', now())"), {"i": a.id})
    with as_user(runtime, b.id) as conn:
        assert conn.execute(text("UPDATE notes SET text = 'pwned'")).rowcount == 0
        assert conn.execute(text("DELETE FROM notes")).rowcount == 0
    with as_user(runtime, a.id) as conn:
        assert conn.execute(text("SELECT text FROM notes")).scalar() == "alice"


def test_a_user_cannot_write_a_row_for_someone_else_or_reassign_their_own(runtime, two):
    a, b = two
    with as_user(runtime, b.id) as conn:
        with pytest.raises(DBAPIError, match="row-level security"):
            _insert_note(conn, a.id)
    with as_user(runtime, a.id) as conn:
        _insert_note(conn, a.id)
        with pytest.raises(DBAPIError, match="row-level security"):
            conn.execute(text("UPDATE notes SET owner_id = :o"), {"o": b.id})


def test_no_identity_means_no_access_at_all(runtime, admin, two):
    a, _ = two
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO catch.notes (owner_id, date, text, created_at) VALUES (:i, '2026-11-02', 'x', now())"), {"i": a.id})
    with as_user(runtime, None) as conn:  # catch_api itself, no SET ROLE: it has no table grants
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text("SELECT * FROM catch.notes"))
    with as_user(runtime, str(uuid.uuid4())) as conn:  # an authenticated stranger
        assert conn.execute(text("SELECT count(*) FROM notes")).scalar() == 0
    with runtime.connect() as conn:
        # The runtime role can become `authenticated` and nothing else: not anon, not service_role, not postgres.
        for other in ("anon", "service_role", "postgres", "supabase_admin"):
            with pytest.raises(ProgrammingError, match="permission denied to set role"):
                conn.exec_driver_sql(f"SET LOCAL ROLE {other}")
            conn.rollback()


def test_the_claims_reach_auth_uid_and_role_is_authenticated(runtime, two):
    a, _ = two
    with as_user(runtime, a.id) as conn:
        assert conn.execute(text("SELECT auth.uid()::text")).scalar() == a.id
        assert conn.execute(text("SELECT current_user")).scalar() == "authenticated"


def test_set_local_does_not_leak_into_the_next_transaction_on_the_same_connection(runtime, two):
    """Pool reuse / transaction pooling: identity must die with the transaction."""
    a, _ = two
    with runtime.connect() as conn:
        conn.exec_driver_sql("SET LOCAL ROLE authenticated")
        conn.exec_driver_sql("SELECT set_config('request.jwt.claim.sub', %s, true)", (a.id,))
        assert conn.execute(text("SELECT current_user")).scalar() == "authenticated"
        conn.commit()
        assert conn.execute(text("SELECT current_user")).scalar() == "catch_api"
        assert conn.execute(text("SELECT coalesce(current_setting('request.jwt.claim.sub', true), '')")).scalar() == ""
        conn.rollback()


def test_foreign_key_checks_cannot_be_used_to_attach_to_another_users_rows(runtime, admin, two):
    """A plain FK would accept any existing parent id (the check bypasses RLS); the composite FK does not."""
    a, b = two
    with admin.begin() as conn:
        act = conn.execute(text("INSERT INTO catch.activities (owner_id, source, external_id, updated_at) VALUES (:i, 'garmin', 'x', now()) RETURNING id"), {"i": a.id}).scalar()
    with as_user(runtime, b.id) as conn:
        with pytest.raises(IntegrityError, match="fk_tenant_strokes_activity_id"):
            conn.execute(text("INSERT INTO strokes (owner_id, activity_id, seq, t) VALUES (:o, :a, 0, 0)"), {"o": b.id, "a": act})
    with as_user(runtime, a.id) as conn:
        conn.execute(text("INSERT INTO strokes (owner_id, activity_id, seq, t) VALUES (:o, :a, 0, 0)"), {"o": a.id, "a": act})


def test_shared_reference_rows_are_readable_by_all_and_writable_by_none(runtime, admin, two):
    a, b = two
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO catch.exercises (owner_id, name, default_equipment_type, movement_pattern, unilateral, primary_muscles_json, secondary_muscles_json, custom, created_at) VALUES (NULL, 'Seeded Squat', 'barbell', 'squat', false, '[]', '[]', false, now())"))
    for u in (a, b):
        with as_user(runtime, u.id) as conn:
            assert conn.execute(text("SELECT count(*) FROM exercises WHERE name = 'Seeded Squat'")).scalar() == 1
            assert conn.execute(text("UPDATE exercises SET name = 'hacked'")).rowcount == 0
            assert conn.execute(text("DELETE FROM exercises")).rowcount == 0
            with pytest.raises(DBAPIError, match="row-level security"):
                conn.execute(text("INSERT INTO exercises (owner_id, name, default_equipment_type, movement_pattern, unilateral, primary_muscles_json, secondary_muscles_json, custom, created_at) VALUES (NULL, 'mine', 'barbell', 'squat', false, '[]', '[]', true, now())"))
    with as_user(runtime, a.id) as conn:  # but a user's own custom exercise is private
        conn.execute(text("INSERT INTO exercises (owner_id, name, default_equipment_type, movement_pattern, unilateral, primary_muscles_json, secondary_muscles_json, custom, created_at) VALUES (:o, 'Alice Special', 'barbell', 'squat', false, '[]', '[]', true, now())"), {"o": a.id})
    with as_user(runtime, b.id) as conn:
        assert conn.execute(text("SELECT count(*) FROM exercises WHERE name = 'Alice Special'")).scalar() == 0


def test_profiles_are_private_and_another_users_cannot_be_created(runtime, two):
    a, b = two
    with as_user(runtime, a.id) as conn:
        assert [r[0] for r in conn.execute(text("SELECT id FROM user_profiles")).all()] == [a.id]
        with pytest.raises(DBAPIError, match="row-level security"):
            conn.execute(text("INSERT INTO user_profiles (id, created_at) VALUES (:i, now())"), {"i": str(uuid.uuid4())})


def test_the_security_definer_lookups_only_answer_the_runtime_role(runtime, admin, two):
    a, b = two
    with runtime.connect() as conn:
        assert conn.execute(text("SELECT catch_private.session_is_live(:s)"), {"s": str(uuid.uuid4())}).scalar() is False
        ids = set(conn.execute(text("SELECT catch_private.list_user_ids()")).scalars().all())
        assert {a.id, b.id} <= ids
        conn.rollback()
    with as_user(runtime, a.id) as conn:  # a user-identity transaction can't call them
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text("SELECT catch_private.list_user_ids()"))
