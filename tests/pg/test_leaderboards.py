"""Session 26 on the real Postgres runtime path: the global leaderboard tables are reachable only by `catch_api` through
leaderboard_store (a fresh Session under tenant.system_detached()), never by `authenticated`, and the moderation log is
append-only. The SQLite suite proves the logic; this proves the grants, forced RLS and the detach policy that SQLite cannot."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlmodel import Session

from catch.core import config, tenant
from catch.core.models import ProviderConnection
from catch.sync import leaderboards as svc
from catch.sync.upsert import upsert_activity
from tests.pg.conftest import signup
from tests.pg.test_runtime import app  # noqa: F401  (the fixture: the real app on the catch_api engine)

pytestmark = pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")

GLOBAL = ("public_athletes", "public_entries", "moderation_events", "result_reports", "appeals")  # clubs/club_members became membership-scoped in 0006 (tests/pg/test_clubs.py)


def _wipe(admin) -> None:
    with admin.begin() as conn:
        for t in ("appeals", "result_reports", "moderation_events", "public_entries", "public_athletes"):
            conn.execute(text(f"DELETE FROM catch.{t}"))


@pytest.fixture()
def board_env(app, runtime, admin, monkeypatch):  # noqa: F811
    _wipe(admin)
    monkeypatch.setattr(svc, "_c2_profile", lambda session: {})
    monkeypatch.setattr("catch.api.routes_leaderboards.limits.check_rate", lambda owner, bucket="chat": None)
    previous = config.settings.moderator_ids
    yield app
    object.__setattr__(config.settings, "moderator_ids", previous)
    _wipe(admin)


def _seed_result(runtime, user, ext="9001", account="4242"):
    with tenant.use_owner(user.id), Session(runtime) as s:
        s.add(ProviderConnection(provider="concept2", auth_method="personal_token", account_id=account, last4="abcd"))
        s.commit()
        a = upsert_activity(
            s, "concept2", ext, type="rower", workout_type="FixedDistanceSplits", start=datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc),
            duration=390.4, distance=2000, c2_user_id=account, c2_verified=True, c2_weight_class="H",
            raw_json=json.dumps({"id": ext, "user_id": int(account), "verified": True, "weight_class": "H"}),
        )
        return a.id


def test_the_grants_are_what_the_design_says(admin):
    with admin.connect() as conn:
        def priv(role, table, p):
            return conn.execute(text("SELECT has_table_privilege(:r, :t, :p)"), {"r": role, "t": f"catch.{table}", "p": p}).scalar()

        for t in GLOBAL:
            assert not priv("authenticated", t, "SELECT"), t
            assert not priv("authenticated", t, "INSERT"), t
            assert priv("catch_api", t, "SELECT"), t
        assert not priv("catch_api", "moderation_events", "DELETE")
        assert priv("catch_api", "moderation_events", "INSERT")
        assert conn.execute(text("SELECT has_column_privilege('catch_api','catch.moderation_events','subject_owner_id','UPDATE')")).scalar()
        assert not conn.execute(text("SELECT has_column_privilege('catch_api','catch.moderation_events','reason_text','UPDATE')")).scalar()
        assert not conn.execute(text("SELECT has_column_privilege('catch_api','catch.moderation_events','to_status','UPDATE')")).scalar()


def test_publish_report_moderate_appeal_and_delete_through_real_roles(board_env, runtime, admin):
    client = board_env
    a, b, c, d, mod = (signup(n) for n in ("lb-a", "lb-b", "lb-c", "lb-d", "lb-mod"))
    object.__setattr__(config.settings, "moderator_ids", mod.id)
    act = _seed_result(runtime, a)

    r = client.post("/api/leaderboards/me/opt-in", headers=a.headers, json={"confirm": True, "display_mode": "handle", "handle": "PgRiver", "attest_min_age": True})
    assert r.status_code == 200, r.text
    ref = {"kind": "concept2_result", "id": act}
    p = client.post("/api/leaderboards/publications/preview", headers=a.headers, json={"ref": ref, "prefs": {}})
    assert p.status_code == 200, p.text
    pub = client.post("/api/leaderboards/publications", headers=a.headers, json={"ref": ref, "prefs": {}, "confirm": True, "preview_hash": p.json()["preview_hash"]})
    assert pub.status_code == 200, pub.text
    entry = pub.json()["entry"]["entry_id"]
    assert client.post("/api/leaderboards/publications", headers=a.headers, json={"ref": ref, "prefs": {}, "confirm": True, "preview_hash": p.json()["preview_hash"]}).status_code == 409

    # another account reads it through catch_api, and nothing private or identifying comes with it
    seen = client.get("/api/leaderboards/boards/2000m", headers=b.headers)
    assert seen.status_code == 200 and seen.json()["total"] == 1
    body = json.dumps(seen.json())
    assert a.id not in body and "4242" not in body and "9001" not in body and "2026-10-14" not in body

    # the authenticated role itself cannot reach the table, even if a query tried
    with tenant.use_owner(b.id), Session(runtime) as s:
        with pytest.raises(Exception, match="permission denied"):
            s.execute(text("SELECT count(*) FROM public_entries"))

    # the moderation log is append-only for the application role
    with runtime.begin() as conn:
        with pytest.raises(Exception, match="permission denied"):
            conn.execute(text("DELETE FROM catch.moderation_events"))
    with runtime.begin() as conn:
        with pytest.raises(Exception, match="permission denied"):
            conn.execute(text("UPDATE catch.moderation_events SET reason_text = 'edited'"))

    # three distinct reporters hide it for review, recorded with a reason
    for u in (b, c, d):
        rr = client.post(f"/api/leaderboards/entries/{entry}/report", headers=u.headers, json={"reason": "not_a_real_result", "detail": "looks off"})
        assert rr.status_code == 200, rr.text
    assert client.get("/api/leaderboards/boards/2000m", headers=b.headers).json()["total"] == 0

    # a moderator acts with a reason, the athlete appeals, the moderator overturns
    assert client.get("/api/moderation/queue", headers=a.headers).status_code == 404
    assert client.get("/api/moderation/queue", headers=mod.headers).status_code == 200
    rm = client.post(f"/api/moderation/entries/{entry}/action", headers=mod.headers, json={"action": "remove", "reason": "Does not match the logbook."})
    assert rm.status_code == 200, rm.text
    ap = client.post(f"/api/leaderboards/entries/{entry}/appeal", headers=a.headers, json={"text": "It is my result."})
    assert ap.status_code == 200, ap.text
    res = client.post(f"/api/moderation/appeals/{ap.json()['id']}/resolve", headers=mod.headers, json={"outcome": "overturned", "reason": "Verified against the logbook."})
    assert res.status_code == 200, res.text
    assert client.get("/api/leaderboards/boards/2000m", headers=b.headers).json()["total"] == 1
    mine = client.get("/api/leaderboards/me/moderation", headers=a.headers).json()
    assert [e["to_status"] for e in mine["events"]][0] == "active" and len(mine["events"]) == 3

    # deleting the account removes the public rows but keeps the audit trail without the person
    with admin.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM catch.moderation_events")).scalar()
    assert client.request("DELETE", "/api/account", headers=a.headers, json={"confirm": "DELETE"}).status_code == 200
    with admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM catch.public_entries")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM catch.public_athletes")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM catch.moderation_events")).scalar() == before
        assert conn.execute(text("SELECT count(*) FROM catch.moderation_events WHERE subject_owner_id = :o"), {"o": a.id}).scalar() == 0
    assert client.get("/api/leaderboards/boards/2000m", headers=b.headers).json()["total"] == 0
