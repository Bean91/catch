from __future__ import annotations

import dataclasses

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

import catch.main as main_module
from catch.api.deps import get_db
from catch.core import security
from catch.core.config import settings as real_settings

TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture()
def client(session, monkeypatch):
    monkeypatch.setattr(main_module, "start_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "stop_scheduler", lambda: None)
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    hashed = PasswordHasher().hash(TEST_PASSWORD)
    monkeypatch.setattr(security, "settings", dataclasses.replace(real_settings, password_hash=hashed))

    main_module.app.dependency_overrides[get_db] = lambda: session
    with TestClient(main_module.app) as c:
        yield c
    main_module.app.dependency_overrides.clear()


def test_health_is_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_wellness_requires_auth(client):
    resp = client.get("/api/wellness")
    assert resp.status_code == 401


def test_login_wrong_password_rejected(client):
    resp = client.post("/api/login", json={"password": "nope"})
    assert resp.status_code == 401


def test_login_then_read_wellness(client):
    resp = client.post("/api/login", json={"password": TEST_PASSWORD})
    assert resp.status_code == 200
    assert "catch_session" in resp.cookies

    resp2 = client.get("/api/wellness")
    assert resp2.status_code == 200
    assert resp2.json() == []


def test_sync_status_lists_both_sources(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})
    resp = client.get("/api/sync/status")
    assert resp.status_code == 200
    sources = {row["source"] for row in resp.json()}
    assert sources == {"garmin", "withings"}


def test_activities_from_to_accepts_naive_dates(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})
    resp = client.get("/api/activities", params={"from": "2026-01-01", "to": "2026-12-31"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_body_from_to_accepts_naive_dates(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})
    resp = client.get("/api/body", params={"from": "2026-01-01", "to": "2026-12-31"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_logout_clears_session(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})
    client.post("/api/logout")
    resp = client.get("/api/wellness")
    assert resp.status_code == 401
