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

    main_module.app.dependency_overrides[get_db] = lambda: session
    with TestClient(main_module.app) as c:
        yield c
    main_module.app.dependency_overrides.clear()
