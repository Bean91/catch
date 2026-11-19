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
    API_URL, PUBLISHABLE, SECRET, jwks_fetch, runtime_url, signout_everywhere, signup,
)

pytestmark = pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")


@pytest.fixture()
def app(clean, runtime, monkeypatch):
    import catch.main as main_module
    from catch.api import deps
    from catch.core import db as db_module

    monkeypatch.setattr(tenant, "is_public", lambda: True)
    monkeypatch.setenv("CATCH_ALLOW_LOCAL_BASE_URL", "1")  # the local stack is http://localhost; the base-URL rule has its own tests
    saved = {k: getattr(config.settings, k) for k in ("deployment", "supabase_url", "supabase_publishable_key", "supabase_secret_key", "supabase_session_check_ttl", "tick_secret", "ollama_enabled")}
    for key, value in {
        "deployment": "public", "supabase_url": API_URL, "supabase_publishable_key": PUBLISHABLE,
        "supabase_secret_key": SECRET, "supabase_session_check_ttl": 0.0, "tick_secret": "tick-secret-for-tests-0123456789abcdefg", "ollama_enabled": False,
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
    def events(u):
        return app.get("/api/events", headers=u.headers, params={"from": "2026-12-01", "to": "2026-12-31"}).json()["events"]
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
    def tick(secret="tick-secret-for-tests-0123456789abcdefg"):
        return app.post("/internal/tick/sync", headers={"authorization": f"Bearer {secret}"})
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


def test_a_coach_turn_runs_for_two_real_users_and_holds_no_transaction_while_the_model_streams(app, admin):
    """The whole turn on the real runtime path (SSE, tool loop, memory block, stored messages) — and, while the provider is stalled
    mid-stream, no database session of the app is 'idle in transaction'."""
    import threading

    from catch.coach.providers import registry

    entered, release = threading.Event(), threading.Event()

    class Slow:
        name = "openai"

        async def health_check(self):
            return True

        async def stream_turn(self, *, system_blocks, messages, model):
            last = messages[-1]["blocks"]
            if any(b["type"] == "tool_result" for b in last):
                output = next(b["output"] for b in last if b["type"] == "tool_result")
                yield {"type": "text_delta", "text": "I see: " + json.dumps(output, default=str)}
                yield {"type": "usage", "usage": {"input_tokens": 10, "output_tokens": 2, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}
                yield {"type": "stop", "stop_reason": "end_turn"}
            else:
                entered.set()
                while not release.is_set():  # stalled mid-stream
                    import asyncio

                    await asyncio.sleep(0.05)
                yield {"type": "tool_call", "id": "c1", "name": "recall", "input": {"query": ""}}
                yield {"type": "stop", "stop_reason": "tool_use"}

    real_build = registry.build_provider
    registry.build_provider = lambda s, o, p: Slow()
    try:
        from catch.coach.providers import anthropic_provider, gemini_provider, openai_provider

        async def valid(self):
            return {"ok": True, "kind": None, "message": "Connected", "model_count": 1}

        for cls in (openai_provider.OpenAIProvider, gemini_provider.GeminiProvider, anthropic_provider.AnthropicProvider):
            cls.validate = valid
        a, b = signup("coach-a"), signup("coach-b")
        for u, fact in ((a, "ALICE-FACT"), (b, "BOB-FACT")):
            app.put("/api/ai/providers/openai/key", headers=u.headers, json={"api_key": "sk-proj-" + "k" * 30})
            app.put("/api/ai/active", headers=u.headers, json={"provider": "openai", "model": "gpt-x"})
            assert app.post("/api/coach/tools/remember", headers=u.headers, json={"args": {"category": "preference", "text": fact, "confirm": True}}).status_code == 200
        conv = app.post("/api/coach/conversations", headers=a.headers).json()
        out: dict = {}

        def run():
            with app.stream("POST", f"/api/coach/conversations/{conv['id']}/messages", headers=a.headers, json={"text": "hi"}) as resp:
                out["body"] = "".join(resp.iter_text())

        t = threading.Thread(target=run)
        t.start()
        assert entered.wait(15), "the provider was never reached"
        with admin.connect() as conn:
            states = conn.execute(text("SELECT state FROM pg_stat_activity WHERE usename = 'catch_api'")).scalars().all()
            conn.rollback()
        assert "idle in transaction" not in states, states  # nothing pinned while the model "thinks"
        release.set()
        t.join(30)
        assert "ALICE-FACT" in out["body"] and "BOB-FACT" not in out["body"]
        assert app.get(f"/api/coach/conversations/{conv['id']}", headers=b.headers).status_code == 404
    finally:
        registry.build_provider = real_build


def test_a_token_cannot_bring_a_deleted_account_back_even_while_another_replica_still_trusts_its_session(app, admin, monkeypatch):
    """The 15 s liveness cache is the window: a replica that cached "session alive" before the deletion keeps accepting the
    token. Production TTL here, not the suite's 0.0 — the tombstone is what stops the profile being re-created."""
    import time

    from catch.api import deps

    object.__setattr__(config.settings, "supabase_session_check_ttl", 15.0)
    u = signup("resurrect")
    assert app.get("/api/me", headers=u.headers).status_code == 200
    claims = supabase_auth.verify_access_token(u.access_token)
    assert app.request("DELETE", "/api/account", headers=u.headers, json={"confirm": "DELETE"}).status_code == 200
    # Another replica: it cached "alive" before the deletion and has no profile cached.
    supabase_auth.liveness.reset()
    supabase_auth.liveness._alive[claims.session_id] = time.monotonic()
    deps._profiles_known.clear()
    assert app.get("/api/me", headers=u.headers).status_code == 401
    with admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM catch.user_profiles WHERE id = :i"), {"i": u.id}).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM catch.deleted_accounts WHERE user_id = :i"), {"i": u.id}).scalar() == 1


def test_an_old_sign_in_cannot_delete_the_account_but_a_fresh_one_can(app, admin):
    """Real GoTrue tokens: `amr[].timestamp` is the sign-in moment and survives a refresh; `iat` does not."""
    import base64

    u = signup("stepup")
    refreshed = _refresh(u)
    payload = json.loads(base64.urlsafe_b64decode(refreshed.split(".")[1] + "=="))
    assert payload["amr"][0]["timestamp"] <= payload["iat"]
    # Age the sign-in: the suite can't wait ten minutes, so shrink the window instead of faking a token.
    from catch.api import routes_account

    original = routes_account.RECENT_SIGN_IN_SECONDS
    try:
        routes_account.RECENT_SIGN_IN_SECONDS = -1
        denied = app.request("DELETE", "/api/account", headers={"authorization": f"Bearer {refreshed}"}, json={"confirm": "DELETE"})
        assert denied.status_code == 403 and denied.json()["detail"] == "reauth_required"
    finally:
        routes_account.RECENT_SIGN_IN_SECONDS = original
    assert app.request("DELETE", "/api/account", headers={"authorization": f"Bearer {refreshed}"}, json={"confirm": "DELETE"}).status_code == 200


def _refresh(user) -> str:
    from tests.pg.conftest import _post

    return _post("/auth/v1/token?grant_type=refresh_token", {"refresh_token": user.refresh_token})["access_token"]


def test_the_runtime_role_reports_the_applied_schema_revision(migrated):
    from catch.core import db_pg

    eng = db_pg.build_pg_engine(runtime_url())
    try:
        report = db_pg.schema_revision(eng)
    finally:
        eng.dispose()
    assert report["schema_expected"] == db_pg.EXPECTED_SCHEMA_REVISION
    # None = the role can't read the version table (reported as unknown, never as a failure); otherwise it must be the head.
    assert report["schema_revision"] in (None, db_pg.EXPECTED_SCHEMA_REVISION)
    assert report["schema_current"] in (None, True)


def test_every_transaction_carries_a_statement_timeout_and_a_connect_timeout(migrated):
    from catch.core import db_pg, tenant_hooks

    eng = db_pg.build_pg_engine(runtime_url())
    try:
        u = signup("stmt-timeout")
        with tenant.use_owner(u.id), Session(eng) as s:
            assert s.execute(text("SELECT current_setting('statement_timeout')")).scalar() == "1min"
        with tenant.system_detached(), Session(eng) as s:
            assert s.execute(text("SELECT current_setting('statement_timeout')")).scalar() == "1min"
        assert tenant_hooks.STATEMENT_TIMEOUT_MS == "60000"
    finally:
        eng.dispose()


def test_a_burst_of_concurrent_requests_through_the_small_pool_never_exhausts_connections(migrated):
    """The deployed pool is 1 + 2 overflow per replica. 40 threads x 5 transactions must all finish (waiting for a slot, not
    failing) and leave no connection checked out or idle in a transaction afterwards."""
    from concurrent.futures import ThreadPoolExecutor

    from catch.core import db_pg
    from catch.core.models import Note

    eng = db_pg.build_pg_engine(runtime_url(), pool_size=1)
    try:
        users = [signup(f"burst-{i}") for i in range(4)]

        def work(i: int) -> int:
            u = users[i % len(users)]
            seen = 0
            for k in range(5):
                with tenant.use_owner(u.id), Session(eng) as s:
                    s.add(Note(date=date(2026, 11, 1 + k), text=f"{i}:{k}"))
                    s.commit()
                    seen += len(s.execute(select(Note)).scalars().all()) > 0
            return seen

        with ThreadPoolExecutor(max_workers=40) as pool:
            assert sum(pool.map(work, range(40))) == 200
        assert eng.pool.checkedout() == 0
        with eng.connect() as conn:
            idle = conn.execute(text("SELECT count(*) FROM pg_stat_activity WHERE usename = 'catch_api' AND state = 'idle in transaction'")).scalar()
            conn.rollback()
        assert idle == 0
    finally:
        eng.dispose()
