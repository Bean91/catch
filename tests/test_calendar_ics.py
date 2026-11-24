"""Session 36 follow-up: the .ics download of planned sessions and events (catch/analytics/ics.py, catch/sync/calendar_export.py)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from catch.analytics import ics
from catch.core import localtime
from catch.core.models import Activity, Event, PlannedWorkout
from conftest import TEST_PASSWORD


def test_escaping_and_folding_follow_rfc_5545():
    assert ics.escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    long = "DESCRIPTION:" + "é" * 80
    folded = ics.fold(long)
    pieces = folded.split("\r\n")
    assert all(len(p.encode("utf-8")) <= 75 for p in pieces)
    assert all(p.startswith(" ") for p in pieces[1:])
    assert "".join(p[1:] if i else p for i, p in enumerate(pieces)) == long  # unfolding gives the line back


def test_all_day_and_timed_entries():
    stamp = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    allday = ics.vevent(uid="u1", stamp=stamp, summary="Race", day=date(2026, 6, 1))
    assert "DTSTART;VALUE=DATE:20260601" in allday and "DTEND;VALUE=DATE:20260602" in allday
    timed = ics.vevent(uid="u2", stamp=stamp, summary="Erg", day=date(2026, 6, 1), start=datetime(2026, 6, 1, 7, 30, tzinfo=timezone(timedelta(hours=1))), minutes=45)
    assert "DTSTART:20260601T063000Z" in timed and "DTEND:20260601T071500Z" in timed
    text = ics.calendar([allday, timed])
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n") and "\n" not in text.replace("\r\n", "")


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_calendar_download_has_plans_and_events_only(client, session):
    _login(client)
    today = localtime.today(session)
    session.add(PlannedWorkout(date=today + timedelta(days=2), session_type="erg", title="3 x 2k, steady; rate 20", duration_min=75,
                               start_time="07:15", description="Line one\nline two"))
    session.add(PlannedWorkout(date=today + timedelta(days=3), session_type="erg", title="Skipped one", status="skipped"))
    session.add(PlannedWorkout(date=today + timedelta(days=500), session_type="erg", title="Far away"))
    session.add(Event(name="Head of the River", date=today + timedelta(days=20), type="race", location="Putney, London", participation="entered"))
    session.add(Activity(source="garmin", external_id="done-1", type="indoor_rowing",
                         start=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc), duration=600.0))
    session.commit()
    r = client.get("/api/calendar/export.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    body = r.text
    assert body.count("BEGIN:VEVENT") == 3  # two plans + one event; the far plan is outside the default year; no workout
    assert "SUMMARY:3 x 2k\\, steady\\; rate 20" in body
    assert "DESCRIPTION:75 min\\nLine one\\nline two\\nA plan\\, not a completed workout." in body.replace("\r\n ", "")
    assert "LOCATION:Putney\\, London" in body
    assert body.count("STATUS:CANCELLED") == 1
    tz = localtime.zone_for_day(session, today + timedelta(days=2))
    expected = datetime.combine(today + timedelta(days=2), datetime.min.time().replace(hour=7, minute=15), tzinfo=tz).astimezone(timezone.utc)
    assert f"DTSTART:{expected:%Y%m%dT%H%M%SZ}" in body
    # Stable UIDs: a second download names the same entries.
    uids = sorted(line for line in body.split("\r\n") if line.startswith("UID:"))
    again = sorted(line for line in client.get("/api/calendar/export.ics").text.split("\r\n") if line.startswith("UID:"))
    assert uids == again
    wide = client.get(f"/api/calendar/export.ics?from={today.isoformat()}&to={(today + timedelta(days=600)).isoformat()}").text
    assert "Far away" in wide
