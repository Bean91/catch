"""The personal (Pi) install after session 24 (docs/public-architecture.md §1): an old SQLite file upgrades in place, nothing
about its login, schema defaults or reads changes, and none of the public stack is loaded.

The legacy schema fixture is `.schema` of a real October-2026 Pi database (tests/fixtures/pi/legacy_schema.sql) — tables
created before owner_id, before canonical activities, before pieces."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

import catch.core.models as models
from catch.core import db as db_module
from catch.core import tenant
from tests.conftest import TEST_PASSWORD

LEGACY = Path(__file__).parent / "fixtures" / "pi" / "legacy_schema.sql"


@pytest.fixture()
def legacy_engine(tmp_path, monkeypatch):
    path = tmp_path / "pi.db"
    con = sqlite3.connect(path)
    con.executescript(LEGACY.read_text())
    con.execute("INSERT INTO daily_wellness (date, source, resting_hr, hrv_rmssd, updated_at) VALUES ('2026-10-01', 'garmin', 49, 66.0, '2026-10-01 06:00:00')")
    con.execute("INSERT INTO daily_wellness (date, source, resting_hr, hrv_rmssd, updated_at) VALUES ('2026-10-02', 'garmin', 50, 61.0, '2026-10-02 06:00:00')")
    con.execute(
        "INSERT INTO activities (source, external_id, type, start, duration, updated_at) "
        "VALUES ('garmin', 'g-1', 'rowing_v2', '2026-10-01 07:00:00', 3600.0, '2026-10-01 08:00:00')"
    )
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(db_module, "engine", eng)
    return eng, path


def test_an_old_database_upgrades_in_place_keeping_every_row(legacy_engine):
    eng, path = legacy_engine
    assert "owner_id" not in {c["name"] for c in inspect(eng).get_columns("daily_wellness")}
    db_module.init_db()
    db_module.init_db()  # a second startup is a no-op
    cols = {t: {c["name"] for c in inspect(eng).get_columns(t)} for t in inspect(eng).get_table_names()}
    for table in SQLModel.metadata.tables:
        if table in ("weather_cells", "user_profiles"):
            continue
        assert "owner_id" in cols[table], table
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*), min(owner_id), max(owner_id) FROM daily_wellness")).one() == (2, "owner", "owner")
        assert conn.execute(text("SELECT owner_id FROM activities")).scalar() == "owner"
        assert conn.execute(text("SELECT id, display_name FROM user_profiles")).all() == [("owner", "You")]
        # reference tables stay NULL = global
        assert conn.execute(text("SELECT count(*) FROM exercises WHERE owner_id IS NOT NULL")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM exercises")).scalar() > 600


def test_the_upgraded_database_reads_and_writes_as_the_one_owner(legacy_engine):
    eng, _ = legacy_engine
    db_module.init_db()
    from catch.core.models import Activity, DailyWellness
    from catch.sync.scoring import recompute_scores
    from catch.sync.upsert import upsert_daily_wellness

    with Session(eng) as s:
        assert s.get(DailyWellness, tenant.pk(date(2026, 10, 1))).resting_hr == 49
        assert len(s.exec(select(Activity)).all()) == 1
        upsert_daily_wellness(s, date(2026, 10, 3), resting_hr=48)
        row = s.exec(select(DailyWellness).where(DailyWellness.resting_hr == 48)).one()
        assert row.owner_id == "owner"
        recompute_scores(s)  # the scoring pipeline runs end to end on the upgraded file


def test_cookie_login_still_guards_the_api_and_there_is_no_public_surface(legacy_engine, monkeypatch):
    eng, _ = legacy_engine
    db_module.init_db()
    import catch.main as main_module
    from fastapi.testclient import TestClient

    from catch.api.deps import get_db

    monkeypatch.setattr(main_module, "start_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "stop_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    def session_dep():
        with Session(eng) as s:
            yield s

    from argon2 import PasswordHasher
    import dataclasses

    from catch.core import security
    from catch.core.config import settings

    monkeypatch.setattr(security, "settings", dataclasses.replace(settings, password_hash=PasswordHasher().hash(TEST_PASSWORD)))
    main_module.app.dependency_overrides[get_db] = session_dep
    try:
        with TestClient(main_module.app) as c:
            assert c.get("/api/activities").status_code == 401
            assert c.post("/api/login", json={"password": "wrong"}).status_code == 401
            assert c.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 200
            assert len(c.get("/api/activities").json()["items"]) >= 0
            assert c.get("/api/wellness?from=2026-10-01&to=2026-10-02").json()[0]["resting_hr"] == 49
            # the public-only surfaces say no on a personal install
            assert c.get("/internal/db-check").status_code == 404
            assert c.post("/internal/tick/sync").status_code == 404
            assert c.request("DELETE", "/api/account", json={"confirm": "DELETE"}).status_code == 404
            # a bearer JWT is not an accepted credential here
            c.cookies.clear()
            assert c.get("/api/activities", headers={"authorization": "Bearer a.b.c"}).status_code == 401
    finally:
        main_module.app.dependency_overrides.clear()


def test_a_fresh_personal_database_has_the_full_per_owner_keys(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(db_module, "engine", eng)
    db_module.init_db()
    pk = set(inspect(eng).get_pk_constraint("daily_wellness")["constrained_columns"])
    assert pk == {"owner_id", "date"}
    assert models.UserProfile.__tablename__ in inspect(eng).get_table_names()
