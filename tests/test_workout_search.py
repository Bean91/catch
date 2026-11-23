"""Session 36: searching and filtering the workouts list, and the athlete's own context fields (conditions, equipment)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from catch.core.models import Activity, CanonicalActivity, Note
from catch.sync.matching import run_matching
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _w(session, i: int, overrides: dict | None = None, title: str | None = None):
    a = Activity(source="garmin", external_id=f"s{i}", type="indoor_rowing", start=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=i), duration=1800.0, title_hint=title)
    session.add(a)
    session.commit()
    run_matching(session)
    session.refresh(a)
    if overrides:
        c = session.get(CanonicalActivity, a.canonical_id)
        c.overrides_json = json.dumps(overrides)
        session.add(c)
        session.commit()
    return a.canonical_id


def test_search_notes_conditions_equipment_and_tags(client, session):
    windy = _w(session, 1, {"notes": "Felt strong", "conditions": "Windy, choppy", "tags": ["race"]})
    _w(session, 2, {"notes": "easy"})
    boat = _w(session, 3, {"equipment": "Empacher 1x"})
    _w(session, 4, {"notes": "nothing to see"})  # the word "notes" is a key name in every row's JSON — never a match by itself
    _login(client)
    ids = lambda **p: [i["id"] for i in client.get("/api/activities", params=p).json()["items"]]  # noqa: E731
    assert ids(q="windy") == [windy]
    assert ids(q="EMPACHER") == [boat]
    assert ids(tag="race") == [windy]
    assert set(ids(has_notes=True)) == {windy, _id_of(session, 2), _id_of(session, 4)}
    assert ids(q="notes") == []


def _id_of(session, i):
    a = session.exec(__import__("sqlmodel").select(Activity).where(Activity.external_id == f"s{i}")).first()
    return a.canonical_id


def test_day_note_text_finds_that_days_workout(client, session):
    cid = _w(session, 5)
    c = session.get(CanonicalActivity, cid)
    session.add(Note(date=c.local_date, text="Coach watched from the launch"))
    session.commit()
    _login(client)
    assert [i["id"] for i in client.get("/api/activities", params={"q": "launch"}).json()["items"]] == [cid]


def test_filtered_paging_is_exact(client, session):
    for i in range(12):
        _w(session, 10 + i, {"tags": ["tempo"]} if i % 3 == 0 else {"tags": ["easy"]})
    _login(client)
    first = client.get("/api/activities", params={"tag": "tempo", "limit": 2}).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = client.get("/api/activities", params={"tag": "tempo", "limit": 2, "cursor": first["next_cursor"]}).json()
    assert len(second["items"]) == 2
    seen = [i["id"] for i in first["items"] + second["items"]]
    assert len(set(seen)) == 4


def test_conditions_and_equipment_are_editable_and_kept_apart(client, session):
    cid = _w(session, 30)
    _login(client)
    body = client.patch(f"/api/activities/{cid}", json={"conditions": "Headwind", "equipment": "Club 8+"}).json()
    assert body["conditions"] == "Headwind" and body["equipment"] == "Club 8+"
    assert client.patch(f"/api/activities/{cid}", json={"conditions": "x" * 301}).status_code == 422
    reverted = client.post(f"/api/activities/{cid}/revert", json={"field": "conditions"}).json()
    assert reverted["conditions"] is None and reverted["equipment"] == "Club 8+"


def test_data_quality_summary(client, session):
    from catch.sync.samples import store_samples

    a = Activity(source="garmin", external_id="dq", type="indoor_rowing", start=datetime(2026, 9, 9, tzinfo=timezone.utc), duration=100.0, distance=400.0, avg_hr=140.0)
    session.add(a)
    session.commit()
    store_samples(session, a.id, start=a.start, hr=[140.0] * 75 + [None] * 25, power=[None] * 100, cadence=[20.0] * 100)
    run_matching(session)
    session.refresh(a)
    _login(client)
    dq = client.get(f"/api/activities/{a.canonical_id}").json()["data_quality"]
    assert dq["channels"]["heart_rate"] and not dq["channels"]["power"] and dq["channels"]["cadence"]
    assert dq["completeness"]["heart_rate_pct"] == 75.0
    assert {f["field"]: f["basis"] for f in dq["figures"]}["avg_split"] == "derived"
    assert dq["sources"][0]["source"] == "garmin"
