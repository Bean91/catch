from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_PASSWORD = "correct-horse-battery-staple"


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
    """`search_foods` falls through to Open Food Facts' free-text search
    (`OpenFoodFactsClient.search`) whenever local+USDA haven't filled the page — unlike
    barcode lookup (which every test exercising it already monkeypatches per-test), nothing
    guards this path, so a query with few/no local or USDA results (e.g. "nonexistent xyz
    food") would make a real live call. Patched on the class itself, the same object every
    `OpenFoodFactsClient()` instance shares — a test that wants to exercise a real OFF search
    hit monkeypatches `OpenFoodFactsClient.search` again itself, the same override pattern
    already used for its barcode-lookup sibling."""
    from catch.sync.openfoodfacts_client import OpenFoodFactsClient

    monkeypatch.setattr(OpenFoodFactsClient, "search", lambda self, query, page_size=10: [])


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
