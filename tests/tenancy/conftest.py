from __future__ import annotations

import pytest
from sqlmodel import Session

import catch.main  # noqa: F401  (import under the personal default; the SQLite engine is built at import)
from catch.core import config, supabase_auth, tenant
from tests.tenancy import kit


@pytest.fixture()
def public(monkeypatch):
    """Flip the process to a public deployment for one test (SQLite underneath; the Postgres/RLS half has its own
    tests). Cookie login is off, there is no default owner, and the JWT path is wired to a local ES256 key."""
    monkeypatch.setattr(tenant, "is_public", lambda: True)
    previous = {k: getattr(config.settings, k) for k in ("deployment", "supabase_url", "supabase_session_check_ttl", "tick_secret")}
    object.__setattr__(config.settings, "deployment", "public")
    object.__setattr__(config.settings, "supabase_url", kit.SUPABASE_URL)
    object.__setattr__(config.settings, "supabase_session_check_ttl", 0.0)
    object.__setattr__(config.settings, "tick_secret", "tick-secret-for-tests")
    supabase_auth.jwks_cache = supabase_auth.JwksCache(fetch=kit.jwks)
    supabase_auth.liveness.reset()
    from catch.api import deps

    deps._profiles_known.clear()
    yield
    for k, v in previous.items():
        object.__setattr__(config.settings, k, v)
    supabase_auth.jwks_cache = supabase_auth.JwksCache()
    supabase_auth.liveness.reset()


@pytest.fixture()
def pub_engine(engine, monkeypatch):
    """The conftest SQLite engine, also installed as the process engine so code that opens its own session
    (profile bootstrap, session liveness, the scheduler) never touches data/catch.db."""
    from catch.api import deps
    from catch.core import db as db_module

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(deps, "engine", engine)
    return engine


@pytest.fixture()
def pub_client(public, pub_engine, monkeypatch):
    """A client for the public deployment where every request gets its own Session — as in production, so the
    identity map never carries one user's objects into another user's request."""
    import catch.main as main_module
    from fastapi.testclient import TestClient
    from catch.api.deps import get_db

    monkeypatch.setattr(main_module, "start_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "stop_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "_check_public_runtime", lambda: None)

    def per_request_session():
        with Session(pub_engine) as s:
            yield s

    from catch.api.routes_analytics import invalidate_series_cache

    invalidate_series_cache()
    main_module.app.dependency_overrides[get_db] = per_request_session
    with TestClient(main_module.app) as c:
        yield c
    main_module.app.dependency_overrides.clear()


def bearer(sub: str, **kw) -> dict:
    return {"authorization": f"Bearer {kit.mint(sub, **kw)}"}
