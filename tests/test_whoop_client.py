from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session, select

from catch.analytics.whoop import parse_offset_minutes, sleep_wake_date, sport_family
from catch.core import security
from catch.core.models import Activity, DailyWellness, OAuthToken, SyncState, WellnessReading
from catch.core.settings_store import update_settings
from catch.sync import whoop_client as wc
from catch.sync import wellness_readings
from tests.conftest import TEST_PASSWORD

FX = Path(__file__).parent / "fixtures" / "whoop"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def load(name):
    return json.loads((FX / name).read_text())


@pytest.fixture(autouse=True)
def whoop_settings(monkeypatch):
    monkeypatch.setattr(
        wc, "settings", dataclasses.replace(wc.settings, whoop_client_id="cid", whoop_client_secret="csecret-value", whoop_redirect_uri="http://localhost:8000/auth/whoop/callback")
    )


def connect(session, *, expires_in=3600, access="WHOOP-ACCESS-TOKEN-AAAAAAAAAAAA", refresh="WHOOP-REFRESH-TOKEN-BBBBBBBBBBBB"):
    session.add(
        OAuthToken(
            source="whoop",
            access_token_enc=security.encrypt(access),
            refresh_token_enc=security.encrypt(refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )
    )
    session.commit()


class FakeWhoop:
    """A routing MockTransport that also records every request."""

    def __init__(self, pages=None, token_status=200):
        self.requests: list[httpx.Request] = []
        self.pages = pages or {}
        self.token_status = token_status
        self.token_calls = 0
        self.api_status: list[int] = []

    def transport(self):
        def handler(request: httpx.Request):
            self.requests.append(request)
            path = request.url.path
            if path.endswith("/oauth2/token"):
                self.token_calls += 1
                if self.token_status != 200:
                    return httpx.Response(self.token_status, json={"error": "invalid_grant"})
                n = self.token_calls
                return httpx.Response(200, json={"access_token": f"NEW-ACCESS-{n}-XXXXXXXX", "refresh_token": f"NEW-REFRESH-{n}-YYYYYYYY", "expires_in": 3600, "token_type": "bearer"})
            if self.api_status:
                return httpx.Response(self.api_status.pop(0), json={"error": "x"}, headers={"x-ratelimit-reset": "2"})
            if request.method == "DELETE":
                return httpx.Response(204)
            for suffix, pages in self.pages.items():
                if path.endswith(suffix):
                    token = request.url.params.get("nextToken")
                    return httpx.Response(200, json=pages[int(token) if token else 0])
            return httpx.Response(404, json={})

        return httpx.MockTransport(handler)


# -- OAuth ----------------------------------------------------------------------------------


def test_authorize_url_requests_offline_and_the_documented_scopes():
    state = wc.new_state()
    assert len(state) == 8
    url = httpx.URL(wc.authorize_url(state))
    assert url.host == "api.prod.whoop.com" and url.path == "/oauth/oauth2/auth"
    scopes = url.params["scope"].split()
    assert "offline" in scopes and {"read:recovery", "read:sleep", "read:workout", "read:cycles"} <= set(scopes)
    assert url.params["state"] == state and url.params["response_type"] == "code"


def test_exchange_code_stores_tokens_encrypted(session):
    fake_response = load("token_response.json")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=fake_response))
    wc.exchange_code(session, "the-code", transport)
    row = session.get(OAuthToken, "whoop")
    assert "WHOOP-ACCESS-TOKEN" not in row.access_token_enc and "WHOOP-REFRESH-TOKEN" not in row.refresh_token_enc
    assert security.decrypt(row.refresh_token_enc) == "WHOOP-REFRESH-TOKEN-BBBBBBBBBBBB"
    assert row.expires_at is not None


def test_token_request_sends_credentials_in_the_form_body_not_the_url(session):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json=load("token_response.json"))

    wc.exchange_code(session, "abc", httpx.MockTransport(handler))
    assert "csecret-value" not in seen["url"] and "client_secret=csecret-value" in seen["body"] and "grant_type=authorization_code" in seen["body"]


def test_valid_token_is_reused_without_a_network_call(session):
    connect(session)
    fake = FakeWhoop()
    assert wc.get_access_token(session, fake.transport()) == "WHOOP-ACCESS-TOKEN-AAAAAAAAAAAA"
    assert fake.requests == []


def test_expired_token_refreshes_and_the_rotated_refresh_token_is_committed(session):
    connect(session, expires_in=60)  # inside the 5-minute skew
    fake = FakeWhoop()
    assert wc.get_access_token(session, fake.transport()) == "NEW-ACCESS-1-XXXXXXXX"
    body = fake.requests[0].content.decode()
    assert "grant_type=refresh_token" in body and "scope=offline" in body and "WHOOP-REFRESH-TOKEN-BBBBBBBBBBBB" in body
    session.expire_all()
    assert security.decrypt(session.get(OAuthToken, "whoop").refresh_token_enc) == "NEW-REFRESH-1-YYYYYYYY"


def test_a_second_caller_with_a_stale_row_does_not_refresh_again(engine):
    with Session(engine) as a:
        connect(a, expires_in=60)
        stale = a.get(OAuthToken, "whoop")
        assert stale.access_token_enc
        fake = FakeWhoop()
        with Session(engine) as b:
            wc.get_access_token(b, fake.transport())  # B rotates the token
        # A still holds the old, expired object in its identity map.
        assert wc.get_access_token(a, fake.transport()) == "NEW-ACCESS-1-XXXXXXXX"
    assert fake.token_calls == 1  # a second refresh would have used a dead token and failed


def test_a_refused_refresh_token_means_reconnect_and_does_not_loop(session):
    connect(session, expires_in=-10)
    fake = FakeWhoop(token_status=400)
    with pytest.raises(wc.WhoopReconnectNeeded) as exc:
        wc.get_access_token(session, fake.transport())
    assert "Reconnect" in str(exc.value) and "WHOOP-REFRESH" not in str(exc.value)
    assert fake.token_calls == 1


def test_not_connected_is_a_reconnect_error(session):
    with pytest.raises(wc.WhoopReconnectNeeded):
        wc.get_access_token(session, FakeWhoop().transport())


def test_a_401_from_the_api_forces_one_refresh_then_succeeds(session):
    connect(session)
    fake = FakeWhoop(pages={"/v2/recovery": [{"records": []}]})
    fake.api_status = [401]
    assert wc.WhoopApi(session, fake.transport()).get("/v2/recovery") == {"records": []}
    assert fake.token_calls == 1


def test_two_401s_in_a_row_ask_for_reconnection(session):
    connect(session)
    fake = FakeWhoop()
    fake.api_status = [401, 401]
    with pytest.raises(wc.WhoopReconnectNeeded):
        wc.WhoopApi(session, fake.transport()).get("/v2/recovery")


def test_429_waits_for_the_reset_header_once_then_retries(session):
    connect(session)
    fake = FakeWhoop(pages={"/v2/recovery": [{"records": []}]})
    fake.api_status = [429]
    waits = []
    assert wc.WhoopApi(session, fake.transport(), sleep=waits.append).get("/v2/recovery") == {"records": []}
    assert waits == [2.0]


def test_a_long_rate_limit_is_left_to_the_next_scheduled_sync(session):
    connect(session)
    fake = FakeWhoop()
    fake.api_status = [429]
    fake.api_status = [429]

    def handler(request):
        return httpx.Response(429, headers={"x-ratelimit-reset": "600"})

    with pytest.raises(wc.WhoopRateLimited):
        wc.WhoopApi(session, httpx.MockTransport(handler), sleep=lambda s: None).get("/v2/recovery")


def test_errors_never_contain_tokens(session):
    connect(session)
    def handler(r):
        return httpx.Response(500, text="WHOOP-ACCESS-TOKEN-AAAAAAAAAAAA leaked by server")

    with pytest.raises(wc.WhoopError) as exc:
        wc.WhoopApi(session, httpx.MockTransport(handler)).get("/v2/recovery")
    assert "WHOOP-ACCESS" not in str(exc.value)


# -- pagination -----------------------------------------------------------------------------


def test_records_follow_next_token_with_the_documented_parameter_names(session):
    connect(session)
    fake = FakeWhoop(pages={"/v2/activity/sleep": [{"records": [{"id": "a"}, {"id": "b"}], "next_token": "1"}, {"records": [{"id": "c"}]}]})
    got = list(wc.WhoopApi(session, fake.transport()).records("/v2/activity/sleep", NOW - timedelta(days=3)))
    assert [r["id"] for r in got] == ["a", "b", "c"]
    first, second = fake.requests
    assert first.url.params["limit"] == "25" and "nextToken" not in first.url.params
    assert second.url.params["nextToken"] == "1"
    assert first.headers["authorization"] == "Bearer WHOOP-ACCESS-TOKEN-AAAAAAAAAAAA"


# -- day assignment -------------------------------------------------------------------------


def test_offsets_and_wake_dates():
    assert parse_offset_minutes("-05:00") == -300 and parse_offset_minutes("+10:00") == 600 and parse_offset_minutes("Z") == 0
    assert parse_offset_minutes("garbage") == 0 and parse_offset_minutes(None) == 0
    # The same instant belongs to different wake days depending on the record's own offset.
    assert sleep_wake_date({"end": "2026-11-11T04:30:00.000Z", "timezone_offset": "-05:00"}) == date(2026, 11, 10)
    assert sleep_wake_date({"end": "2026-11-11T04:30:00.000Z", "timezone_offset": "+10:00"}) == date(2026, 11, 11)
    assert sleep_wake_date({"end": "2026-11-10T06:50:00.000Z", "timezone_offset": "-05:00"}) == date(2026, 11, 10)
    assert sleep_wake_date({"end": None}) is None


def test_sport_families():
    assert sport_family("Rowing") == "rowing" and sport_family("running") == "running" and sport_family("Spinning") == "cycling"
    assert sport_family("pickleball") == "other" and sport_family(None) == "other"


# -- import ---------------------------------------------------------------------------------


def pages():
    return {
        "/v2/activity/sleep": [load("sleep_page.json")],
        "/v2/recovery": [load("recovery_page.json")],
        "/v2/activity/workout": [load("workout_page.json")],
    }


def test_sync_imports_only_scored_main_sleep_recovery_and_workouts(session):
    connect(session)
    n = wc.sync(session, days=3, transport=FakeWhoop(pages()).transport(), now=NOW)
    assert n == 2  # one wake day + one workout

    day = date(2026, 11, 10)
    row = session.get(DailyWellness, day)
    assert row.source == "whoop"
    assert row.hrv_rmssd == pytest.approx(78.4) and row.resting_hr == 52 and row.spo2 == pytest.approx(96.5) and row.skin_temp_c == pytest.approx(33.4)
    assert row.sleep_seconds == 27000  # light + slow-wave + REM; the nap and the pending sleep are excluded
    assert (row.deep_sleep_seconds, row.light_sleep_seconds, row.rem_sleep_seconds, row.awake_sleep_seconds) == (6600, 14400, 6000, 2400)
    assert row.wake_time_minutes == 110  # 01:50 local
    assert row.sleep_respiration_avg == pytest.approx(14.6)
    assert json.loads(row.field_sources_json)["hrv_rmssd"] == "whoop"
    assert session.get(DailyWellness, date(2026, 11, 11)) is None  # PENDING_SCORE never lands

    workouts = session.exec(select(Activity).where(Activity.source == "whoop")).all()
    assert len(workouts) == 1  # the UNSCORABLE run is skipped
    w = workouts[0]
    assert (w.type, w.sport_family, w.duration, w.avg_hr, w.max_hr) == ("rowing", "rowing", 3600.0, 148, 171)
    assert w.calories == pytest.approx(500.0, rel=1e-3) and w.distance == 11800.0
    assert w.canonical_id is not None


def test_whoops_own_recovery_score_is_reference_only(session):
    connect(session)
    wc.sync(session, days=3, transport=FakeWhoop(pages()).transport(), now=NOW)
    reading = session.get(WellnessReading, (date(2026, 11, 10), "whoop", "hrv_rmssd"))
    assert json.loads(reading.meta_json)["whoop_recovery_score"] == 68.0
    from catch.core.models import DailyScore

    assert not any("68" in (s.recovery_json or "") and "whoop" in (s.recovery_json or "").lower() for s in session.exec(select(DailyScore)).all())


def test_resync_is_idempotent(session):
    connect(session)
    for _ in range(2):
        wc.sync(session, days=3, transport=FakeWhoop(pages()).transport(), now=NOW)
    assert len(session.exec(select(WellnessReading)).all()) == len(set((r.date, r.source, r.signal) for r in session.exec(select(WellnessReading)).all()))
    assert len(session.exec(select(Activity).where(Activity.source == "whoop")).all()) == 1


# -- the same night from two providers ------------------------------------------------------


def seed_garmin_night(session, day=date(2026, 11, 10), hrv=61.0, rhr=49, sleep=25000):
    wellness_readings.record_garmin(session, day, hrv_rmssd=hrv, resting_hr=rhr, sleep_seconds=sleep, sleep_meta={"wake_time_minutes": 400}, sleep_respiration=13.0)
    wellness_readings.resolve_days(session, [day])


def test_same_night_from_both_providers_resolves_to_one_row_and_one_winner(session):
    seed_garmin_night(session)
    connect(session)
    wc.sync(session, days=3, transport=FakeWhoop(pages()).transport(), now=NOW)
    rows = session.exec(select(DailyWellness)).all()
    assert [r.date for r in rows] == [date(2026, 11, 10)]  # one row, not one per provider
    row = rows[0]
    assert (row.hrv_rmssd, row.resting_hr, row.sleep_seconds) == (61.0, 49, 25000)  # Garmin first by default
    assert json.loads(row.field_sources_json) == {"hrv_rmssd": "garmin", "resting_hr": "garmin", "sleep_seconds": "garmin", "sleep_respiration": "garmin", "spo2": "whoop", "skin_temp_c": "whoop"}
    assert len(session.exec(select(WellnessReading).where(WellnessReading.signal == "hrv_rmssd")).all()) == 2  # both are kept as readings


def test_priority_change_re_decides_and_a_later_garmin_sync_cannot_overwrite_it(session):
    seed_garmin_night(session)
    connect(session)
    wc.sync(session, days=3, transport=FakeWhoop(pages()).transport(), now=NOW)
    update_settings(session, {"wellness_priority": {"hrv_rmssd": ["whoop", "garmin"], "resting_hr": ["whoop", "garmin"], "sleep_seconds": ["whoop", "garmin"]}})
    wellness_readings.resolve_all(session)
    row = session.get(DailyWellness, date(2026, 11, 10))
    assert (row.hrv_rmssd, row.resting_hr, row.sleep_seconds) == (pytest.approx(78.4), 52, 27000)

    seed_garmin_night(session, hrv=90.0, rhr=45, sleep=30000)  # Garmin syncs again with new numbers
    session.expire_all()
    row = session.get(DailyWellness, date(2026, 11, 10))
    assert (row.hrv_rmssd, row.resting_hr, row.sleep_seconds) == (pytest.approx(78.4), 52, 27000)
    assert row.deep_sleep_seconds == 6600  # stage columns follow the winning sleep record


def test_implausible_values_are_rejected_before_ranking(session):
    wellness_readings.record_garmin(session, date(2026, 11, 10), hrv_rmssd=9999.0)
    wellness_readings.record_reading(session, date(2026, 11, 10), "whoop", "hrv_rmssd", 70.0)
    wellness_readings.resolve_days(session, [date(2026, 11, 10)])
    assert session.get(DailyWellness, date(2026, 11, 10)).hrv_rmssd == 70.0


def test_the_baseline_never_counts_one_night_twice(session):
    from catch.sync.scoring import day_recovery
    from catch.core.settings_store import get_settings

    for i in range(9):
        day = date(2026, 11, 1) + timedelta(days=i)
        wellness_readings.record_garmin(session, day, hrv_rmssd=60 + i, resting_hr=50, sleep_seconds=26000)
        wellness_readings.record_reading(session, day, "whoop", "hrv_rmssd", 70 + i)
    wellness_readings.resolve_all(session)
    result = day_recovery(session, date(2026, 11, 10), get_settings(session), {})
    assert result["calibration"]["nights"] == 9  # nine nights, not eighteen readings
    hrv = next(a for a in result["data_availability"] if a["signal"] == "hrv_rmssd")
    assert hrv["baseline_nights"] == 9 and hrv["source"] is None  # no reading for the day being scored


def test_mixed_baseline_is_flagged_and_availability_names_the_source(session):
    from catch.sync.scoring import day_recovery
    from catch.core.settings_store import get_settings

    for i in range(8):
        day = date(2026, 11, 1) + timedelta(days=i)
        source = "garmin" if i < 4 else "whoop"
        wellness_readings.record_reading(session, day, source, "hrv_rmssd", 60 + i)
        wellness_readings.record_reading(session, day, source, "resting_hr", 50)
    wellness_readings.record_reading(session, date(2026, 11, 9), "whoop", "hrv_rmssd", 66.0)
    wellness_readings.resolve_all(session)
    result = day_recovery(session, date(2026, 11, 9), get_settings(session), {})
    assert "hrv_rmssd" in result["baseline_mixed_sources"]
    assert next(a for a in result["data_availability"] if a["signal"] == "hrv_rmssd")["source"] == "whoop"
    assert result["calibration"]["status"] == "calibrated"


def test_calibrating_status_and_availability_before_enough_nights(session):
    from catch.sync.scoring import day_recovery
    from catch.core.settings_store import get_settings

    wellness_readings.record_garmin(session, date(2026, 11, 2), hrv_rmssd=60.0)
    wellness_readings.resolve_all(session)
    result = day_recovery(session, date(2026, 11, 3), get_settings(session), {})
    assert result["band"] == "calibrating" and result["calibration"] == {"status": "calibrating", "nights": 1, "required": 7, "nights_remaining": 6}
    assert {a["signal"] for a in result["data_availability"]} >= {"hrv_rmssd", "resting_hr", "sleep_seconds", "checkin"}


def test_whoop_and_garmin_workouts_merge_into_one_canonical(session):
    from catch.sync.matching import run_matching
    from catch.sync.upsert import upsert_activity

    connect(session)
    upsert_activity(session, "garmin", "g1", type="rowing_v2", start=datetime(2026, 11, 10, 13, 0, 20, tzinfo=timezone.utc), duration=3590.0, distance=11750.0, avg_hr=150, max_hr=172)
    wc.sync(session, days=3, transport=FakeWhoop(pages()).transport(), now=NOW)
    run_matching(session)
    canonicals = {a.canonical_id for a in session.exec(select(Activity)).all()}
    assert len(canonicals) == 1  # one physical session, two source records


# -- disconnect, scheduler, routes ----------------------------------------------------------


def test_disconnect_revokes_forgets_tokens_and_keeps_imported_data(session):
    connect(session)
    wc.sync(session, days=3, transport=FakeWhoop(pages()).transport(), now=NOW)
    session.add(SyncState(source="whoop"))
    session.commit()
    fake = FakeWhoop()
    result = wc.disconnect(session, fake.transport())
    assert result == {"revoked": True, "was_connected": True}
    assert any(r.method == "DELETE" and r.url.path == "/developer/v2/user/access" for r in fake.requests)
    assert session.get(OAuthToken, "whoop") is None and session.get(SyncState, "whoop") is None
    assert session.get(DailyWellness, date(2026, 11, 10)) is not None
    assert len(session.exec(select(Activity).where(Activity.source == "whoop")).all()) == 1
    assert wc.disconnect(session, fake.transport()) == {"revoked": False, "was_connected": False}


def test_disconnect_still_forgets_tokens_when_whoop_is_unreachable(session):
    connect(session)
    result = wc.disconnect(session, httpx.MockTransport(lambda r: httpx.Response(500)))
    assert result["revoked"] is False and session.get(OAuthToken, "whoop") is None


def test_check_reports_counts_only(session):
    connect(session)
    fake = FakeWhoop({**pages(), "/v2/user/profile/basic": [{"user_id": 7, "email": "me@example.test", "first_name": "Ben"}], "/v2/cycle": [{"records": []}]})
    report = wc.check(session, fake.transport())
    text = json.dumps(report)
    assert report["recovery"]["has_records"] and "me@example.test" not in text and "Ben" not in text and "WHOOP-ACCESS" not in text


def test_scheduler_skips_whoop_when_not_connected_and_raises_no_alert(session, engine, monkeypatch):
    import contextlib

    from catch.sync import scheduler

    @contextlib.contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(scheduler, "get_session", fake_session)
    assert scheduler.run_sync("whoop") == {"source": "whoop", "skipped": "not connected"}
    assert session.get(SyncState, "whoop") is None


def test_scheduler_runs_whoop_when_connected(session, monkeypatch):
    import contextlib

    from catch.sync import scheduler

    @contextlib.contextmanager
    def fake_session():
        yield session

    connect(session)
    monkeypatch.setattr(scheduler, "get_session", fake_session)
    monkeypatch.setattr(wc, "sync", lambda s, days=3, **k: 4)
    result = scheduler.run_sync("whoop", days=2)
    assert result == {"source": "whoop", "records": 4}
    assert session.get(SyncState, "whoop").last_success_at is not None


def _login(client):
    assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 200


def test_oauth_routes(client, monkeypatch):
    _login(client)
    monkeypatch.setattr("catch.sync.whoop_client.exchange_code", lambda db, code, transport=None: None)
    start = client.get("/auth/whoop/start", follow_redirects=False)
    assert start.status_code in (302, 307) and start.headers["location"].startswith("https://api.prod.whoop.com/oauth/oauth2/auth")
    state = httpx.URL(start.headers["location"]).params["state"]
    assert client.cookies.get("whoop_oauth_state") == state

    bad = client.get("/auth/whoop/callback", params={"code": "c", "state": "WRONGSTA"}, follow_redirects=False)
    assert bad.status_code == 400
    ok = client.get("/auth/whoop/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/settings?whoop=connected"


def test_oauth_denied_lands_on_settings(client):
    _login(client)
    start = client.get("/auth/whoop/start", follow_redirects=False)
    state = httpx.URL(start.headers["location"]).params["state"]
    denied = client.get("/auth/whoop/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
    assert denied.headers["location"] == "/settings?whoop=denied"


def test_oauth_routes_need_login(client):
    assert client.get("/auth/whoop/start", follow_redirects=False).status_code == 401
    assert client.post("/auth/whoop/disconnect").status_code == 401
    assert client.get("/api/whoop/test").status_code == 401


def test_test_endpoint_when_not_connected_asks_to_reconnect(client):
    _login(client)
    body = client.get("/api/whoop/test").json()
    assert body["connected"] is False and body["reconnect"] is True
