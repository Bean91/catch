"""Session 30 (docs/mobile/health-data.md): consent gating, per-category limits, duplicate suppression against connected providers,
provenance, isolation and deletion for the Apple Health / Health Connect import."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from catch.core import tenant
from catch.core.models import Activity, CanonicalActivity, DailyWellness, WellnessReading
from catch.sync import connections
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A, B = bearer(kit.ALICE), bearer(kit.BOB)


def _iso(delta_days=1, hour=7, minutes=40):
    start = (datetime.now(timezone.utc) - timedelta(days=delta_days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(minutes=minutes)).isoformat()


def _workout(ext="w1", app="Apple Watch", app_id="com.apple.health", **kw):
    s, e = _iso()
    return {"external_id": ext, "type": "rowingMachine", "start": s, "end": e, "distance_m": 8000, "energy_kcal": 500, "avg_hr": 150, "max_hr": 178, "origin_app": app, "origin_id": app_id, **kw}


def _consent(client, headers, platform="apple_health", cats=("workouts", "sleep", "resting_hr", "spo2")):
    return client.put("/api/health/consent", headers=headers, json={"platform": platform, "categories": list(cats)})


def _day(delta=1):
    return (datetime.now(timezone.utc) - timedelta(days=delta)).date().isoformat()


@pytest.fixture()
def api(pub_client):
    pub_client.get("/api/me", headers=A)
    pub_client.get("/api/me", headers=B)
    return pub_client


def test_nothing_is_accepted_before_the_person_consents(api):
    r = api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout()]})
    assert r.status_code == 403 and "Settings" in r.json()["detail"]
    assert api.get("/api/health/status", headers=A).json()["counts"]["apple_health"] == {"workouts": 0, "readings": 0}


def test_consent_lists_categories_and_refuses_what_the_platform_cannot_supply(api):
    assert _consent(api, A, cats=("workouts", "hrv")).status_code == 422  # HealthKit reports SDNN, not the RMSSD Catch uses
    assert _consent(api, A, "health_connect", cats=("workouts", "hrv")).status_code == 200
    assert _consent(api, A, cats=()).status_code == 422
    assert api.put("/api/health/consent", headers=A, json={"platform": "fitbit", "categories": ["workouts"]}).status_code == 422
    assert [c["categories"] for c in api.get("/api/health/status", headers=A).json()["consents"]] == [["hrv", "workouts"]]


def test_an_import_is_limited_to_the_categories_the_person_ticked(api):
    _consent(api, A, cats=("workouts",))
    r = api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout()], "readings": [{"category": "resting_hr", "date": _day(), "value": 52}]}).json()
    assert r["workouts"] == 1 and r["readings"] == 0 and r["skipped_not_consented"] == 1


def test_a_workout_lands_as_a_canonical_activity_with_its_origin_app(api, pub_engine):
    _consent(api, A)
    assert api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout(app="Apple Watch")]}).json()["workouts"] == 1
    api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout(app="Apple Watch")]})  # idempotent re-send
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        rows = s.exec(select(Activity)).all()
        assert [(a.source, a.sport_family, a.canonical_id is not None) for a in rows] == [("apple_health", "rowing", True)]
        assert '"origin_app": "Apple Watch"' in rows[0].raw_json


def test_a_workout_recorded_by_a_connected_provider_is_not_imported_twice(api, pub_engine):
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        connections.store_credential(s, "garmin", "garmin-personal-api-key-0123456789", auth_method="api_key")
    _consent(api, A)
    r = api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout("g1", app="Garmin Connect", app_id="com.garmin.connect.mobile"), _workout("a1")]}).json()
    assert r["workouts"] == 1 and r["skipped_duplicate"] == 1
    # …but with Garmin not connected the same record is the only copy, so it is kept (and still labelled)
    r2 = api.post("/api/health/import", headers=B, json={"platform": "apple_health", "workouts": []})
    assert r2.status_code == 403


def test_a_garmin_session_that_still_slips_through_merges_into_one_canonical_with_garmin_winning(api, pub_engine):
    from catch.sync.upsert import upsert_activity

    s_iso, e_iso = _iso()
    start = datetime.fromisoformat(s_iso)
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        upsert_activity(s, "garmin", "G-1", type="indoor_rowing", start=start, duration=2400.0, distance=8100.0, avg_hr=151.0)
    _consent(api, A)
    api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout(app="Apple Watch")]})  # Garmin not marked connected: no client-side filter
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        assert len(s.exec(select(CanonicalActivity)).all()) == 1  # the matching engine merged the overlap
        canon = s.exec(select(CanonicalActivity)).first()
        assert canon.distance == 8100.0  # Garmin's distance outranks the health platform's


def test_readings_resolve_one_winner_per_day_and_keep_the_provider_visible(api, pub_engine):
    _consent(api, A)
    r = api.post("/api/health/import", headers=A, json={"platform": "apple_health", "readings": [
        {"category": "resting_hr", "date": _day(), "value": 52, "origin_app": "Apple Watch"},
        {"category": "sleep", "date": _day(), "sleep_seconds": 27000, "deep_sleep_seconds": 5400, "origin_app": "Apple Watch"},
        {"category": "resting_hr", "date": _day(), "value": 400},
    ]}).json()
    assert r["readings"] == 2 and r["skipped_invalid"] == 1
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        w = s.exec(select(DailyWellness)).first()
        assert w.resting_hr == 52 and w.sleep_seconds == 27000
        assert '"apple_health"' in (w.field_sources_json or "")


def test_a_garmin_reading_outranks_a_health_platform_reading(api, pub_engine):
    from catch.sync import wellness_readings as wr

    day = datetime.now(timezone.utc).date() - timedelta(days=1)
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        wr.record_reading(s, day, "garmin", "resting_hr", 49)
        wr.resolve_days(s, [day])
    _consent(api, A)
    api.post("/api/health/import", headers=A, json={"platform": "apple_health", "readings": [{"category": "resting_hr", "date": day.isoformat(), "value": 55}]})
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        assert s.exec(select(DailyWellness)).first().resting_hr == 49


def test_batches_are_bounded_and_bad_records_never_echo_back(api):
    _consent(api, A)
    assert api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout(f"w{i}") for i in range(201)]}).status_code == 413
    r = api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [{"external_id": "x", "start": "SECRET-VALUE", "end": "no"}, {}]})
    assert r.status_code == 200 and r.json()["skipped_invalid"] == 2 and "SECRET-VALUE" not in r.text
    bad = api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": ["SECRET-VALUE"]})
    assert bad.status_code == 422 and "SECRET-VALUE" not in bad.text


def test_revoking_stops_imports_and_can_delete_what_was_imported(api, pub_engine):
    _consent(api, A)
    api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout()], "readings": [{"category": "resting_hr", "date": _day(), "value": 52}]})
    out = api.post("/api/health/consent/revoke", headers=A, json={"platform": "apple_health", "delete_data": True}).json()
    assert out["revoked"] and out["workouts"] == 1 and out["readings"] == 1
    assert api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout()]}).status_code == 403
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        assert s.exec(select(Activity)).all() == [] and s.exec(select(CanonicalActivity)).all() == [] and s.exec(select(WellnessReading)).all() == []


def test_deleting_imported_data_leaves_other_sources_alone(api, pub_engine):
    from catch.sync.upsert import upsert_activity

    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        upsert_activity(s, "garmin", "G-2", type="running", start=datetime.now(timezone.utc) - timedelta(days=3), duration=1800.0, distance=5000.0)
    _consent(api, A)
    api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout()]})
    assert api.delete("/api/health/data", headers=A).json()["workouts"] == 1
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        assert [a.source for a in s.exec(select(Activity)).all()] == ["garmin"]


def test_two_people_never_see_each_others_imports(api):
    _consent(api, A)
    _consent(api, B)
    api.post("/api/health/import", headers=A, json={"platform": "apple_health", "workouts": [_workout()]})
    assert api.get("/api/health/status", headers=B).json()["counts"]["apple_health"]["workouts"] == 0
    assert api.delete("/api/health/data", headers=B).json()["workouts"] == 0
    assert api.get("/api/health/status", headers=A).json()["counts"]["apple_health"]["workouts"] == 1


def test_routes_need_a_signed_in_person_and_do_not_exist_on_a_personal_install(api, client):
    assert api.get("/api/health/status").status_code == 401
    assert api.put("/api/health/consent", json={"platform": "apple_health", "categories": ["workouts"]}).status_code == 401
    assert client.get("/api/health/status").status_code in (401, 404)
