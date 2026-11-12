"""Real Supabase tests (session 24): migrations, RLS with separate identities, the FastAPI runtime path, GoTrue,
Storage. They need a THROWAWAY local Supabase stack — `supabase start` in an empty directory — and are skipped
unless these are set (values printed by `supabase status -o env`):

    CATCH_TEST_SUPABASE_DB_URL   admin URL, e.g. postgresql://postgres:postgres@127.0.0.1:54322/postgres
    CATCH_TEST_SUPABASE_URL      http://127.0.0.1:54321
    CATCH_TEST_SUPABASE_PUBLISHABLE_KEY / CATCH_TEST_SUPABASE_SECRET_KEY

They DROP and recreate the `catch` schema, so they refuse to run against anything but localhost. Never point them
at a hosted project."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import create_engine, text

DB_URL = os.environ.get("CATCH_TEST_SUPABASE_DB_URL", "")
API_URL = os.environ.get("CATCH_TEST_SUPABASE_URL", "").rstrip("/")
PUBLISHABLE = os.environ.get("CATCH_TEST_SUPABASE_PUBLISHABLE_KEY", "")
SECRET = os.environ.get("CATCH_TEST_SUPABASE_SECRET_KEY", "")
ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PASSWORD = "catch-api-test-only"
# Captured before the suite's autouse fixture replaces it: these tests talk to a local stack on purpose.
REAL_HTTP = httpx.HTTPTransport.handle_request

pytestmark = pytest.mark.skipif(not (DB_URL and API_URL), reason="CATCH_TEST_SUPABASE_* not set (needs a local Supabase stack)")


def _local(url: str) -> bool:
    return (urlsplit(url).hostname or "") in ("localhost", "127.0.0.1", "::1")


@pytest.fixture(autouse=True)
def _allow_the_local_stack(monkeypatch):
    if not (DB_URL and API_URL):
        return
    assert _local(DB_URL) and _local(API_URL), "refusing to run Supabase tests against a non-local project"
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", REAL_HTTP)


def admin_url() -> str:
    return DB_URL


def runtime_url() -> str:
    parts = urlsplit(DB_URL)
    return f"postgresql://catch_api:{RUNTIME_PASSWORD}@{parts.hostname}:{parts.port}{parts.path}"


def run_alembic(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_ADMIN_URL": DB_URL}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True)


def reset_schema(admin) -> None:
    with admin.begin() as conn:
        conn.execute(text("DROP TRIGGER IF EXISTS catch_on_auth_user_created ON auth.users"))
        conn.execute(text("DROP TRIGGER IF EXISTS catch_on_auth_user_deleted ON auth.users"))
        conn.execute(text("DROP SCHEMA IF EXISTS catch CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS catch_private CASCADE"))
        for cmd in ("select", "insert", "update", "delete"):
            conn.execute(text(f"DROP POLICY IF EXISTS catch_piece_photos_{cmd} ON storage.objects"))


@pytest.fixture(scope="session")
def admin():
    eng = create_engine(admin_url().replace("postgresql://", "postgresql+psycopg://"))
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def migrated(admin):
    reset_schema(admin)
    done = run_alembic("upgrade", "head")
    assert done.returncode == 0, done.stderr[-1500:]
    with admin.begin() as conn:
        conn.execute(text(f"ALTER ROLE catch_api PASSWORD '{RUNTIME_PASSWORD}'"))
    return True


@pytest.fixture()
def clean(migrated, admin):
    """Empty tables between tests (users are deleted through auth, so the cascade is exercised too)."""
    yield
    with admin.begin() as conn:
        conn.execute(text("TRUNCATE catch.user_profiles CASCADE"))
        conn.execute(text("DELETE FROM catch.weather_cells"))
        conn.execute(text("DELETE FROM catch.exercises WHERE owner_id IS NULL"))


@pytest.fixture(scope="session")
def runtime(migrated):
    from catch.core.db_pg import build_pg_engine

    eng = build_pg_engine(runtime_url())
    yield eng
    eng.dispose()


# --- GoTrue helpers (urllib: independent of the app's httpx and of the live-call guard) -----------------------------


def _post(path: str, body: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API_URL}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"apikey": PUBLISHABLE, "content-type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


class User:
    def __init__(self, data: dict, password: str):
        self.id = data["user"]["id"]
        self.email = data["user"]["email"]
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.password = password

    @property
    def headers(self) -> dict:
        return {"authorization": f"Bearer {self.access_token}"}


def signup(name: str = "u") -> User:
    password = "correct-horse-battery-staple"
    email = f"{name}-{uuid.uuid4().hex[:10]}@example.com"
    return User(_post("/auth/v1/signup", {"email": email, "password": password}), password)


def signout_everywhere(user: User) -> None:
    _post("/auth/v1/logout?scope=global", {}, {"authorization": f"Bearer {user.access_token}"})


def jwks_fetch():
    with urllib.request.urlopen(f"{API_URL}/auth/v1/.well-known/jwks.json", timeout=10) as resp:
        return json.loads(resp.read())
