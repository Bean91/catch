"""Alembic against a real Supabase Postgres (session 24): the schema, the RLS layer, rollback, and backup/restore."""

from __future__ import annotations

import os
import subprocess
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlmodel import SQLModel

from tests.pg.conftest import DB_URL, run_alembic, signup, runtime_url, RUNTIME_PASSWORD
import catch.core.models  # noqa: F401


def q(admin, sql, **params):
    with admin.connect() as conn:
        return conn.execute(text(sql), params).all()


def test_the_migrated_schema_matches_the_models_exactly(migrated, admin):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    def include(obj, name, type_, reflected, compare_to):
        if type_ == "unique_constraint" and name and name.startswith("uq_owner_id_"):
            return False
        if type_ == "foreign_key_constraint" and name and name.startswith("fk_tenant_"):
            return False
        if type_ == "table" and name == "alembic_version":
            return False
        return True

    with admin.connect() as conn:
        conn.execute(text("SET search_path TO catch, public"))
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "include_object": include, "include_schemas": False})
        diff = compare_metadata(ctx, SQLModel.metadata)
    assert diff == [], f"alembic head and the SQLModel metadata disagree: {diff[:5]}"


def test_every_table_has_forced_rls_and_a_policy_per_command(migrated, admin):
    rows = q(admin, """SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                              (SELECT count(*) FROM pg_policies p WHERE p.schemaname = 'catch' AND p.tablename = c.relname)
                       FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = 'catch' AND c.relkind = 'r' AND c.relname <> 'alembic_version'""")
    assert len(rows) == len(SQLModel.metadata.tables)
    expected = {"weather_cells": 2}
    for name, rls, forced, policies in rows:
        assert rls and forced, f"{name}: RLS not enabled and forced"
        assert policies == expected.get(name, 4), f"{name}: {policies} policies"


def test_grants_leave_the_runtime_role_and_anon_with_nothing(migrated, admin):
    for table in ("activities", "user_profiles", "weather_cells"):
        assert q(admin, f"SELECT has_table_privilege('catch_api', 'catch.{table}', 'SELECT')")[0][0] is False, table
        assert q(admin, f"SELECT has_table_privilege('anon', 'catch.{table}', 'SELECT')")[0][0] is False, table
        assert q(admin, f"SELECT has_table_privilege('service_role', 'catch.{table}', 'SELECT')")[0][0] is False, table
        assert q(admin, f"SELECT has_table_privilege('authenticated', 'catch.{table}', 'SELECT')")[0][0] is True, table
    role = q(admin, "SELECT rolsuper, rolbypassrls, rolinherit, rolcanlogin FROM pg_roles WHERE rolname = 'catch_api'")[0]
    assert role == (False, False, False, True)
    # the SECURITY DEFINER lookups are executable by the runtime role and nobody else
    for fn in ("catch_private.session_is_live(uuid)", "catch_private.resolve_api_token(text)", "catch_private.list_user_ids()"):
        assert q(admin, f"SELECT has_function_privilege('catch_api', '{fn}', 'EXECUTE')")[0][0] is True, fn
        for role_name in ("anon", "authenticated"):
            assert q(admin, f"SELECT has_function_privilege('{role_name}', '{fn}', 'EXECUTE')")[0][0] is False, (role_name, fn)


def test_the_schema_is_not_in_the_data_apis_default_exposure(migrated, admin):
    # PostgREST exposes `public` by default; Catch's tables live elsewhere, and anon can't even enter the schema.
    assert q(admin, "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename IN ('activities', 'user_profiles')")[0][0] == 0
    assert q(admin, "SELECT has_schema_privilege('anon', 'catch', 'USAGE')")[0][0] is False


def test_the_storage_bucket_is_private_and_limited(migrated, admin):
    public, limit, mimes = q(admin, "SELECT public, file_size_limit, allowed_mime_types FROM storage.buckets WHERE id = 'piece-photos'")[0]
    assert public is False and limit == 5242880 and set(mimes) == {"image/jpeg", "image/png", "image/webp"}
    assert q(admin, "SELECT count(*) FROM pg_policies WHERE schemaname = 'storage' AND policyname LIKE 'catch_piece_photos_%'")[0][0] == 4


def test_a_new_auth_user_gets_a_profile_and_deleting_the_user_removes_everything(migrated, admin):
    user = signup("trigger")
    assert q(admin, "SELECT id, email FROM catch.user_profiles WHERE id = :i", i=user.id) == [(user.id, user.email)]
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO catch.notes (owner_id, date, text, created_at) VALUES (:i, '2026-11-02', 'x', now())"), {"i": user.id})
        conn.execute(text("DELETE FROM auth.users WHERE id = :i"), {"i": user.id})
    assert q(admin, "SELECT count(*) FROM catch.user_profiles WHERE id = :i", i=user.id)[0][0] == 0
    assert q(admin, "SELECT count(*) FROM catch.notes WHERE owner_id = :i", i=user.id)[0][0] == 0  # cascaded


def test_a_failing_profile_trigger_never_blocks_a_signup(migrated, admin):
    with admin.begin() as conn:
        conn.execute(text("ALTER TABLE catch.user_profiles RENAME TO user_profiles_off"))
    try:
        user = signup("blocked")  # would 500 if the trigger raised
        assert user.id
    finally:
        with admin.begin() as conn:
            conn.execute(text("ALTER TABLE catch.user_profiles_off RENAME TO user_profiles"))
            conn.execute(text("DELETE FROM auth.users WHERE email LIKE 'blocked-%'"))


def test_rollback_keeps_data_and_the_upgrade_restores_the_protection(migrated, admin):
    user = signup("rollback")
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO catch.notes (owner_id, date, text, created_at) VALUES (:i, '2026-11-02', 'keep me', now())"), {"i": user.id})
    down = run_alembic("downgrade", "0001")
    assert down.returncode == 0, down.stderr[-1500:]
    assert q(admin, "SELECT count(*) FROM pg_policies WHERE schemaname = 'catch'")[0][0] == 0
    assert q(admin, "SELECT relrowsecurity FROM pg_class WHERE oid = 'catch.notes'::regclass")[0][0] is False
    assert q(admin, "SELECT count(*) FROM pg_roles WHERE rolname = 'catch_api'")[0][0] == 0
    assert q(admin, "SELECT text FROM catch.notes WHERE owner_id = :i", i=user.id) == [("keep me",)]  # data survives
    up = run_alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr[-1500:]
    with admin.begin() as conn:
        conn.execute(text(f"ALTER ROLE catch_api PASSWORD '{RUNTIME_PASSWORD}'"))
    assert q(admin, "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid = 'catch.notes'::regclass")[0][0] is True
    assert q(admin, "SELECT text FROM catch.notes WHERE owner_id = :i", i=user.id) == [("keep me",)]
    with admin.begin() as conn:
        conn.execute(text("DELETE FROM auth.users WHERE id = :i"), {"i": user.id})


def test_a_second_upgrade_is_a_noop_and_base_downgrade_works(migrated, admin):
    assert run_alembic("upgrade", "head").returncode == 0
    assert run_alembic("downgrade", "base").returncode == 0
    assert q(admin, "SELECT count(*) FROM pg_tables WHERE schemaname = 'catch' AND tablename <> 'alembic_version'")[0][0] == 0
    assert run_alembic("upgrade", "head").returncode == 0
    with admin.begin() as conn:
        conn.execute(text(f"ALTER ROLE catch_api PASSWORD '{RUNTIME_PASSWORD}'"))


def test_backup_and_restore_keeps_rows_policies_and_isolation(migrated, admin, tmp_path):
    """pg_dump of the catch schema, drop it, restore: rows come back and the policies still hold."""
    a, b = signup("backup-a"), signup("backup-b")
    with admin.begin() as conn:
        for u, txt in ((a, "alice"), (b, "bob")):
            conn.execute(text("INSERT INTO catch.notes (owner_id, date, text, created_at) VALUES (:i, '2026-11-02', :t, now())"), {"i": u.id, "t": txt})
    parts = urlsplit(DB_URL)
    env = {**os.environ, "PGPASSWORD": parts.password or ""}
    conn_args = ["-h", parts.hostname, "-p", str(parts.port), "-U", parts.username, "-d", parts.path.lstrip("/")]
    dump = tmp_path / "catch.dump"
    done = subprocess.run(["pg_dump", *conn_args, "-n", "catch", "-Fc", "-f", str(dump)], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
    before = q(admin, "SELECT count(*) FROM pg_policies WHERE schemaname = 'catch'")[0][0]
    with admin.begin() as conn:
        conn.execute(text("DROP SCHEMA catch CASCADE"))
    assert q(admin, "SELECT count(*) FROM pg_tables WHERE schemaname = 'catch'")[0][0] == 0
    done = subprocess.run(["pg_restore", *conn_args, "--no-owner", str(dump)], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]
    assert q(admin, "SELECT text FROM catch.notes ORDER BY text") == [("alice",), ("bob",)]
    assert q(admin, "SELECT count(*) FROM pg_policies WHERE schemaname = 'catch'")[0][0] == before
    assert q(admin, "SELECT relforcerowsecurity FROM pg_class WHERE oid = 'catch.notes'::regclass")[0][0] is True
    # ...and the restored policies still isolate (as a user, through the runtime role)
    from tests.pg.test_rls import as_user

    from catch.core.db_pg import build_pg_engine

    runtime = build_pg_engine(runtime_url())
    try:
        with as_user(runtime, a.id) as conn:
            assert [r[0] for r in conn.execute(text("SELECT text FROM notes")).all()] == ["alice"]
    finally:
        runtime.dispose()
    with admin.begin() as conn:
        conn.execute(text("DELETE FROM auth.users WHERE id IN (:a, :b)"), {"a": a.id, "b": b.id})
