"""Session 36: training-block progress, block categories and the monthly calendar summary."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from catch.core import localtime
from catch.core.models import Activity, UserProfile
from catch.sync import planning as sp
from catch.sync.matching import run_matching
from conftest import TEST_PASSWORD

OWNER = sp.OWNER_ID


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _row(session, ext: str, start: datetime, minutes: float, distance: float | None = None, exclude=False):
    a = Activity(source="garmin", external_id=ext, type="indoor_rowing", start=start, duration=minutes * 60, distance=distance)
    session.add(a)
    session.commit()
    run_matching(session)
    session.refresh(a)
    if exclude:
        import json

        from catch.core.models import CanonicalActivity

        c = session.get(CanonicalActivity, a.canonical_id)
        c.overrides_json = json.dumps({"exclude_from_totals": True})
        session.add(c)
        session.commit()
    return a


def test_month_summary_uses_local_days_and_never_counts_plans(session):
    session.add(UserProfile(id=OWNER, timezone="Asia/Tokyo", follow_device_zone=False))
    session.commit()
    localtime.invalidate(session)
    # 20:00 UTC on 31 Oct is 05:00 on 1 Nov in Tokyo: it belongs to November.
    _row(session, "m1", datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc), 60, 12000)
    _row(session, "m2", datetime(2026, 11, 2, 1, 0, tzinfo=timezone.utc), 30, 6000)
    _row(session, "m3", datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc), 45, 9000, exclude=True)
    sp.create_planned(session, OWNER, {"date": date(2026, 11, 5), "session_type": "erg", "duration_min": 90})

    nov = sp.month_summary(session, OWNER, 2026, 11)
    oct_ = sp.month_summary(session, OWNER, 2026, 10)
    assert nov["completed"]["sessions"] == 2 and nov["completed"]["minutes"] == pytest.approx(90)
    assert nov["completed"]["distance_m"] == pytest.approx(18000)
    assert nov["completed"]["training_days"] == 2
    assert nov["planned"]["minutes"] == pytest.approx(90)  # the plan is only ever on the planned side
    assert oct_["completed"]["sessions"] == 0


def test_month_summary_route_validates_the_month(client, session):
    _login(client)
    assert client.get("/api/calendar/month-summary", params={"month": "2026-13"}).status_code == 422
    assert client.get("/api/calendar/month-summary", params={"month": "2026-11"}).status_code == 200


def test_phase_progress_week_by_week(client, session):
    _login(client)
    today = localtime.today(session)
    monday = today - timedelta(days=today.weekday())
    start, end = monday - timedelta(weeks=1), monday + timedelta(weeks=1, days=6)
    phase = client.post("/api/phases", json={
        "kind": "specific_prep", "name": "Build", "category": "Build", "start_date": start.isoformat(), "end_date": end.isoformat(),
        "target_minutes_per_week": 300,
    }).json()
    assert phase["category"] == "Build"
    _row(session, "p1", datetime.combine(start + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=12), 60, 15000)
    client.post("/api/planned", json={"date": (monday + timedelta(weeks=1)).isoformat(), "session_type": "erg", "duration_min": 80})

    prog = client.get(f"/api/phases/{phase['id']}/progress").json()
    assert [w["state"] for w in prog["weeks"]] == ["past", "current", "future"]
    assert prog["weeks"][0]["completed"]["minutes"] == pytest.approx(60)
    assert prog["weeks"][0]["completed"]["distance_m"] == pytest.approx(15000)
    assert prog["weeks"][2]["completed"] is None  # nothing done yet in a future week: absent, not zero
    assert prog["weeks"][2]["planned"]["minutes"] == pytest.approx(80)
    assert prog["targets"]["minutes"] == 300
    assert prog["totals"]["completed_minutes"] == pytest.approx(60)

    cats = client.get("/api/phases").json()["categories"]
    assert cats[:5] == ["Base", "Build", "Peak", "Taper", "Recovery"]
    assert client.patch(f"/api/phases/{phase['id']}", json={"category": "Speed block"}).json()["category"] == "Speed block"
    assert "Speed block" in client.get("/api/phases").json()["categories"]
    assert client.patch(f"/api/phases/{phase['id']}", json={"category": "x" * 41}).status_code == 422
    assert client.get("/api/phases/99999/progress").status_code == 404


def test_event_result_link_follows_merges_and_survives_piece_delete(client, session):
    from catch.core.models import Event, Piece
    from catch.sync import planning as sp2

    _login(client)
    day = localtime.today(session) - timedelta(days=2)
    a = _row(session, "race", datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9), 8, 2000)
    ev = client.post("/api/events", json={"name": "Club 2k", "date": day.isoformat(), "type": "2k_test", "participation": "entered"}).json()
    ov = client.get(f"/api/events/{ev['id']}").json()
    assert [c["id"] for c in ov["result_candidates"]] == [a.canonical_id]
    piece = Piece(canonical_id=a.canonical_id, piece_type="2000m", distance_m=2000.0, duration_s=420.0, splits_json="[]")
    session.add(piece)
    session.commit()
    upd = client.patch(f"/api/events/{ev['id']}", json={"result_piece_id": piece.id, "participation": "completed"})
    assert upd.status_code == 200 and upd.json()["result_canonical_id"] == a.canonical_id  # the workout follows the piece
    res = client.get(f"/api/events/{ev['id']}").json()["result_link"]
    assert res["ref"] == f"/tests/piece/{piece.id}" and res["split_s"] == pytest.approx(105.0)
    assert client.patch(f"/api/events/{ev['id']}", json={"participation": "maybe"}).status_code == 422
    assert client.patch(f"/api/events/{ev['id']}", json={"result_canonical_id": 999999}).status_code == 404

    # Deleting the piece keeps the workout as the result.
    from catch.sync import piece as piece_sync

    piece_sync.delete_piece(session, piece.id)
    session.expire_all()
    row = session.get(Event, ev["id"])
    assert row.result_piece_id is None and row.result_canonical_id == a.canonical_id

    # A merge moves the result to the surviving workout.
    from catch.sync.activity_merge import move_references

    b = _row(session, "other", datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15), 30, 7000)
    move_references(session, b.canonical_id, a.canonical_id)
    session.commit()
    session.expire_all()
    assert session.get(Event, ev["id"]).result_canonical_id == b.canonical_id
    _ = sp2
