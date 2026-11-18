"""Session 26 (docs/leaderboards.md): publishing, ranking through the API, categories, duplicates, privacy, moderation and
appeals — on the public deployment with several users. Concept2 data is the repo's synthetic fixtures' shape; nothing live."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from catch.core import config, tenant
from catch.core.models import Activity, BodyComp, DailyWellness, ProviderConnection
from catch.sync import leaderboard_store as store
from catch.sync import leaderboards as svc
from catch.sync.upsert import upsert_activity
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

ALICE, BOB = kit.ALICE, kit.BOB
CAROL, DAVE, ERIN = (f"{n}{n}{n}{n}{n}{n}{n}{n}-{n}{n}{n}{n}-4{n}{n}{n}-8{n}{n}{n}-{n * 12}" for n in "345")
MOD = "99999999-9999-4999-8999-999999999999"
ALL = (ALICE, BOB, CAROL, DAVE, ERIN, MOD)
UTC = timezone.utc


@pytest.fixture()
def env(pub_client, pub_engine, monkeypatch):
    profiles: dict = {}
    monkeypatch.setattr(svc, "_c2_profile", lambda session: profiles.get(tenant.current_owner(), {}))
    monkeypatch.setattr("catch.api.routes_leaderboards.limits.check_rate", lambda owner, bucket="chat": None)
    for sub in ALL:
        assert pub_client.get("/api/me", headers=bearer(sub)).status_code == 200
    previous = config.settings.moderator_ids
    object.__setattr__(config.settings, "moderator_ids", MOD)
    yield SimpleNamespace(c=pub_client, engine=pub_engine, profiles=profiles)
    object.__setattr__(config.settings, "moderator_ids", previous)


def seed(env, owner, ext, *, account="1", verified=True, distance=2000, duration=390.4, wtype="FixedDistanceSplits", wc="H", day=14, connect=True, extra=None):
    with tenant.use_owner(owner), Session(env.engine) as s:
        if connect and s.get(ProviderConnection, tenant.pk("concept2")) is None:
            s.add(ProviderConnection(provider="concept2", auth_method="personal_token", account_id=account, last4="abcd"))
            s.commit()
        a = upsert_activity(
            s, "concept2", str(ext), type="rower", workout_type=wtype, start=datetime(2026, 10, day, 7, 0, tzinfo=UTC), duration=duration,
            distance=distance, c2_user_id=account, c2_verified=verified, c2_weight_class=wc,
            raw_json=json.dumps({"id": ext, "user_id": int(account), "verified": verified, "weight_class": wc, "date": f"2026-10-{day:02d} 07:30:00", "timezone": "America/New_York"}),
            **(extra or {}),
        )
        return a.id


def join(env, sub, handle=None, **extra):
    body = {"confirm": True, "display_mode": "handle" if handle else "anonymous", "attest_min_age": True, **extra}
    if handle:
        body["handle"] = handle
    r = env.c.post("/api/leaderboards/me/opt-in", headers=bearer(sub), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def ref(act_id):
    return {"kind": "concept2_result", "id": act_id}


def preview(env, sub, act_id, **prefs):
    return env.c.post("/api/leaderboards/publications/preview", headers=bearer(sub), json={"ref": ref(act_id), "prefs": prefs})


def publish(env, sub, act_id, **prefs):
    p = preview(env, sub, act_id, **prefs)
    assert p.status_code == 200, p.text
    r = env.c.post("/api/leaderboards/publications", headers=bearer(sub), json={"ref": ref(act_id), "prefs": prefs, "confirm": True, "preview_hash": p.json()["preview_hash"]})
    return r


def athlete(env, sub, handle, ext, *, account, duration=400.0, **kw):
    join(env, sub, handle)
    act = seed(env, sub, ext, account=account, duration=duration, **kw)
    r = publish(env, sub, act)
    assert r.status_code == 200, r.text
    return r.json()["entry"]["entry_id"], act


def board(env, sub, key="2000m", **params):
    r = env.c.get(f"/api/leaderboards/boards/{key}", headers=bearer(sub), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def events(owner):
    return store.my_events(owner)


# ------------------------------------------------------------------ availability and consent

def test_leaderboards_do_not_exist_on_a_personal_install(client):
    from tests.conftest import TEST_PASSWORD

    client.post("/api/login", json={"password": TEST_PASSWORD})
    assert client.get("/api/leaderboards/boards").status_code == 404
    assert client.get("/api/leaderboards/me").status_code == 404
    assert client.get("/api/moderation/queue").status_code == 404


def test_an_unauthenticated_caller_gets_nothing(env):
    assert env.c.get("/api/leaderboards/boards/2000m").status_code == 401


def test_opting_in_needs_an_explicit_confirmation(env):
    r = env.c.post("/api/leaderboards/me/opt-in", headers=bearer(ALICE), json={"handle": "River"})
    assert r.status_code == 422
    assert env.c.get("/api/leaderboards/me", headers=bearer(ALICE)).json()["settings"]["opted_in"] is False


def test_nothing_can_be_published_before_opting_in(env):
    act = seed(env, ALICE, 1)
    assert preview(env, ALICE, act).status_code == 403


def test_publishing_needs_the_age_attestation_when_no_age_is_known(env):
    join(env, ALICE, "River", attest_min_age=False)
    act = seed(env, ALICE, 1)
    r = preview(env, ALICE, act)
    assert r.status_code == 403 and "age" in r.json()["detail"].lower()
    env.c.put("/api/leaderboards/me/settings", headers=bearer(ALICE), json={"attest_min_age": True})
    assert preview(env, ALICE, act).status_code == 200


def test_opting_out_withdraws_every_entry_with_a_recorded_reason(env):
    entry, _ = athlete(env, ALICE, "River", 1, account="1")
    r = env.c.post("/api/leaderboards/me/opt-out", headers=bearer(ALICE), json={"confirm": False})
    assert r.status_code == 422 and board(env, BOB)["total"] == 1
    assert env.c.post("/api/leaderboards/me/opt-out", headers=bearer(ALICE), json={"confirm": True}).status_code == 200
    assert board(env, BOB)["total"] == 0
    assert [e["reason_code"] for e in events(ALICE)] == ["user_opted_out"]
    state = env.c.get("/api/leaderboards/me", headers=bearer(ALICE)).json()
    assert state["settings"]["opted_in"] is False and state["publications"][0]["status"] == "withdrawn"
    assert env.c.get(f"/api/leaderboards/athletes/{state['athlete']['athlete_id']}", headers=bearer(BOB)).status_code == 404


# ------------------------------------------------------------------ publish flow

def test_publishing_needs_confirm_and_the_preview_the_athlete_saw(env):
    join(env, ALICE, "River")
    act = seed(env, ALICE, 1)
    p = preview(env, ALICE, act).json()
    body = {"ref": ref(act), "prefs": {}, "preview_hash": p["preview_hash"]}
    assert env.c.post("/api/leaderboards/publications", headers=bearer(ALICE), json=body).status_code == 422  # no confirm
    stale = env.c.post("/api/leaderboards/publications", headers=bearer(ALICE), json={**body, "confirm": True, "preview_hash": "0" * 64})
    assert stale.status_code == 409
    assert board(env, BOB)["total"] == 0
    ok = env.c.post("/api/leaderboards/publications", headers=bearer(ALICE), json={**body, "confirm": True})
    assert ok.status_code == 200 and board(env, BOB)["total"] == 1


def test_the_preview_is_exactly_what_gets_published(env):
    join(env, ALICE, "River")
    act = seed(env, ALICE, 1)
    shown = preview(env, ALICE, act, date_precision="month").json()["entry"]
    published = publish(env, ALICE, act, date_precision="month").json()["entry"]
    assert {**shown, "entry_id": None} == {**published, "entry_id": None}
    assert board(env, BOB)["entries"][0]["date_label"] == "2026-10"


def test_a_result_that_is_not_exactly_a_board_distance_cannot_be_published(env):
    join(env, ALICE, "River")
    assert preview(env, ALICE, seed(env, ALICE, 1, distance=1960)).status_code == 422
    assert preview(env, ALICE, seed(env, ALICE, 2, wtype="JustRow")).status_code == 422
    assert preview(env, ALICE, seed(env, ALICE, 3, wtype="FixedDistanceInterval")).status_code == 422


def test_withdrawing_needs_confirmation_and_leaves_an_event(env):
    entry, _ = athlete(env, ALICE, "River", 1, account="1")
    url = f"/api/leaderboards/publications/{entry}/withdraw"
    assert env.c.post(url, headers=bearer(ALICE), json={"confirm": False}).status_code == 422
    assert board(env, BOB)["total"] == 1
    assert env.c.post(url, headers=bearer(ALICE), json={"confirm": True}).status_code == 200
    assert board(env, BOB)["total"] == 0
    assert [(e["to_status"], e["actor_kind"], e["reason_code"]) for e in events(ALICE)] == [("withdrawn", "user", "user_withdrawn")]


def test_a_note_is_public_only_when_the_athlete_says_so(env):
    join(env, ALICE, "River")
    act = seed(env, ALICE, 1)
    publish(env, ALICE, act, note="PB after a long block", note_public=False)
    assert board(env, BOB)["entries"][0]["note"] is None
    entry = env.c.get("/api/leaderboards/me", headers=bearer(ALICE)).json()["publications"][0]["entry_id"]
    r = env.c.patch(f"/api/leaderboards/publications/{entry}", headers=bearer(ALICE), json={"note_public": True})
    assert r.status_code == 200 and board(env, BOB)["entries"][0]["note"] == "PB after a long block"
    assert env.c.patch(f"/api/leaderboards/publications/{entry}", headers=bearer(ALICE), json={"note": "see www.example.com", "note_public": True}).status_code == 422


# ------------------------------------------------------------------ ranking through the API

def test_verified_results_rank_with_ties_and_unverified_ones_are_filtered_out_by_default(env):
    athlete(env, ALICE, "Alpha", 1, account="1", duration=400.0)
    athlete(env, BOB, "Bravo", 2, account="2", duration=400.0)
    athlete(env, CAROL, "Charlie", 3, account="3", duration=410.5)
    athlete(env, DAVE, "Delta", 4, account="4", duration=380.0, verified=False)
    data = board(env, ERIN)
    assert [e["rank"] for e in data["entries"]] == [1, 1, 3] and data["total"] == 3
    assert {e["name"] for e in data["entries"]} == {"Alpha", "Bravo", "Charlie"}
    assert data["unverified"] == [] and "Delta" not in json.dumps(data)
    both = board(env, ERIN, verification="include_unverified")
    assert [(e["name"], e["rank"], e["verification"]) for e in both["unverified"]] == [("Delta", 1, "provider_linked")]
    assert [e["rank"] for e in both["entries"]] == [1, 1, 3]  # the unverified time never displaces a verified row
    assert both["context"]["ties"] and both["context"]["verification"] == "include_unverified"


def test_the_viewers_own_row_is_flagged_and_pinned(env):
    athlete(env, ALICE, "Alpha", 1, account="1", duration=400.0)
    athlete(env, BOB, "Bravo", 2, account="2", duration=420.0)
    data = board(env, BOB)
    assert data["you"]["name"] == "Bravo" and data["you"]["rank"] == 2
    assert [e["is_you"] for e in data["entries"]] == [False, True]


def test_a_timed_board_ranks_by_distance(env):
    for sub, name, acct, dist in ((ALICE, "Alpha", "1", 8000), (BOB, "Bravo", "2", 8200)):
        join(env, sub, name)
        act = seed(env, sub, int(acct), account=acct, distance=dist, duration=1800.0, wtype="FixedTimeSplits")
        assert publish(env, sub, act).status_code == 200
    rows = board(env, CAROL, "30min")["entries"]
    assert [(r["name"], r["result"], r["rank"]) for r in rows] == [("Bravo", "8,200 m", 1), ("Alpha", "8,000 m", 2)]


# ------------------------------------------------------------------ duplicates

def test_one_result_cannot_be_published_twice_even_from_two_catch_accounts(env):
    _, act = athlete(env, ALICE, "Alpha", 1, account="1")
    assert publish(env, ALICE, act).status_code == 409  # already published by the same athlete
    join(env, BOB, "Bravo")
    bobs = seed(env, BOB, 1, account="1")  # the same Concept2 account + result id synced into a second Catch account
    r = publish(env, BOB, bobs)
    assert r.status_code == 409 and "can't be published" in r.json()["detail"]
    assert board(env, CAROL)["total"] == 1
    assert env.c.get("/api/leaderboards/me", headers=bearer(BOB)).json()["publications"] == []


def test_two_catch_accounts_on_one_concept2_account_are_one_athlete_on_the_board(env):
    athlete(env, ALICE, "Alpha", 1, account="1", duration=400.0)
    join(env, BOB, "Bravo")
    assert publish(env, BOB, seed(env, BOB, 2, account="1", duration=395.0)).status_code == 200
    data = board(env, CAROL)
    assert data["total"] == 1 and data["entries"][0]["result"] == "6:35.0"


def test_a_republished_withdrawn_result_is_allowed_again(env):
    entry, act = athlete(env, ALICE, "Alpha", 1, account="1")
    env.c.post(f"/api/leaderboards/publications/{entry}/withdraw", headers=bearer(ALICE), json={"confirm": True})
    assert publish(env, ALICE, act).status_code == 200 and board(env, BOB)["total"] == 1


def test_publishing_has_a_daily_limit_counted_in_the_database(env, monkeypatch):
    monkeypatch.setattr(svc, "PUBLICATIONS_PER_DAY", 1)
    join(env, ALICE, "Alpha")
    assert publish(env, ALICE, seed(env, ALICE, 1)).status_code == 200
    second = seed(env, ALICE, 2, distance=5000, duration=1100.0)
    p = preview(env, ALICE, second).json()
    r = env.c.post("/api/leaderboards/publications", headers=bearer(ALICE), json={"ref": ref(second), "prefs": {}, "confirm": True, "preview_hash": p["preview_hash"]})
    assert r.status_code == 429


# ------------------------------------------------------------------ categories, age, dates, names

def test_self_declared_youth_bands_are_cumulative_under_boards_and_labelled(env):
    join(env, ALICE, "Alpha", self_declared_band="U16", attest_guardian=True, show_age_band=True)
    assert publish(env, ALICE, seed(env, ALICE, 1)).status_code == 200
    assert board(env, BOB, age="U16")["total"] == 1 and board(env, BOB, age="U17")["total"] == 1 and board(env, BOB, age="U19")["total"] == 1
    assert board(env, BOB, age="U15")["total"] == 0 and board(env, BOB, age="30-39")["total"] == 0
    row = board(env, BOB)["entries"][0]
    assert row["age_label"] == "U16" and row["age_provenance"] == "self-declared"


def test_an_age_the_athlete_did_not_agree_to_show_is_neither_shown_nor_filterable(env):
    join(env, ALICE, "Alpha", self_declared_band="30-39")
    assert publish(env, ALICE, seed(env, ALICE, 1)).status_code == 200
    assert board(env, BOB)["entries"][0]["age_label"] is None and board(env, BOB, age="30-39")["total"] == 0


def test_a_concept2_date_of_birth_wins_and_only_the_band_is_kept(env):
    env.profiles[BOB] = {"id": 2, "dob": "1984-03-09"}
    join(env, BOB, "Bravo", show_age_band=True)
    assert publish(env, BOB, seed(env, BOB, 2, account="2")).status_code == 200
    row = board(env, ALICE, age="40-49")["entries"][0]
    assert row["age_label"] == "40-49" and row["age_provenance"] == "as reported to Concept2"
    r = env.c.put("/api/leaderboards/me/settings", headers=bearer(BOB), json={"self_declared_band": "U16"})
    assert r.status_code == 409  # no self-declaring into an easier band once Concept2 has supplied one
    with Session(env.engine) as s:
        for row in s.execute(select(store.PublicEntry)).scalars():
            assert row.age_years is None and row.age_band == "40-49"


def test_under_the_minimum_age_nothing_can_be_published(env):
    env.profiles[ALICE] = {"id": 1, "dob": "2014-06-01"}
    join(env, ALICE, "Alpha")
    r = preview(env, ALICE, seed(env, ALICE, 1))
    assert r.status_code == 403 and "13" in r.json()["detail"]


def test_a_young_athlete_needs_guardian_consent_and_gets_year_only_dates(env):
    env.profiles[ALICE] = {"id": 1, "dob": "2012-01-01"}  # 14 on the result date
    join(env, ALICE, "Alpha", show_age_band=True)
    act = seed(env, ALICE, 1)
    assert "guardian" in preview(env, ALICE, act).json()["detail"].lower()
    env.c.put("/api/leaderboards/me/settings", headers=bearer(ALICE), json={"attest_guardian": True})
    p = preview(env, ALICE, act, date_precision="day").json()
    assert p["entry"]["date_label"] == "2026" and p["entry"]["age_label"] == "U15"
    assert any("under 18" in d for d in p["disclosures"])


def test_dates_are_hidden_unless_consented_and_only_truncated_ones_are_stored(env):
    join(env, ALICE, "Alpha")
    act = seed(env, ALICE, 1)
    assert preview(env, ALICE, act).json()["entry"]["date_label"] is None
    assert preview(env, ALICE, act, date_precision="year").json()["entry"]["date_label"] == "2026"
    publish(env, ALICE, act, date_precision="day")
    with Session(env.engine) as s:
        assert [r.date_label for r in s.execute(select(store.PublicEntry)).scalars()] == ["2026-10-14"]


def test_weight_class_is_opt_in_and_filters_the_lightweight_board(env):
    join(env, ALICE, "Alpha", show_weight_class=True)
    publish(env, ALICE, seed(env, ALICE, 1, wc="L"))
    join(env, BOB, "Bravo")
    publish(env, BOB, seed(env, BOB, 2, account="2", wc="L"))  # lightweight, but did not agree to show it
    rows = board(env, CAROL, weight="lightweight")["entries"]
    assert [r["name"] for r in rows] == ["Alpha"] and rows[0]["weight_class"] == "Lightweight"
    assert {r["weight_class"] for r in board(env, CAROL)["entries"]} == {"Lightweight", None}


def test_handles_are_unique_case_insensitively_and_anonymous_hides_them(env):
    join(env, ALICE, "River")
    r = env.c.post("/api/leaderboards/me/opt-in", headers=bearer(BOB), json={"confirm": True, "handle": "river", "display_mode": "handle", "attest_min_age": True})
    assert r.status_code == 409
    join(env, BOB)  # anonymous
    publish(env, BOB, seed(env, BOB, 2, account="2"))
    assert board(env, ALICE)["entries"][0]["name"] == "Anonymous rower"
    bad = env.c.post("/api/leaderboards/me/opt-in", headers=bearer(CAROL), json={"confirm": True, "handle": "Catch Admin", "display_mode": "handle", "attest_min_age": True})
    assert bad.status_code == 422


def test_filter_values_are_validated(env):
    assert env.c.get("/api/leaderboards/boards/1234m", headers=bearer(ALICE)).status_code == 404
    assert env.c.get("/api/leaderboards/boards/2000m", headers=bearer(ALICE), params={"age": "U12"}).status_code == 422
    assert env.c.get("/api/leaderboards/boards/2000m", headers=bearer(ALICE), params={"verification": "all"}).status_code == 422
    keys = [b["board_key"] for b in env.c.get("/api/leaderboards/boards", headers=bearer(ALICE)).json()["boards"]]
    assert keys == ["500m", "1000m", "2000m", "5000m", "6000m", "30min", "60min"]


def _club(env, club_id, *, visibility, members):
    """members: [(owner_id, include_public_results)] — seeded directly, since club membership is session 27's service (tests/tenancy/test_clubs_*.py)."""
    from catch.core.models import Club, ClubMember, ClubMemberPrefs

    with Session(env.engine) as s:
        s.add(Club(club_id=club_id, name=club_id, name_ci=club_id, visibility=visibility, audience="adult", join_policy="open" if visibility == "public" else "request"))
        s.commit()
        for owner, show in members:
            s.add(ClubMember(club_id=club_id, owner_id=owner, club_audience="adult", role="athlete"))
            s.commit()
            s.add(ClubMemberPrefs(club_id=club_id, owner_id=owner, include_public_results=show))
        s.commit()


def test_the_public_board_club_filter_only_ever_matches_public_clubs_and_members_who_opted_in(env):
    athlete(env, ALICE, "Alpha", 1, account="1")
    athlete(env, BOB, "Bravo", 2, account="2")
    athlete(env, DAVE, "Delta", 4, account="4")
    _club(env, "river-public", visibility="public", members=[(ALICE, True), (BOB, False)])
    _club(env, "river-private", visibility="private", members=[(ALICE, True), (BOB, True)])
    assert {e["name"] for e in board(env, CAROL, club="river-public")["entries"]} == {"Alpha"}  # Bob didn't tick "show my public results"
    assert board(env, CAROL, club="river-private")["total"] == 0  # a private club's membership can't be enumerated through the public board
    assert board(env, CAROL)["total"] == 3
    state = env.c.get("/api/leaderboards/me", headers=bearer(ALICE)).json()
    assert [c["club_id"] for c in state["clubs"]] == ["river-public"]  # the filter offers public clubs only


# ------------------------------------------------------------------ source changes

def test_a_published_result_whose_source_changed_is_hidden_with_a_recorded_reason(env):
    entry, act = athlete(env, ALICE, "Alpha", 1, account="1")
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        a = s.get(Activity, act)
        a.duration = 380.0
        s.commit()
    state = env.c.get("/api/leaderboards/me", headers=bearer(ALICE)).json()
    assert state["publications"][0]["status"] == "hidden"
    assert board(env, BOB)["total"] == 0
    assert [e["reason_code"] for e in events(ALICE)] == ["source_changed"]


# ------------------------------------------------------------------ reports, moderation, appeals

def report(env, sub, entry, reason="not_a_real_result"):
    return env.c.post(f"/api/leaderboards/entries/{entry}/report", headers=bearer(sub), json={"reason": reason, "detail": "looks off"})


def test_reports_dedupe_cannot_target_yourself_and_three_reporters_hide_for_review(env):
    entry, _ = athlete(env, ALICE, "Alpha", 1, account="1")
    assert report(env, ALICE, entry).status_code == 422
    assert report(env, BOB, entry).status_code == 200 and report(env, BOB, entry).status_code == 409
    assert report(env, CAROL, entry).json()["hidden_for_review"] is False
    assert report(env, DAVE, entry).json()["hidden_for_review"] is True
    assert board(env, ERIN)["total"] == 0
    assert [(e["actor_kind"], e["reason_code"], e["to_status"]) for e in events(ALICE)] == [("system", "report_threshold", "hidden")]
    assert report(env, ERIN, entry).status_code == 404  # no longer public, nothing to report
    assert env.c.post(f"/api/leaderboards/entries/{entry}/report", headers=bearer(BOB), json={"reason": "spite"}).status_code in (404, 409, 422)


def test_reporting_has_a_daily_limit_counted_in_the_database(env, monkeypatch):
    monkeypatch.setattr(store, "REPORTS_PER_DAY", 1)
    one, _ = athlete(env, ALICE, "Alpha", 1, account="1")
    two, _ = athlete(env, CAROL, "Charlie", 3, account="3")
    assert report(env, BOB, one).status_code == 200
    assert report(env, BOB, two).status_code == 429


def test_only_listed_moderators_can_see_the_queue(env):
    assert env.c.get("/api/moderation/queue", headers=bearer(ALICE)).status_code == 404
    assert env.c.get("/api/moderation/queue", headers=bearer(MOD)).status_code == 200
    assert env.c.get("/api/leaderboards/me", headers=bearer(MOD)).json()["is_moderator"] is True
    assert env.c.get("/api/leaderboards/me", headers=bearer(ALICE)).json()["is_moderator"] is False


def test_a_moderator_action_needs_a_reason_and_is_recorded_and_appealable(env):
    entry, _ = athlete(env, ALICE, "Alpha", 1, account="1")
    report(env, BOB, entry)
    def act(**b):
        return env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(MOD), json=b)

    assert act(action="remove", reason="  ").status_code == 422
    assert board(env, ERIN)["total"] == 1  # nothing changed without a reason
    assert act(action="remove", reason="The time doesn't match Concept2's records.").status_code == 200
    assert board(env, ERIN)["total"] == 0
    mine = env.c.get("/api/leaderboards/me/moderation", headers=bearer(ALICE)).json()
    assert [(e["to_status"], e["actor_kind"], e["reason_text"]) for e in mine["events"]] == [("removed", "moderator", "The time doesn't match Concept2's records.")]
    assert "reporter" not in json.dumps(mine) and BOB not in json.dumps(mine)

    def appeal(**b):
        return env.c.post(f"/api/leaderboards/entries/{entry}/appeal", headers=bearer(ALICE), json=b)

    assert appeal(text="").status_code == 422
    first = appeal(text="This is my result; here is the screenshot.")
    assert first.status_code == 200 and appeal(text="again").status_code == 409
    queue = env.c.get("/api/moderation/queue", headers=bearer(MOD)).json()
    assert [a["id"] for a in queue["appeals"]] == [first.json()["id"]]
    def resolve(**b):
        return env.c.post(f"/api/moderation/appeals/{first.json()['id']}/resolve", headers=bearer(MOD), json=b)

    assert resolve(outcome="overturned", reason="").status_code == 422
    assert resolve(outcome="overturned", reason="Verified against the Concept2 logbook.").status_code == 200
    assert board(env, ERIN)["total"] == 1
    trail = events(ALICE)
    assert [(e["to_status"], e["reason_code"]) for e in trail] == [("active", "appeal_overturned"), ("removed", "moderator_remove")]
    assert env.c.get("/api/leaderboards/me/moderation", headers=bearer(ALICE)).json()["appeals"][0]["status"] == "overturned"


def test_an_upheld_appeal_keeps_the_decision_and_is_recorded(env):
    entry, _ = athlete(env, ALICE, "Alpha", 1, account="1")
    env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(MOD), json={"action": "hide", "reason": "Under review."})
    a = env.c.post(f"/api/leaderboards/entries/{entry}/appeal", headers=bearer(ALICE), json={"text": "Please restore it."}).json()
    assert env.c.post(f"/api/moderation/appeals/{a['id']}/resolve", headers=bearer(MOD), json={"outcome": "upheld", "reason": "Still inconsistent."}).status_code == 200
    assert board(env, ERIN)["total"] == 0
    assert [e["reason_code"] for e in events(ALICE)] == ["appeal_upheld", "moderator_hide"]


def test_only_a_hidden_or_removed_result_can_be_appealed_and_only_by_its_owner(env):
    entry, _ = athlete(env, ALICE, "Alpha", 1, account="1")
    assert env.c.post(f"/api/leaderboards/entries/{entry}/appeal", headers=bearer(ALICE), json={"text": "x"}).status_code == 422
    env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(MOD), json={"action": "hide", "reason": "Under review."})
    assert env.c.post(f"/api/leaderboards/entries/{entry}/appeal", headers=bearer(BOB), json={"text": "x"}).status_code == 404


def test_an_athlete_cannot_change_their_own_entrys_status(env):
    entry, _ = athlete(env, ALICE, "Alpha", 1, account="1")
    env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(MOD), json={"action": "remove", "reason": "Not a real result."})
    r = env.c.patch(f"/api/leaderboards/publications/{entry}", headers=bearer(ALICE), json={"status": "active", "note_public": True})
    assert r.status_code in (200, 422)
    assert board(env, BOB)["total"] == 0
    assert env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(ALICE), json={"action": "restore", "reason": "mine"}).status_code == 404
    assert env.c.post(f"/api/leaderboards/publications/{entry}/withdraw", headers=bearer(BOB), json={"confirm": True}).status_code == 404


def test_a_moderator_cannot_moderate_their_own_result(env):
    entry, _ = athlete(env, MOD, "Referee", 9, account="9")
    r = env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(MOD), json={"action": "hide", "reason": "self"})
    assert r.status_code == 403 and board(env, ALICE)["total"] == 1


def test_every_status_change_in_these_flows_left_an_event(env):
    entry, _ = athlete(env, ALICE, "Alpha", 1, account="1")
    for sub in (BOB, CAROL, DAVE):
        report(env, sub, entry)
    env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(MOD), json={"action": "restore", "reason": "Reports were mistaken."})
    env.c.post(f"/api/leaderboards/publications/{entry}/withdraw", headers=bearer(ALICE), json={"confirm": True})
    assert [e["reason_code"] for e in events(ALICE)] == ["user_withdrawn", "moderator_restore", "report_threshold"]
    assert all(e["reason_text"] for e in events(ALICE))


def test_deleting_an_account_removes_public_rows_but_keeps_an_anonymous_audit_trail(env):
    entry, _ = athlete(env, ALICE, "Alpha", 1, account="1")
    report(env, BOB, entry)
    env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(MOD), json={"action": "hide", "reason": "Under review."})
    store.delete_owner_data(ALICE)
    with store.store() as s:
        assert s.execute(select(store.PublicEntry)).first() is None and s.execute(select(store.PublicAthlete)).first() is None
        kept = s.execute(select(store.ModerationEvent)).scalars().all()
        assert len(kept) == 1 and kept[0].subject_owner_id is None and kept[0].reason_code == "moderator_hide"
        assert s.execute(select(store.ResultReport)).scalars().one().reporter_id == BOB


# ------------------------------------------------------------------ privacy

SENTINELS = ["97.3171", "17.8643", "73.4137", "18.2749", "171.3719", "7351.25", "311.77", "90417213", "55290183", "1984-03-09", "2026-10-14", "2026-10", "alice-private-note"]


def test_no_private_metric_or_provider_identifier_ever_reaches_another_users_response(env):
    env.profiles[ALICE] = {"id": 55290183, "dob": "1984-03-09"}
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        s.add(DailyWellness(date=datetime(2026, 10, 14).date(), hrv_rmssd=97.3171, respiration=17.8643, resting_hr=41, stress=88))
        s.add(BodyComp(external_id="x", ts=datetime(2026, 10, 14, tzinfo=UTC), weight_kg=73.4137, fat_pct=18.2749))
        s.commit()
    join(env, ALICE, "Alpha", show_age_band=True, show_weight_class=True)
    act = seed(env, ALICE, 90417213, account="55290183", extra={"avg_hr": 171.3719, "calories": 7351.25, "avg_power": 311.77})
    p = preview(env, ALICE, act, note="alice-private-note", note_public=False)
    assert p.status_code == 200
    publish(env, ALICE, act, note="alice-private-note", note_public=False)
    athlete_id = env.c.get("/api/leaderboards/me", headers=bearer(ALICE)).json()["athlete"]["athlete_id"]

    seen = [p.text]
    for key in ("2000m", "500m", "30min"):
        seen.append(env.c.get(f"/api/leaderboards/boards/{key}", headers=bearer(BOB), params={"verification": "include_unverified"}).text)
    seen.append(env.c.get(f"/api/leaderboards/athletes/{athlete_id}", headers=bearer(BOB)).text)
    seen.append(env.c.get("/api/leaderboards/boards", headers=bearer(BOB)).text)
    seen.append(env.c.get("/api/leaderboards/me", headers=bearer(BOB)).text)
    seen.append(env.c.get("/api/leaderboards/me/results", headers=bearer(BOB)).text)
    blob = "\n".join(seen)
    for sentinel in SENTINELS:
        assert sentinel not in blob, f"{sentinel!r} leaked into a response"
    assert "Alpha" in blob  # the public parts are there


def test_public_projection_columns_and_serializer_keys_are_an_allowlist(env):
    from catch.analytics import leaderboards as lb

    athlete(env, ALICE, "Alpha", 1, account="1")
    view = board(env, BOB)["entries"][0]
    assert set(view) <= set(lb.PUBLIC_RANKED_KEYS) | {"is_you"}
    banned = ("hr", "hrv", "sleep", "weight_kg", "recovery", "strain", "calories", "watts", "nutrition", "fat", "dob", "birth", "email", "owner")
    for key in view:
        assert not any(b in key for b in banned), key
    columns = {c.name for c in store.PublicEntry.__table__.columns}
    assert not any(b in c for c in columns for b in ("hr", "hrv", "sleep", "weight_kg", "recovery", "strain", "calories", "nutrition", "dob", "birth", "email"))


def test_the_profile_preview_is_the_public_profile(env):
    athlete(env, ALICE, "Alpha", 1, account="1")
    mine = env.c.get("/api/leaderboards/me/profile-preview", headers=bearer(ALICE)).json()
    theirs = env.c.get(f"/api/leaderboards/athletes/{mine['athlete_id']}", headers=bearer(BOB)).json()
    assert {k: v for k, v in mine.items() if k != "is_preview"} == theirs
    assert theirs["name"] == "Alpha" and theirs["results"][0]["board_key"] == "2000m"


def test_my_results_lists_the_athletes_own_states_without_publishing_anything(env):
    join(env, ALICE, "Alpha")
    seed(env, ALICE, 1, verified=True)
    seed(env, ALICE, 2, distance=5000, duration=1100.0, verified=False)
    seed(env, ALICE, 3, distance=1960)  # not a board
    rows = env.c.get("/api/leaderboards/me/results", headers=bearer(ALICE)).json()["results"]
    assert {(r["board_key"], r["verification"], r["published"]) for r in rows} == {("2000m", "verified", None), ("5000m", "provider_linked", None)}
    assert all(r["verification_explained"] for r in rows)
    assert board(env, BOB)["total"] == 0


# ------------------------------------------------------------------ the coach / MCP tools

def _tool(env, sub, name, **args):
    from catch.coach import tools as coach_tools
    from catch.core.principal import athlete_for

    with tenant.use_owner(sub), Session(env.engine) as s:
        return coach_tools.call_tool(s, name, args, {"principal": athlete_for(sub), "via": "mcp"})


def test_the_tools_return_public_information_only_and_no_private_metric(env):
    env.profiles[ALICE] = {"id": 55290183, "dob": "1984-03-09"}
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        s.add(DailyWellness(date=datetime(2026, 10, 14).date(), hrv_rmssd=97.3171, respiration=17.8643))
        s.add(BodyComp(external_id="x", ts=datetime(2026, 10, 14, tzinfo=UTC), weight_kg=73.4137))
        s.commit()
    join(env, ALICE, "Alpha", show_age_band=True)
    act = seed(env, ALICE, 90417213, account="55290183", extra={"avg_hr": 171.3719, "calories": 7351.25, "avg_power": 311.77})
    assert publish(env, ALICE, act, date_precision="year").status_code == 200
    athlete_id = env.c.get("/api/leaderboards/me", headers=bearer(ALICE)).json()["athlete"]["athlete_id"]

    out = [
        _tool(env, BOB, "get_leaderboards"),
        _tool(env, BOB, "get_leaderboards", board="2000m", verification="include_unverified"),
        _tool(env, BOB, "get_public_athlete_profile", athlete_id=athlete_id),
        _tool(env, ALICE, "get_public_athlete_profile"),
        _tool(env, ALICE, "get_verified_results"),
    ]
    blob = json.dumps(out)
    for sentinel in [s for s in SENTINELS if s not in ("2026-10",)]:
        assert sentinel not in blob, f"{sentinel!r} leaked through a tool"
    assert out[1]["entries"][0]["name"] == "Alpha" and out[2]["results"][0]["verification"] == "verified"
    assert out[3]["name"] == "Alpha" and out[4]["results"][0]["published"] == "active"
    assert "performed_on" not in blob


def test_get_verified_results_defaults_to_verified_and_never_publishes(env):
    join(env, ALICE, "Alpha")
    seed(env, ALICE, 1, verified=True)
    seed(env, ALICE, 2, distance=5000, duration=1100.0, verified=False)
    assert [r["board_key"] for r in _tool(env, ALICE, "get_verified_results")["results"]] == ["2000m"]
    assert [r["verification"] for r in _tool(env, ALICE, "get_verified_results", state="provider_linked")["results"]] == ["provider_linked"]
    assert board(env, BOB)["total"] == 0


def test_a_tool_for_an_unknown_board_or_athlete_fails_cleanly(env):
    with pytest.raises(ValueError):
        _tool(env, ALICE, "get_leaderboards", board="2000m", age="U12")
    with pytest.raises(ValueError):
        _tool(env, ALICE, "get_public_athlete_profile", athlete_id="nope")


# ------------------------------------------------------------------ ownership of the source

def test_another_users_result_cannot_be_previewed_or_published(env):
    join(env, BOB, "Bravo")
    alices = seed(env, ALICE, 1)
    assert preview(env, BOB, alices).status_code == 404
    piece = env.c.post("/api/leaderboards/publications/preview", headers=bearer(BOB), json={"ref": {"kind": "piece", "id": 424242}, "prefs": {}})
    assert piece.status_code == 404
    assert board(env, CAROL)["total"] == 0


def test_an_oauth_connection_without_a_stored_account_id_is_resolved_from_the_profile_once(env):
    env.profiles[ALICE] = {"id": 1}
    join(env, ALICE, "Alpha")
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        s.add(ProviderConnection(provider="concept2", auth_method="oauth", account_id=None, last4=""))
        s.commit()
    seed(env, ALICE, 1, account="1", connect=False)
    seed(env, ALICE, 2, account="1", connect=False, distance=5000, duration=1100.0)
    rows = env.c.get("/api/leaderboards/me/results", headers=bearer(ALICE)).json()["results"]
    assert {r["verification"] for r in rows} == {"verified"}
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        assert s.get(ProviderConnection, tenant.pk("concept2")).account_id == "1"


def test_a_result_from_another_concept2_account_is_never_verified_through_this_connection(env):
    join(env, ALICE, "Alpha")
    seed(env, ALICE, 1, account="1")
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        a = s.execute(select(Activity)).scalars().one()
        a.c2_user_id = "999"  # a result Concept2 attributes to somebody else
        s.commit()
    assert env.c.get("/api/leaderboards/me/results", headers=bearer(ALICE)).json()["results"][0]["verification"] == "provider_linked"


# ------------------------------------------------------------------ a moderation decision can't be undone by withdrawing

def _entry_status(env, entry):
    with store.store() as s:
        row = s.get(store.PublicEntry, entry)
        return row.status if row else None


def test_withdrawing_a_removed_entry_keeps_it_closed_and_it_cannot_be_republished(env):
    entry, act = athlete(env, ALICE, "Alpha", 1, account="1")
    env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(MOD), json={"action": "remove", "reason": "Not a real result."})
    r = env.c.post(f"/api/leaderboards/publications/{entry}/withdraw", headers=bearer(ALICE), json={"confirm": True})
    assert r.status_code == 200 and r.json()["withdrawn"] is False and r.json()["kept_for_review"] is True
    assert _entry_status(env, entry) == "removed"
    assert publish(env, ALICE, act).status_code == 409  # the result is still the one a moderator removed
    assert board(env, BOB)["total"] == 0
    assert [e["reason_code"] for e in events(ALICE)] == ["withdrawal_requested", "moderator_remove"]
    # the athlete's way out is the appeal, which still works on the kept entry
    assert env.c.post(f"/api/leaderboards/entries/{entry}/appeal", headers=bearer(ALICE), json={"text": "It is real."}).status_code == 200


def test_a_report_threshold_hide_cannot_be_escaped_by_withdrawing_and_republishing(env):
    entry, act = athlete(env, ALICE, "Alpha", 1, account="1")
    for sub in (BOB, CAROL, DAVE):
        report(env, sub, entry)
    env.c.post(f"/api/leaderboards/publications/{entry}/withdraw", headers=bearer(ALICE), json={"confirm": True})
    assert _entry_status(env, entry) == "hidden"
    assert publish(env, ALICE, act).status_code == 409 and board(env, ERIN)["total"] == 0


def test_opting_out_and_back_in_cannot_clear_a_moderators_decision(env):
    entry, act = athlete(env, ALICE, "Alpha", 1, account="1")
    env.c.post(f"/api/moderation/entries/{entry}/action", headers=bearer(MOD), json={"action": "remove", "reason": "Not a real result."})
    env.c.post("/api/leaderboards/me/opt-out", headers=bearer(ALICE), json={"confirm": True})
    assert _entry_status(env, entry) == "removed"
    join(env, ALICE, "Alpha")
    assert publish(env, ALICE, act).status_code == 409
    # restored by an overturned appeal, it is public again — through a moderator, not through the athlete
    a = env.c.post(f"/api/leaderboards/entries/{entry}/appeal", headers=bearer(ALICE), json={"text": "Please look again."}).json()
    env.c.post(f"/api/moderation/appeals/{a['id']}/resolve", headers=bearer(MOD), json={"outcome": "overturned", "reason": "It checks out."})
    assert board(env, BOB)["total"] == 1


def test_a_source_changed_entry_is_replaced_by_publishing_again_and_can_be_taken_down(env):
    entry, act = athlete(env, ALICE, "Alpha", 1, account="1", duration=400.0)
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        s.get(Activity, act).duration = 380.0
        s.commit()
    row = env.c.get("/api/leaderboards/me/results", headers=bearer(ALICE)).json()["results"][0]
    assert row["published"] == "hidden" and row["can_republish"] is True
    again = publish(env, ALICE, act)
    assert again.status_code == 200 and again.json()["entry"]["entry_id"] != entry
    data = board(env, BOB)
    assert data["total"] == 1 and data["entries"][0]["result"] == "6:20.0"
    assert [e["reason_code"] for e in events(ALICE)] == ["replaced_by_republish", "source_changed"]
    assert _entry_status(env, entry) is None


def test_a_source_changed_entry_can_simply_be_taken_down(env):
    entry, act = athlete(env, ALICE, "Alpha", 1, account="1")
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        s.get(Activity, act).duration = 380.0
        s.commit()
    env.c.get("/api/leaderboards/me", headers=bearer(ALICE))
    r = env.c.post(f"/api/leaderboards/publications/{entry}/withdraw", headers=bearer(ALICE), json={"confirm": True})
    assert r.json()["withdrawn"] is True and _entry_status(env, entry) is None


def test_an_anonymous_athlete_keeps_one_stable_public_id_across_results(env):
    join(env, ALICE)
    publish(env, ALICE, seed(env, ALICE, 1))
    publish(env, ALICE, seed(env, ALICE, 2, distance=5000, duration=1100.0))
    ids = {e["athlete_id"] for key in ("2000m", "5000m") for e in board(env, BOB, key)["entries"]}
    assert len(ids) == 1  # documented: anonymous is a display name, not unlinkability
