"""Session 28 moderation: account restrictions with reasons and appeals, an audit trail for moderator actions and reads, the aal2 gate,
and the report-brigading rule. Public deployment, several real identities."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from catch.core import config, tenant
from catch.core.models import ModeratorAccess, ModerationAction
from catch.sync import account_store, restrictions
from catch.sync import leaderboard_store as store
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

ALICE, BOB = kit.ALICE, kit.BOB
MOD, MOD2 = "99999999-9999-4999-8999-999999999999", "88888888-8888-4888-8888-888888888888"
OTHER = "77777777-7777-4777-8777-777777777777"


@pytest.fixture()
def env(pub_client, pub_engine):
    for sub in (ALICE, BOB, MOD, MOD2, OTHER):
        assert pub_client.get("/api/me", headers=bearer(sub)).status_code == 200
    previous = config.settings.moderator_ids
    object.__setattr__(config.settings, "moderator_ids", f"{MOD},{MOD2}")
    yield SimpleNamespace(c=pub_client, engine=pub_engine)
    object.__setattr__(config.settings, "moderator_ids", previous)


def restrict(env, who=ALICE, scope="publish", **extra):
    return env.c.post("/api/moderation/restrictions", headers=bearer(MOD), json={"user_id": who, "scope": scope, "reason": "Repeated abusive notes", "reason_code": "abuse", **extra})


def test_a_moderator_restricts_one_capability_with_a_reason_and_it_is_enforced(env):
    r = restrict(env, scope="clubs")
    assert r.status_code == 200 and r.json()["active"] is True and r.json()["decided_by"] == "a platform moderator"
    denied = env.c.post("/api/clubs", headers=bearer(ALICE), json={"name": "Fast Crew"})
    assert denied.status_code == 403 and "restricted" in denied.json()["detail"]
    assert env.c.post("/api/leaderboards/me/opt-in", headers=bearer(ALICE), json={"confirm": True}).status_code != 403  # other capabilities untouched
    # never the person's own data: export, deletion and their own records are unaffected
    assert env.c.get("/api/privacy/summary", headers=bearer(ALICE)).status_code == 200
    assert env.c.get("/api/privacy/export", headers=bearer(ALICE)).status_code == 200
    assert env.c.get("/api/wellness", headers=bearer(ALICE)).status_code == 200


def test_the_person_sees_the_restriction_its_reason_and_can_appeal_once(env):
    rid = restrict(env).json()["id"]
    mine = env.c.get("/api/account/restrictions", headers=bearer(ALICE)).json()["restrictions"]
    assert [(m["scope"], m["reason"], m["active"]) for m in mine] == [("publish", "Repeated abusive notes", True)]
    assert env.c.get("/api/account/restrictions", headers=bearer(BOB)).json()["restrictions"] == []  # nobody else's
    appeal = env.c.post(f"/api/account/restrictions/{rid}/appeal", headers=bearer(ALICE), json={"text": "It was a misunderstanding."})
    assert appeal.status_code == 200 and appeal.json()["appeal"]["status"] == "open"
    assert env.c.post(f"/api/account/restrictions/{rid}/appeal", headers=bearer(ALICE), json={"text": "again"}).status_code == 409
    assert env.c.post(f"/api/account/restrictions/{rid}/appeal", headers=bearer(BOB), json={"text": "not mine"}).status_code == 404
    assert env.c.post(f"/api/account/restrictions/{rid}/appeal", headers=bearer(ALICE), json={"text": "  "}).status_code in (400, 409)


def test_a_different_moderator_reviews_the_appeal_and_an_overturn_lifts_it(env):
    rid = restrict(env).json()["id"]
    env.c.post(f"/api/account/restrictions/{rid}/appeal", headers=bearer(ALICE), json={"text": "please look again"})
    same = env.c.post(f"/api/moderation/restrictions/{rid}/resolve", headers=bearer(MOD), json={"outcome": "overturned", "reason": "ok"})
    assert same.status_code == 403  # not the moderator who decided
    done = env.c.post(f"/api/moderation/restrictions/{rid}/resolve", headers=bearer(MOD2), json={"outcome": "overturned", "reason": "On review the notes were fine."})
    assert done.status_code == 200 and done.json()["active"] is False
    assert env.c.post("/api/clubs", headers=bearer(ALICE), json={"name": "x"}).status_code != 403
    kinds = [a["action"] for a in env.c.get("/api/moderation/actions", headers=bearer(MOD)).json()["actions"]]
    assert kinds == ["appeal_overturned", "restrict"]  # newest first, both with reasons


def test_every_moderator_action_needs_a_reason_and_has_limits(env):
    assert env.c.post("/api/moderation/restrictions", headers=bearer(MOD), json={"user_id": ALICE, "scope": "publish", "reason": "  "}).status_code == 400
    assert env.c.post("/api/moderation/restrictions", headers=bearer(MOD), json={"user_id": ALICE, "scope": "everything", "reason": "x"}).status_code == 400
    assert restrict(env, who=MOD).status_code == 403  # not yourself
    assert restrict(env, who=MOD2).status_code == 403  # nor another moderator
    assert restrict(env, who="00000000-0000-4000-8000-000000000000").status_code == 404  # no such account
    assert restrict(env, days=9999).status_code == 400
    rid = restrict(env, days=7).json()["id"]
    assert env.c.post(f"/api/moderation/restrictions/{rid}/lift", headers=bearer(MOD), json={"action": "lift", "reason": ""}).status_code == 400
    assert env.c.post(f"/api/moderation/restrictions/{rid}/lift", headers=bearer(MOD), json={"action": "lift", "reason": "Served."}).status_code == 200
    assert env.c.post(f"/api/moderation/restrictions/{rid}/lift", headers=bearer(MOD), json={"action": "lift", "reason": "again"}).status_code == 409


def test_an_expired_restriction_no_longer_applies(env):
    rid = restrict(env, days=1).json()["id"]
    from datetime import datetime, timedelta, timezone

    from catch.core.models import AccountRestriction

    with store.store() as s:
        row = s.get(AccountRestriction, rid)
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    restrictions.assert_allowed(ALICE, "publish")  # does not raise
    assert env.c.get("/api/account/restrictions", headers=bearer(ALICE)).json()["restrictions"][0]["active"] is False


def test_the_moderation_routes_and_restrictions_are_not_reachable_by_ordinary_users(env):
    for method, path, body in [("GET", "/api/moderation/restrictions", None), ("POST", "/api/moderation/restrictions", {"user_id": BOB, "scope": "clubs", "reason": "x"}), ("GET", "/api/moderation/actions", None)]:
        assert env.c.request(method, path, headers=bearer(ALICE), json=body).status_code == 404


def test_moderator_reads_are_logged_and_the_logs_are_append_only(env):
    env.c.get("/api/moderation/queue", headers=bearer(MOD))
    env.c.get("/api/moderation/restrictions", headers=bearer(MOD))
    env.c.get("/api/moderation/clubs/queue", headers=bearer(MOD2))
    with store.store() as s:
        rows = s.exec(select(ModeratorAccess).order_by(ModeratorAccess.id)).all()
    assert [(r.moderator_id, r.kind) for r in rows] == [(MOD, "queue"), (MOD, "restrictions"), (MOD2, "queue")]
    restrict(env)
    with store.store() as s:
        assert len(s.exec(select(ModerationAction)).all()) == 1


def test_a_moderator_needs_a_second_factor_when_that_is_required(env):
    object.__setattr__(config.settings, "moderator_require_aal2", True)
    try:
        assert env.c.get("/api/moderation/queue", headers=bearer(MOD)).status_code == 403
        assert env.c.get("/api/moderation/queue", headers=bearer(MOD, extra={"aal": "aal2"})).status_code == 200
        assert env.c.get("/api/moderation/queue", headers=bearer(ALICE, extra={"aal": "aal2"})).status_code == 404  # still not a moderator
    finally:
        object.__setattr__(config.settings, "moderator_require_aal2", False)


def test_reports_from_brand_new_accounts_do_not_count_towards_an_automatic_hide(env):
    account_store.MIN_REPORTER_AGE_DAYS = 7  # the suite default is 0; production is a week
    try:
        assert account_store.eligible_reporters([ALICE, BOB, OTHER]) == 0  # all created seconds ago
        account_store.MIN_REPORTER_AGE_DAYS = 0
        assert account_store.eligible_reporters([ALICE, BOB, OTHER, None]) == 3
    finally:
        account_store.MIN_REPORTER_AGE_DAYS = 0


def test_a_restricted_account_cannot_publish_but_can_still_delete_everything_it_owns(env):
    restrict(env, scope="publish")
    from catch.sync import leaderboards as svc

    with tenant.use_owner(ALICE):
        with pytest.raises(svc.LeaderboardError) as exc:
            svc._not_restricted("publish")
    assert exc.value.status == 403
    done = env.c.request("DELETE", "/api/privacy/data/notes_checkins", headers=bearer(ALICE), json={"confirm": True})
    assert done.status_code == 200


def test_a_restriction_covers_every_way_in_not_just_the_front_door(env):
    from catch.sync import club_challenges, club_team, clubs
    from catch.sync import leaderboards as lb

    restrict(env, scope="publish")
    restrict(env, scope="posting")
    restrict(env, scope="clubs")
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        for call, exc in [
            (lambda: lb.update_settings(s, {}), lb.LeaderboardError),
            (lambda: lb.opt_in(s, {}), lb.LeaderboardError),
            (lambda: lb.update_publication(s, "e1", {"note": "new note"}), lb.LeaderboardError),
            (lambda: clubs.create_club(s, name="x"), clubs.ClubError),
            (lambda: clubs.join(s, club_id="c"), clubs.ClubError),
            (lambda: club_team.post_announcement(s, "c", "t", "b"), clubs.ClubError),
            (lambda: club_team.create_session(s, "c", title="t", session_type="water", on=__import__("datetime").date.today()), clubs.ClubError),
            (lambda: club_team.share_result(s, "c", {}, note="hi"), clubs.ClubError),
            (lambda: club_challenges.create_challenge(s, "c", title="t", metric="m", start=__import__("datetime").date.today(), end=__import__("datetime").date.today()), clubs.ClubError),
            (lambda: club_challenges.join_challenge(s, "c", 1), clubs.ClubError),
        ]:
            with pytest.raises(exc) as e:
                call()
            assert e.value.status == 403
        # taking your own things down is never blocked
        assert lb.opt_out(s, {"confirm": True}) is not None
