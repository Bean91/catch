"""The actual FastAPI-to-Supabase path (session 24): the app in public mode, connected as the unprivileged
`catch_api` role, authenticating real GoTrue-issued JWTs, with row level security evaluated by Postgres."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlmodel import Session

from catch.core import config, supabase_auth, tenant
from tests.pg.conftest import (
    API_URL, PUBLISHABLE, RUNTIME_PASSWORD, SECRET, jwks_fetch, runtime_url, signout_everywhere, signup,
)

pytestmark = pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")


@pytest.fixture()
def app(clean, runtime, monkeypatch):
    import catch.main as main_module
    from catch.api import deps
    from catch.core import db as db_module

    monkeypatch.setattr(tenant, "is_public", lambda: True)
    saved = {k: getattr(config.settings, k) for k in ("deployment", "supabase_url", "supabase_publishable_key", "supabase_secret_key", "supabase_session_check_ttl", "tick_secret")}
    for key, value in {
        "deployment": "public", "supabase_url": API_URL, "supabase_publishable_key": PUBLISHABLE,
        "supabase_secret_key": SECRET, "supabase_session_check_ttl": 0.0, "tick_secret": "tick-secret-for-tests",
    }.items():
        object.__setattr__(config.settings, key, value)
    monkeypatch.setattr(db_module, "engine", runtime)
    monkeypatch.setattr(deps, "engine", runtime)
    monkeypatch.setattr(main_module, "start_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "stop_scheduler", lambda: None)
    supabase_auth.jwks_cache = supabase_auth.JwksCache(fetch=jwks_fetch)
    supabase_auth.liveness.reset()
    deps._profiles_known.clear()
    from fastapi.testclient import TestClient

    from catch.api.routes_analytics import invalidate_series_cache

    invalidate_series_cache()
    with TestClient(main_module.app) as client:  # the real lifespan: refuses a role that bypasses RLS
        yield client
    for key, value in saved.items():
        object.__setattr__(config.settings, key, value)
    supabase_auth.jwks_cache = supabase_auth.JwksCache()
    supabase_auth.liveness.reset()


def test_a_real_gotrue_token_authenticates_and_the_profile_exists(app):
    u = signup("rt")
    me = app.get("/api/me", headers=u.headers)
    assert me.status_code == 200 and me.json()["id"] == u.id and me.json()["email"] == u.email
    assert app.get("/api/me").status_code == 401
    assert app.get("/api/me", headers={"authorization": f"Bearer {u.access_token}x"}).status_code == 401


def test_two_real_users_with_overlapping_data_are_isolated_through_the_whole_stack(app):
    a, b = signup("rt-a"), signup("rt-b")
    for u, name in ((a, "alice"), (b, "bob")):
        assert app.post("/api/notes", headers=u.headers, json={"date": "2026-11-02", "text": f"{name} note", "rpe": 6}).status_code == 200
        assert app.post("/api/checkins", headers=u.headers, json={"soreness": 1 if name == "alice" else 5}).status_code == 200
        assert app.post("/api/events", headers=u.headers, json={"name": f"{name} race", "date": "2026-12-05", "type": "race"}).status_code == 200
    assert app.get("/api/notes", headers=a.headers, params={"date": "2026-11-02"}).json()["text"] == "alice note"
    assert app.get("/api/notes", headers=b.headers, params={"date": "2026-11-02"}).json()["text"] == "bob note"
    assert app.get("/api/checkins/today", headers=a.headers).json()["checkin"]["soreness"] == 1
    events = lambda u: app.get("/api/events", headers=u.headers, params={"from": "2026-12-01", "to": "2026-12-31"}).json()["events"]
    assert [e["name"] for e in events(a)] == ["alice race"] and [e["name"] for e in events(b)] == ["bob race"]
    foreign = events(a)[0]["id"]
    assert app.get(f"/api/events/{foreign}", headers=b.headers).status_code == 404
    assert app.patch(f"/api/events/{foreign}", headers=b.headers, json={"name": "mine"}).status_code == 404
    assert app.delete(f"/api/events/{foreign}", headers=b.headers).status_code == 404
    assert app.get(f"/api/events/{foreign}", headers=a.headers).status_code == 200


def test_row_level_security_still_protects_when_the_application_filter_is_bypassed(app, runtime):
    """Defence in depth, demonstrated: with the ORM's owner filter switched off (as a bug in a query would),
    Postgres alone still returns only the signed-in user's rows."""
    from catch.core.models import Note

    a, b = signup("did-a"), signup("did-b")
    for u in (a, b):
        app.post("/api/notes", headers=u.headers, json={"date": "2026-11-02", "text": f"note of {u.id}", "rpe": 6})
    with tenant.use_owner(b.id), Session(runtime) as s:
        rows = s.execute(select(Note.text).execution_options(tenant_unscoped=True)).scalars().all()
    assert rows == [f"note of {b.id}"]
    with tenant.use_owner(a.id), Session(runtime) as s:
        # and a write naming the other owner is refused by the policy even if the ORM guard were absent
        s.execute(text("SELECT 1"))
        with pytest.raises(Exception, match="row-level security"):
            s.execute(text("INSERT INTO notes (owner_id, date, text, created_at) VALUES (:o, '2026-11-03', 'x', now())"), {"o": b.id})


def test_every_transaction_gets_the_identity_even_after_a_mid_request_commit(runtime):
    from catch.core.models import Note

    u = signup("commit")
    with tenant.use_owner(u.id), Session(runtime) as s:
        s.add(Note(date=date(2026, 11, 2), text="one"))
        s.commit()  # ends transaction 1
        s.add(Note(date=date(2026, 11, 3), text="two"))
        s.commit()  # transaction 2 must also be authenticated-as-u
        assert s.execute(text("SELECT current_user, auth.uid()::text")).one() == ("authenticated", u.id)
        assert len(s.execute(select(Note)).scalars().all()) == 2


def test_no_owner_means_the_database_is_never_reached_in_public_mode(runtime, monkeypatch):
    monkeypatch.setattr(tenant, "is_public", lambda: True)
    from catch.core.models import Note
    from catch.core.tenant import NoTenantContext

    with Session(runtime) as s:
        with pytest.raises(NoTenantContext):
            s.execute(select(Note)).all()
        with pytest.raises(NoTenantContext):
            s.execute(text("SELECT 1"))  # not even a bare query: the transaction itself can't begin


def test_logging_out_everywhere_ends_the_session_before_the_token_expires(app):
    u = signup("logout")
    assert app.get("/api/me", headers=u.headers).status_code == 200
    signout_everywhere(u)
    assert app.get("/api/me", headers=u.headers).status_code == 401  # same unexpired JWT, session row gone


def test_account_deletion_removes_data_files_sessions_and_the_sign_in_account(app, admin):
    u, other = signup("del"), signup("keep")
    app.post("/api/notes", headers=u.headers, json={"date": "2026-11-02", "text": "mine", "rpe": 5})
    app.post("/api/notes", headers=other.headers, json={"date": "2026-11-02", "text": "theirs", "rpe": 5})
    req = urllib.request.Request(
        f"{API_URL}/storage/v1/object/piece-photos/{u.id}/pic.png", data=b"\x89PNG\r\n\x1a\n" + b"0" * 16, method="POST",
        headers={"apikey": PUBLISHABLE, "authorization": f"Bearer {u.access_token}", "content-type": "image/png"},
    )
    assert urllib.request.urlopen(req, timeout=15).status == 200

    assert app.request("DELETE", "/api/account", headers=u.headers, json={"confirm": "nope"}).status_code == 400
    done = app.request("DELETE", "/api/account", headers=u.headers, json={"confirm": "DELETE"})
    assert done.status_code == 200 and done.json() == {"deleted": True, "files_removed": 1}

    with admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM auth.users WHERE id = :i"), {"i": u.id}).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM catch.user_profiles WHERE id = :i"), {"i": u.id}).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM catch.notes WHERE owner_id = :i"), {"i": u.id}).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM storage.objects WHERE name LIKE :p"), {"p": f"{u.id}/%"}).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM auth.sessions WHERE user_id = :i"), {"i": u.id}).scalar() == 0
    assert app.get("/api/me", headers=u.headers).status_code == 401  # the old, unexpired token is dead
    assert app.get("/api/notes", headers=other.headers, params={"date": "2026-11-02"}).json()["text"] == "theirs"  # others untouched


def test_deleting_the_account_without_files_works_and_is_repeatable_safe(app):
    u = signup("del2")
    assert app.request("DELETE", "/api/account", headers=u.headers, json={"confirm": "DELETE"}).json()["files_removed"] == 0
    assert app.request("DELETE", "/api/account", headers=u.headers, json={"confirm": "DELETE"}).status_code == 401


def test_the_tick_walks_every_user_under_their_own_identity_and_leases_prevent_double_runs(app, monkeypatch):
    from catch.api import routes_internal as ri

    a, b = signup("tick-a"), signup("tick-b")
    seen = []
    monkeypatch.setattr(ri, "_sync_work", lambda: seen.append(tenant.current_owner()))
    tick = lambda secret="tick-secret-for-tests": app.post("/internal/tick/sync", headers={"authorization": f"Bearer {secret}"})
    assert tick("wrong").status_code == 401
    assert app.post("/internal/tick/sync").status_code == 401
    out = tick().json()
    assert out["failed"] == 0 and {a.id, b.id} <= set(seen)
    assert tick().json()["skipped_running"] == 0  # the first tick finished, so a second may run
    from datetime import datetime, timezone

    from catch.core.models import SyncState

    with tenant.use_owner(a.id), Session(app.app.dependency_overrides.get(None) or __import__("catch.core.db", fromlist=["engine"]).engine) as s:
        row = s.get(SyncState, tenant.pk("job:sync"))
        row.last_success_at = None  # a run that never finished
        row.last_attempt_at = datetime.now(timezone.utc)
        s.commit()
    seen.clear()
    assert tick().json()["skipped_running"] >= 1 and a.id not in seen


def test_transaction_pooler_settings_work_end_to_end(clean, migrated):
    """CATCH_DB_POOL_MODE=transaction: no pooling in the app, no prepared statements — the identity is still
    carried per transaction and identical queries repeat cleanly."""
    from catch.core.db_pg import build_pg_engine
    from catch.core.models import Note

    eng = build_pg_engine(runtime_url(), pool_mode="transaction")
    try:
        u = signup("txmode")
        for i in range(8):  # repeated identical statements are what trip server-side prepared statements
            with tenant.use_owner(u.id), Session(eng) as s:
                s.add(Note(date=date(2026, 11, 1 + i), text=f"n{i}"))
                s.commit()
                assert len(s.execute(select(Note)).scalars().all()) == i + 1
    finally:
        eng.dispose()


def test_the_startup_guard_refuses_a_role_that_bypasses_rls(migrated):
    from catch.core import db_pg
    from tests.pg.conftest import admin_url

    privileged = db_pg.build_pg_engine(admin_url())
    try:
        with pytest.raises(RuntimeError, match="bypasses row level security"):
            db_pg.assert_unprivileged(privileged)
    finally:
        privileged.dispose()
    safe = db_pg.build_pg_engine(runtime_url())
    try:
        report = db_pg.assert_unprivileged(safe)
        assert report["role"] == "catch_api" and not report["bypass_rls"]
        assert db_pg.rls_probe(safe) == {"sees_nothing_as_stranger": True, "cannot_write_for_another_user": True}
    finally:
        safe.dispose()


def test_the_database_connection_requires_ssl_for_remote_hosts():
    from catch.core.db_pg import normalize_url

    assert "sslmode=require" in normalize_url("postgresql://u:p@db.abc.supabase.co:5432/postgres")
    assert "sslmode=require" in normalize_url("postgres://u:p@aws-0-us-east-1.pooler.supabase.com:6543/postgres")
    assert "sslmode" not in normalize_url("postgresql://u:p@127.0.0.1:54322/postgres")
    assert "sslmode=verify-full" in normalize_url("postgresql://u:p@db.abc.supabase.co:5432/postgres?sslmode=verify-full")
    assert normalize_url("postgresql://u:p@h/db").startswith("postgresql+psycopg://")
