from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_PASSWORD = "correct-horse-battery-staple"

# Session 16: blanked once, here, directly on the one shared `Settings` singleton every
# module's `from catch.core.config import settings` already points to (bypassing the frozen
# dataclass's own `__setattr__` — `monkeypatch.setattr` would still hit that same guard) —
# so every module sees the change, not just whichever one a test happens to import by name.
# Scoped to the fields this session added, which a real `.env`/`catch.env` now plausibly has
# non-empty values for (VAPID keys, an ntfy topic, healthchecks URLs): without this, whether
# catch.notify.push/ntfy/healthchecks attempt a real network call in a test that never
# touches them on purpose depends on whose laptop or CI runner the suite happens to run on —
# exactly the class of hidden-environment dependency that made 17 Fernet-dependent tests here
# pass locally and fail in CI (see `_fernet_key_always_set` below) before this fixture existed.
from catch.core.config import settings as _real_settings  # noqa: E402

object.__setattr__(_real_settings, "ollama_enabled", True)
for _field in ("secrets_master_key_previous", "whoop_client_id", "whoop_client_secret", "whoop_redirect_uri"):
    object.__setattr__(_real_settings, _field, "")
# A fixed, test-only master key: never the ambient .env's CATCH_FERNET_KEY, so credential tests
# are deterministic on a laptop with a real .env and in CI without one.
object.__setattr__(_real_settings, "secrets_master_key", "test-master-key-not-a-real-secret-0123456789")

for _field in ("vapid_private_key", "vapid_public_key", "ntfy_topic", "healthchecks_sync_url", "healthchecks_backup_url"):
    object.__setattr__(_real_settings, _field, "")


class _LiveNetworkCallError(Exception):
    """Deliberately NOT an `httpx.HTTPError` subclass — every external-API client in this app
    (openfoodfacts_client.py, usda_client.py, and the Garmin/Withings/Concept2 clients) catches
    `httpx.HTTPError` and fails open (returns None/[]), which is exactly how the two live-call
    leaks this session already found (USDA, then OFF search) hid behind a passing-looking test:
    a real call that errored out, or returned real data loose enough to satisfy the assertions,
    was silently swallowed by that same handling. Raising something `httpx.HTTPError` can't
    catch turns a leak on one of *those* paths into a hard test failure instead of quiet
    non-determinism.

    Not a universal guarantee, though — `catch/sync/scheduler.py` and `catch/coach/chat.py`
    both have their own broader `except Exception` around a sync/tool call (by design: one
    source's sync failure, or one tool call's error, shouldn't crash the whole run), which
    would catch this too and turn a leak there into a recorded error/tool-result rather than a
    failing test. The Anthropic SDK also wraps a transport-level failure into its own
    `APIConnectionError` (an `APIError` subclass), which `nutrition_vision.py` already catches
    deliberately — not a live risk today, since its tests replace the whole `anthropic` module
    in `sys.modules` rather than reaching real httpx at all, but worth knowing if that ever
    changes. This guard is a floor for the two paths it's already caught leaking on, not proof
    that every code path is covered."""


def _raise_live_call(*args, **kwargs):
    raise _LiveNetworkCallError("A test attempted a real network call via httpx's default HTTPTransport — every external call in this suite must go through httpx.MockTransport (see CLAUDE.md's 'no live network calls' rule).")


@pytest.fixture(autouse=True)
def _no_live_network_calls_anywhere(monkeypatch):
    """A structural backstop, not a replacement for the path-specific fixtures below — those
    still set sensible defaults (e.g. no USDA key) so most tests never even reach this guard.
    Patches the transport classes actually used for real outbound HTTP (`HTTPTransport`/
    `AsyncHTTPTransport`, httpx's defaults when a `Client()` is constructed with no explicit
    `transport=`), never `httpx.MockTransport` (fixture-driven tests) or the ASGI transport
    `TestClient` uses internally (a different class entirely) — so this can't interfere with
    either of this suite's two legitimate uses of httpx."""
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _raise_live_call)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _raise_live_call)


@pytest.fixture()
def engine():
    # StaticPool: TestClient dispatches requests on a worker thread, and sqlite's default
    # per-thread pooling for "sqlite://" would otherwise hand that thread a fresh, separate
    # in-memory database with none of our tables in it.
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def _fernet_key_always_set(monkeypatch):
    """`catch.core.security._fernet` is built once at import time from the real `.env`'s
    `CATCH_FERNET_KEY` — on a laptop that already has a real `.env`, every test calling
    `security.encrypt`/`decrypt` (OAuth token storage, the coach's Anthropic key) silently
    rides on that real key and passes. CI has no `.env` at all (by design — this suite must
    run on fixtures only), which turned that hidden dependency into 17 real failures the first
    time this suite ran there (`RuntimeError: CATCH_FERNET_KEY is not set`) despite passing
    locally. A fixed, test-only key makes every test deterministic regardless of the ambient
    environment, local or CI."""
    from cryptography.fernet import Fernet

    from catch.core import security

    monkeypatch.setattr(security, "_fernet", Fernet(Fernet.generate_key()))


@pytest.fixture(autouse=True)
def _fresh_ai_limits():
    """The AI rate limiter is process-global in-memory state; reset it so one test's requests
    never count against the next."""
    from catch.coach import limits

    limits.reset()
    yield
    limits.reset()


@pytest.fixture(autouse=True)
def _no_live_usda_calls(monkeypatch):
    """The real `.env` this suite runs against may have a real `USDA_FDC_API_KEY` set —
    without this, any test that reaches `catch.sync.nutrition.search_foods`/
    `lookup_or_fetch_barcode` without its own explicit monkeypatch would make live network
    calls to the USDA API, violating "no live network calls in the suite" (CLAUDE.md) and
    making those tests non-deterministic. Tests that specifically want to exercise the USDA
    fallback path override `catch.sync.nutrition.app_settings` themselves (see
    tests/test_api_nutrition.py)."""
    import catch.sync.nutrition as nutrition_module

    monkeypatch.setattr(nutrition_module, "app_settings", dataclasses.replace(nutrition_module.app_settings, usda_fdc_api_key=""))


@pytest.fixture(autouse=True)
def _no_live_off_search_calls(monkeypatch):
    """`search_foods`'s OFF free-text search is opt-in (`include_off=True`) — the plain
    debounced search box never reaches it, but the coach's `log_food` tool always passes
    `include_off=True` (one call per tool use, not as-you-type — see
    `catch/sync/nutrition.py::search_foods`'s docstring), so any coach-tool test exercising
    `log_food` by description, or a route test passing `include_off=true` explicitly, would
    still make a real live call without this. Patched on the class itself, the same object
    every `OpenFoodFactsClient()` instance shares — a test that wants to exercise a real OFF
    search hit monkeypatches `OpenFoodFactsClient.search` again itself, the same override
    pattern already used for its barcode-lookup sibling."""
    from catch.sync.openfoodfacts_client import OpenFoodFactsClient

    monkeypatch.setattr(OpenFoodFactsClient, "search", lambda self, query, page_size=10: [])


@pytest.fixture(autouse=True)
def _no_live_weather_calls(monkeypatch):
    """Weather enrichment runs from the sync path and the track endpoints; without this, any
    test reaching it would hit the live-network guard above (a non-httpx exception). A test that
    exercises the client builds one over an httpx.MockTransport; a test of the DB layer passes a
    fake client explicitly."""
    from catch.sync.weather_client import OpenMeteoClient

    monkeypatch.setattr(OpenMeteoClient, "fetch_day", lambda self, lat_e1, lon_e1, day: None)


def load_fixture(*parts: str) -> dict | list:
    return json.loads((FIXTURE_DIR.joinpath(*parts)).read_text())


@pytest.fixture()
def client(session, monkeypatch):
    import catch.main as main_module
    from catch.api.deps import get_db
    from catch.core import security
    from catch.core.config import settings as real_settings

    monkeypatch.setattr(main_module, "start_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "stop_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    hashed = PasswordHasher().hash(TEST_PASSWORD)
    monkeypatch.setattr(security, "settings", dataclasses.replace(real_settings, password_hash=hashed))

    # GET /api/series caches each metric's full history in a module-level dict (session 8,
    # catch/api/routes_analytics.py) — cleared per-test so one test's cached series can't leak
    # into the next test's fresh in-memory engine.
    from catch.api.routes_analytics import invalidate_series_cache

    invalidate_series_cache()

    main_module.app.dependency_overrides[get_db] = lambda: session
    with TestClient(main_module.app) as c:
        yield c
    main_module.app.dependency_overrides.clear()
