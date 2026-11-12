"""Two signed-in users with overlapping dates and similar workouts, through the real HTTP routes (session 24)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session

from catch.core import tenant
from catch.sync.matching import run_matching
from catch.sync.upsert import upsert_activity, upsert_daily_wellness
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A, B = bearer(kit.ALICE), bearer(kit.BOB)
TODAY = date.today()


def _seed_activity(engine, owner: str, *, minutes: int = 60):
    # The same source/external_id for both users: two people can legitimately sync the same Concept2 id.
    with tenant.use_owner(owner), Session(engine) as s:
        a = upsert_activity(
            s, "garmin", "act-1", type="rowing_v2", start=datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc),
            duration=minutes * 60.0, distance=12000.0, avg_hr=140.0,
        )
        upsert_daily_wellness(s, date(2026, 11, 2), resting_hr=50 if owner == kit.ALICE else 70, hrv_rmssd=60.0)
        run_matching(s)
        s.refresh(a)
        return a.id, a.canonical_id


def test_overlapping_workouts_and_wellness_stay_separate(pub_client, pub_engine):
    a_id, a_canon = _seed_activity(pub_engine, kit.ALICE, minutes=60)
    b_id, b_canon = _seed_activity(pub_engine, kit.BOB, minutes=30)
    assert a_id != b_id

    mine = pub_client.get("/api/activities", headers=A).json()["items"]
    his = pub_client.get("/api/activities", headers=B).json()["items"]
    assert [i["duration"] for i in mine] == [3600.0] and [i["duration"] for i in his] == [1800.0]
    assert pub_client.get("/api/wellness?from=2026-11-02&to=2026-11-02", headers=A).json()[0]["resting_hr"] == 50
    assert pub_client.get("/api/wellness?from=2026-11-02&to=2026-11-02", headers=B).json()[0]["resting_hr"] == 70


def test_guessing_another_users_ids_finds_nothing(pub_client, pub_engine):
    a_id, a_canon = _seed_activity(pub_engine, kit.ALICE)
    for path in (f"/api/activities/{a_canon}", f"/api/activities/{a_canon}/samples", f"/api/activities/{a_canon}/zones"):
        assert pub_client.get(path, headers=B).status_code == 404, path
    assert pub_client.patch(f"/api/activities/{a_canon}", headers=B, json={"title": "pwned"}).status_code in (404, 405)
    assert pub_client.get(f"/api/activities/{a_canon}", headers=A).status_code == 200


def test_notes_and_checkins_with_the_same_date_do_not_collide(pub_client):
    for headers, text in ((A, "alice felt strong"), (B, "bob felt flat")):
        assert pub_client.post("/api/notes", headers=headers, json={"date": "2026-11-02", "text": text, "rpe": 7}).status_code == 200
        assert pub_client.post("/api/checkins", headers=headers, json={"soreness": 2 if text.startswith("alice") else 5}).status_code == 200
    assert pub_client.get("/api/notes", headers=A, params={"date": "2026-11-02"}).json()["text"] == "alice felt strong"
    assert pub_client.get("/api/notes", headers=B, params={"date": "2026-11-02"}).json()["text"] == "bob felt flat"
    assert pub_client.get("/api/checkins/today", headers=A).json()["checkin"]["soreness"] == 2
    assert pub_client.get("/api/checkins/today", headers=B).json()["checkin"]["soreness"] == 5


def test_calendar_events_and_plans_are_private_and_cannot_be_linked_across_users(pub_client, pub_engine):
    _, a_canon = _seed_activity(pub_engine, kit.ALICE)
    ev = pub_client.post("/api/events", headers=A, json={"name": "Nationals", "date": (TODAY + timedelta(days=20)).isoformat(), "type": "race"}).json()
    plan = pub_client.post("/api/planned", headers=A, json={"date": TODAY.isoformat(), "session_type": "erg"}).json()["planned"][0]
    assert pub_client.get("/api/events", headers=B, params={"from": TODAY.isoformat(), "to": (TODAY + timedelta(days=60)).isoformat()}).json()["events"] == []
    assert pub_client.get(f"/api/events/{ev['id']}", headers=B).status_code == 404
    assert pub_client.patch(f"/api/events/{ev['id']}", headers=B, json={"name": "mine now"}).status_code == 404
    assert pub_client.delete(f"/api/events/{ev['id']}", headers=B).status_code == 404
    assert pub_client.get(f"/api/planned/{plan['id']}", headers=B).status_code == 404
    # Bob's own plan cannot attach Alice's workout (a foreign key check would otherwise accept the id).
    bobs = pub_client.post("/api/planned", headers=B, json={"date": TODAY.isoformat(), "session_type": "erg"}).json()["planned"][0]
    assert pub_client.post(f"/api/planned/{bobs['id']}/link", headers=B, json={"canonical_id": a_canon}).status_code == 404
    assert pub_client.post("/api/planned", headers=B, json={"date": TODAY.isoformat(), "session_type": "erg", "event_id": ev["id"]}).status_code == 404
    assert pub_client.get(f"/api/events/{ev['id']}", headers=A).status_code == 200


def test_technique_notes_cannot_hang_off_someone_elses_workout(pub_client, pub_engine):
    _, a_canon = _seed_activity(pub_engine, kit.ALICE)
    mine = pub_client.post("/api/technique-notes", headers=A, json={"category": "catch", "text": "Early arms", "date": "2026-11-02", "canonical_id": a_canon})
    assert mine.status_code in (200, 201), mine.text
    bobs = pub_client.get("/api/technique-notes", headers=B).json()
    assert bobs == [] or bobs.get("notes", []) == []
    assert pub_client.post("/api/technique-notes", headers=B, json={"category": "catch", "text": "x", "date": "2026-11-02", "canonical_id": a_canon}).status_code in (404, 422)


def test_coach_conversations_and_memory_are_private(pub_client):
    conv = pub_client.post("/api/coach/conversations", headers=A).json()
    assert pub_client.get(f"/api/coach/conversations/{conv['id']}", headers=B).status_code == 404
    assert pub_client.delete(f"/api/coach/conversations/{conv['id']}", headers=B).status_code == 404
    assert pub_client.get("/api/coach/conversations", headers=B).json() == []
    ev = pub_client.post("/api/coach/memory/events", headers=A, json={"name": "Old", "date": (TODAY + timedelta(days=5)).isoformat(), "type": "race"}).json()
    assert pub_client.put(f"/api/coach/memory/events/{ev['id']}", headers=B, json={"goal_time": "6:40"}).status_code in (404, 422)


def test_provider_keys_and_settings_are_per_user(pub_client, monkeypatch):
    from catch.coach.providers import anthropic_provider, gemini_provider, openai_provider

    async def fake(self):
        return {"ok": True, "kind": None, "message": "Connected", "model_count": 3}

    for cls in (openai_provider.OpenAIProvider, gemini_provider.GeminiProvider, anthropic_provider.AnthropicProvider):
        monkeypatch.setattr(cls, "validate", fake)
    key = "sk-proj-ALICE-secret-key-aaaaaaaaaaaaaaaa1111"
    pub_client.put("/api/ai/providers/openai/key", headers=A, json={"api_key": key})
    mine = pub_client.get("/api/ai/providers", headers=A).json()
    his = pub_client.get("/api/ai/providers", headers=B).json()
    assert any(p["configured"] for p in mine["providers"] if p["id"] == "openai")
    assert not any(p["configured"] for p in his["providers"] if p["id"] == "openai")
    assert key not in pub_client.get("/api/ai/providers", headers=A).text


def test_a_users_id_in_the_request_body_or_a_tool_argument_is_ignored(pub_client, pub_engine):
    a_id, a_canon = _seed_activity(pub_engine, kit.ALICE)
    r = pub_client.post("/api/notes", headers=B, json={"date": "2026-11-02", "text": "bob's", "owner_id": kit.ALICE, "user_id": kit.ALICE})
    assert r.status_code == 200
    assert pub_client.get("/api/notes", headers=B, params={"date": "2026-11-02"}).json()["text"] == "bob's"  # it landed on Bob...
    assert pub_client.get("/api/notes", headers=A, params={"date": "2026-11-02"}).json() is None  # ...not on the user it named
    # And through the shared tool endpoint, which the AI coach and MCP use: Bob names Alice's owner AND her workout id.
    r = pub_client.post("/api/coach/tools/get_workout", headers=B, json={"args": {"owner_id": kit.ALICE, "user_id": kit.ALICE, "id": a_canon}})
    assert kit.ALICE not in r.text and "3600" not in r.text
    mine = pub_client.post("/api/coach/tools/get_workout", headers=A, json={"args": {"id": a_canon}})
    assert mine.status_code == 200 and "3600" in mine.text or mine.json().get("duration_s") == 3600  # positive control: Alice can read it


def test_the_series_cache_is_per_user(pub_client, pub_engine):
    _seed_activity(pub_engine, kit.ALICE)
    _seed_activity(pub_engine, kit.BOB)
    a = pub_client.get("/api/series", headers=A, params={"metrics": "resting_hr"}).json()
    b = pub_client.get("/api/series", headers=B, params={"metrics": "resting_hr"}).json()
    assert a != b


def test_device_tokens_belong_to_the_user_who_minted_them(pub_client, pub_engine):
    from catch.api.deps import hash_token
    from catch.core.models import ApiToken

    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        s.add(ApiToken(name="laptop", token_hash=hash_token("alice-device-token-xxxxxxxxxxxxxxxx")))
        s.commit()
    _, a_canon = _seed_activity(pub_engine, kit.ALICE, minutes=60)
    _, b_canon = _seed_activity(pub_engine, kit.BOB, minutes=30)
    r = pub_client.post("/api/coach/tools/list_workouts", headers={"authorization": "Bearer alice-device-token-xxxxxxxxxxxxxxxx"}, json={"args": {}})
    assert r.status_code == 200, r.text
    ids = [w["id"] for w in r.json()["items"]]
    assert ids == [a_canon] and b_canon not in ids  # exactly Alice's workout, never Bob's
    assert pub_client.post("/api/coach/tools/list_workouts", headers={"authorization": "Bearer not-a-token"}, json={"args": {}}).status_code == 401


# --- scheduled work and ops channels in a public deployment ---------------------------------------------------------


def test_the_real_tick_for_fresh_accounts_runs_clean_and_raises_no_alert(pub_client, pub_engine, monkeypatch):
    """A new public account has connected nothing. Every tick must treat that as the normal state: no failed sync, no
    error row, no 'sync is broken' push, no write to the shared ops topic, no shared dead-man's-switch ping."""
    from sqlalchemy import select

    from catch.core import healthchecks
    from catch.core.models import SyncState
    from catch.notify import ntfy, push

    sent: list = []
    monkeypatch.setattr(ntfy, "send", lambda *a, **k: sent.append(("ntfy", a)) or True)
    monkeypatch.setattr(push, "send_to_subscription", lambda *a, **k: sent.append(("push", a)) or True)
    monkeypatch.setattr(push, "notify", lambda *a, **k: sent.append(("notify", a)) or [])
    monkeypatch.setattr(healthchecks, "ping_sync_ok", lambda *a, **k: sent.append(("ping", a)))
    for headers in (A, B):
        assert pub_client.get("/api/me", headers=headers).status_code == 200  # creates the profiles
    tick = {"authorization": "Bearer tick-secret-for-tests"}
    for _ in range(4):  # past the 3-failures threshold a broken source would alert on
        for job in ("sync", "notifications"):
            out = pub_client.post(f"/internal/tick/{job}", headers=tick).json()
            assert out["users"] == 2 and out["failed"] == 0, (job, out)
        # the lease rows are the only sync_state a fresh account has
        # (each tick's lease is released, so the next one runs)
    with Session(pub_engine) as s:
        rows = s.execute(select(SyncState).execution_options(tenant_unscoped=True)).scalars().all()
    assert {r.source for r in rows} <= {"job:sync", "job:notifications"}
    assert all(r.last_error is None and r.consecutive_failures == 0 for r in rows)
    assert sent == []


def test_a_manual_sync_of_an_unconnected_source_is_skipped_not_failed(pub_client, pub_engine):
    from sqlalchemy import select

    from catch.core.models import SyncState

    for source in ("withings", "whoop", "garmin", "concept2"):
        out = pub_client.post(f"/api/sync/{source}", headers=A).json()
        assert "error" not in out and "skipped" in out, (source, out)
    with Session(pub_engine) as s:
        assert s.execute(select(SyncState).execution_options(tenant_unscoped=True)).scalars().all() == []


def test_server_details_are_not_readable_by_users(pub_client):
    body = pub_client.get("/api/status", headers=A).json()
    assert body["disk_total_bytes"] == 0 and body["uptime_seconds"] == 0 and body["backup"] is None and body["db_size_bytes"] == 0
