from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

FIXTURE_DIR = Path(__file__).parent / "fixtures"


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
