from __future__ import annotations

from conftest import TEST_PASSWORD


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
    assert sources == {"garmin", "withings", "concept2", "whoop"}


def test_activities_from_to_accepts_naive_dates(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})
    resp = client.get("/api/activities", params={"from": "2026-01-01", "to": "2026-12-31"})
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}


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
