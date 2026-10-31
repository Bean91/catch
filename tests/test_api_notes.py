from __future__ import annotations

from datetime import date, datetime, timezone

from sqlmodel import select

from catch.core.models import Note
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_get_note_returns_none_when_missing(client):
    _login(client)
    resp = client.get("/api/notes", params={"date": "2026-01-01"})
    assert resp.status_code == 200
    assert resp.json() is None


def test_post_note_creates_and_get_returns_it(client):
    _login(client)
    resp = client.post("/api/notes", json={"date": "2026-01-01", "text": "felt strong", "rpe": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "felt strong"
    assert body["rpe"] == 7

    resp2 = client.get("/api/notes", params={"date": "2026-01-01"})
    assert resp2.json()["text"] == "felt strong"


def test_post_note_upserts_same_date(client, session):
    _login(client)
    client.post("/api/notes", json={"date": "2026-01-01", "text": "first", "rpe": 3})
    client.post("/api/notes", json={"date": "2026-01-01", "text": "revised", "rpe": 5})

    assert len(session.exec(select(Note)).all()) == 1
    resp = client.get("/api/notes", params={"date": "2026-01-01"})
    body = resp.json()
    assert body["text"] == "revised"
    assert body["rpe"] == 5


def test_post_note_rejects_out_of_range_rpe(client):
    _login(client)
    resp = client.post("/api/notes", json={"date": "2026-01-01", "text": "x", "rpe": 11})
    assert resp.status_code == 422


def test_notes_require_auth(client):
    resp = client.get("/api/notes", params={"date": "2026-01-01"})
    assert resp.status_code == 401


def test_post_note_triggers_recompute_affecting_strain(client, session):
    from catch.core.models import Activity

    today = date.today()
    session.add(
        Activity(
            source="garmin",
            external_id="g1",
            type="strength_training",
            start=datetime.now(timezone.utc),
            duration=3600.0,
        )
    )
    session.commit()

    _login(client)
    client.post("/api/notes", json={"date": today.isoformat(), "text": "hard session", "rpe": 8})

    resp = client.get("/api/today")
    assert resp.json()["strain_today"]["value"] is not None
