"""Session 27 (docs/clubs.md): clubs, roles, invites, joining, junior rules, team training, challenges, safety — through the API, on the public
deployment, with several users. SQLite has no RLS, so this proves the SERVICE's own role and membership checks; tests/pg/test_clubs.py proves the
database refuses the same things, and tests/pg/test_clubs_api.py runs these flows on real Postgres. Synthetic data only."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from catch.core import config, tenant
from catch.core.models import CanonicalActivity, Club, ClubChallenge, ClubMember, ProviderConnection
from catch.sync import club_store
from catch.sync import leaderboards as lbsvc
from catch.sync.canonical import resolve_canonical
from catch.sync.upsert import upsert_activity
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

ALICE, BOB = kit.ALICE, kit.BOB
CAROL, DAVE, ERIN, FRANK = (f"{n}{n}{n}{n}{n}{n}{n}{n}-{n}{n}{n}{n}-4{n}{n}{n}-8{n}{n}{n}-{n * 12}" for n in "3457")
MOD = "99999999-9999-4999-8999-999999999999"
ALL = (ALICE, BOB, CAROL, DAVE, ERIN, FRANK, MOD)
UTC = timezone.utc


@pytest.fixture()
def env(pub_client, pub_engine, monkeypatch):
    monkeypatch.setattr("catch.api.routes_clubs.limits.check_rate", lambda owner, bucket="club": None)
    monkeypatch.setattr("catch.api.routes_leaderboards.limits.check_rate", lambda owner, bucket="chat": None)
    monkeypatch.setattr(lbsvc, "_c2_profile", lambda session: {})
    for sub in ALL:
        assert pub_client.get("/api/me", headers=bearer(sub)).status_code == 200
    previous = config.settings.moderator_ids
    object.__setattr__(config.settings, "moderator_ids", MOD)
    yield SimpleNamespace(c=pub_client, engine=pub_engine)
    object.__setattr__(config.settings, "moderator_ids", previous)


# ---------------------------------------------------------------- helpers

def call(env, sub, method, path, expect=None, **kw):
    r = env.c.request(method, f"/api/clubs{path}", headers=bearer(sub), **kw)
    if expect is not None:
        assert r.status_code == expect, f"{method} {path} -> {r.status_code} {r.text}"
    return r


def profile(env, sub, handle, band="adult", guardian=False):
    return call(env, sub, "PUT", "/profile", 200, json={"handle": handle, "age_band": band, "attest_min_age": True, "guardian_consent": guardian}).json()


def make(env, sub, name, **kw):
    body = {"name": name, "visibility": "private", "join_policy": "request", **kw}
    return call(env, sub, "POST", "", 200, json=body).json()["club_id"]


def invite(env, sub, cid, role="athlete", **kw):
    return call(env, sub, "POST", f"/{cid}/invites", 200, json={"role": role, **kw}).json()


def join(env, sub, token, expect=200, **kw):
    return call(env, sub, "POST", "/join", expect, json={"token": token, "accept_rules": True, **kw})


def members(env, sub, cid):
    return call(env, sub, "GET", f"/{cid}/members", 200).json()["members"]


def ref_of(env, sub, cid, handle):
    return next(m["member_ref"] for m in members(env, sub, cid) if m["handle"] == handle)


def adult_club(env, *, policy="invite", visibility="private", name="River Rowing Club", rules=None):
    """Alice owns; Bob (admin), Carol (coach), Dave (athlete) join by invite."""
    profile(env, ALICE, "Alice Owner")
    cid = make(env, ALICE, name, visibility=visibility, join_policy=policy, **({"rules": rules} if rules else {}))
    for sub, handle, role in ((BOB, "Bob Admin", "admin"), (CAROL, "Carol Coach", "coach"), (DAVE, "Dave Athlete", "athlete")):
        profile(env, sub, handle)
        tok = invite(env, ALICE, cid)["token"]
        assert join(env, sub, tok).json()["status"] == "joined"
        if role != "athlete":
            call(env, ALICE, "PUT", f"/{cid}/members/{ref_of(env, ALICE, cid, handle)}/role", 200, json={"role": role})
    return cid


def junior_club(env):
    """Alice (adult) owns a junior club; Carol (adult) is its coach; Dave and Erin are young athletes."""
    profile(env, ALICE, "Alice Owner")
    cid = make(env, ALICE, "Junior Squad", audience="junior", rules="Be kind. Row hard. Respect your coach.")
    profile(env, CAROL, "Coach Carol")
    tok = invite(env, ALICE, cid, "coach")["token"]
    assert join(env, CAROL, tok).json()["status"] == "requested"  # an adult coach is vetted by an owner/admin
    rid = call(env, ALICE, "GET", f"/{cid}/requests", 200).json()["requests"][0]["request_id"]
    call(env, ALICE, "POST", f"/{cid}/requests/{rid}/decide", 200, json={"approve": True})
    assert call(env, CAROL, "GET", "/mine", 200).json()["clubs"][0]["my_role"] == "coach"  # approval completes the join as them
    for sub, handle, band in ((DAVE, "Dave Junior", "U17"), (ERIN, "Erin Junior", "U17")):
        profile(env, sub, handle, band)
    return cid


def junior_admin(env, cid):
    """Bob, an adult, joins the junior club as a coach (the owner vets him) and is made an admin: staff, but not a coach."""
    profile(env, BOB, "Bob Admin")
    assert join(env, BOB, invite(env, ALICE, cid, "coach")["token"]).json()["status"] == "requested"
    rid = next(r["request_id"] for r in call(env, ALICE, "GET", f"/{cid}/requests", 200).json()["requests"] if r["handle"] == "Bob Admin")
    call(env, ALICE, "POST", f"/{cid}/requests/{rid}/decide", 200, json={"approve": True})
    call(env, BOB, "GET", "/mine", 200)   # approval completes the join as them
    call(env, ALICE, "PUT", f"/{cid}/members/{ref_of(env, ALICE, cid, 'Bob Admin')}/role", 200, json={"role": "admin"})


def admit_youth(env, cid, sub):
    tok = invite(env, CAROL, cid)["token"]
    assert join(env, sub, tok).json()["status"] == "requested"
    rid = next(r["request_id"] for r in call(env, CAROL, "GET", f"/{cid}/requests", 200).json()["requests"])
    call(env, CAROL, "POST", f"/{cid}/requests/{rid}/decide", 200, json={"approve": True})
    call(env, sub, "GET", "/mine", 200)


def activity(env, owner, source, ext, day, *, duration=3600.0, distance=10000.0, atype=None, workout_type=None, hour=15, account="1", verified=True, **extra):
    when = datetime.combine(date.today() + timedelta(days=day), datetime.min.time(), tzinfo=UTC).replace(hour=hour)
    with tenant.use_owner(owner), Session(env.engine) as s:
        if source == "concept2" and s.get(ProviderConnection, tenant.pk("concept2")) is None:
            s.add(ProviderConnection(provider="concept2", auth_method="personal_token", account_id=account, last4="abcd"))
            s.commit()
        fields = dict(type=atype or ("rower" if source == "concept2" else "rowing_v2"), start=when, duration=duration, distance=distance, **extra)
        if source == "concept2":
            fields.update(workout_type=workout_type or "FixedDistanceSplits", c2_user_id=account, c2_verified=verified, c2_weight_class="H",
                          raw_json=json.dumps({"id": ext, "user_id": int(account), "verified": verified, "weight_class": "H"}))
        a = upsert_activity(s, source, ext, **fields)
        resolve_canonical(s, a.canonical_id)
        return a.id, a.canonical_id


def club_row(env, cid):
    with Session(env.engine) as s:
        return s.get(Club, cid)


# ---------------------------------------------------------------- availability

def test_clubs_do_not_exist_on_a_personal_install(client):
    from tests.conftest import TEST_PASSWORD

    client.post("/api/login", json={"password": TEST_PASSWORD})
    assert client.get("/api/clubs/mine").status_code == 404
    assert client.get("/api/clubs/discover").status_code == 404
    assert client.post("/api/clubs", json={"name": "Nope Club"}).status_code == 404
    assert client.get("/api/moderation/clubs/queue").status_code == 404


def test_an_unauthenticated_caller_gets_nothing(env):
    assert env.c.get("/api/clubs/mine").status_code == 401
    assert env.c.get("/api/clubs/discover").status_code == 401
    assert env.c.post("/api/clubs/join", json={"token": "x"}).status_code == 401


# ---------------------------------------------------------------- profile

def test_a_profile_needs_a_handle_an_age_group_and_the_minimum_age_tick(env):
    r = call(env, ALICE, "PUT", "/profile", json={"handle": "Alice Owner", "age_band": "adult", "attest_min_age": False})
    assert r.status_code == 400 and "13 or older" in r.json()["detail"]
    assert call(env, ALICE, "PUT", "/profile", json={"handle": "www.example.com", "age_band": "adult", "attest_min_age": True}).status_code == 400
    assert call(env, ALICE, "PUT", "/profile", json={"handle": "Alice Owner", "age_band": "U12", "attest_min_age": True}).status_code == 400
    assert profile(env, ALICE, "Alice Owner")["age_class"] == "adult"
    assert call(env, BOB, "PUT", "/profile", json={"handle": "alice owner", "age_band": "adult", "attest_min_age": True}).status_code == 409  # handles are unique


def test_under_sixteen_needs_a_guardian_tick_and_it_is_recorded(env):
    r = call(env, DAVE, "PUT", "/profile", json={"handle": "Dave Junior", "age_band": "U15", "attest_min_age": True})
    assert r.status_code == 400 and "guardian" in r.json()["detail"]
    assert profile(env, DAVE, "Dave Junior", "U15", guardian=True)["guardian_consent"] is True
    assert profile(env, ERIN, "Erin Junior", "U17")["guardian_consent"] is False  # 16 and over: no tick needed


def test_nothing_works_before_a_profile_exists(env):
    assert call(env, ALICE, "POST", "", json={"name": "No Profile Club"}).status_code == 428


# ---------------------------------------------------------------- creating, discovering, reading

def test_discovery_lists_only_public_adult_active_clubs_with_a_count_and_no_members(env):
    profile(env, ALICE, "Alice Owner")
    public = make(env, ALICE, "Open Water Club", visibility="public", join_policy="open", description="Row at dawn.", location="Boston, MA")
    make(env, ALICE, "Private Quiet Club")
    make(env, ALICE, "Junior Hidden Squad", audience="junior")
    listed = call(env, BOB, "GET", "/discover", 200).json()["clubs"]
    assert [k["name"] for k in listed] == ["Open Water Club"]
    assert listed[0]["member_count"] == 1 and listed[0]["location"] == "Boston, MA" and "members" not in listed[0]
    assert [k["name"] for k in call(env, BOB, "GET", "/discover", params={"q": "water"}).json()["clubs"]] == ["Open Water Club"]
    assert call(env, BOB, "GET", "/discover", params={"q": "quiet"}).json()["clubs"] == []
    with Session(env.engine) as s:
        row = s.get(Club, public)
        row.status = "suspended"
        s.add(row)
        s.commit()
    assert call(env, BOB, "GET", "/discover", 200).json()["clubs"] == []  # a suspended club leaves discovery


def test_a_stranger_sees_a_public_club_but_never_a_private_or_junior_one(env):
    profile(env, ALICE, "Alice Owner")
    pub = make(env, ALICE, "Open Water Club", visibility="public", join_policy="open", rules="Be kind.")
    priv = make(env, ALICE, "Private Quiet Club")
    junior = make(env, ALICE, "Junior Hidden Squad", audience="junior")
    seen = call(env, BOB, "GET", f"/{pub}", 200).json()
    assert seen["name"] == "Open Water Club" and seen["my_role"] is None and seen["capabilities"] is None and seen["rules"] == "Be kind."
    assert call(env, BOB, "GET", f"/{priv}").status_code == 404 and call(env, BOB, "GET", f"/{junior}").status_code == 404
    for path in ("members", "announcements", "calendar", "challenges", "summary", "audit", "leaderboard", "invites", "requests"):
        assert call(env, BOB, "GET", f"/{pub}/{path}").status_code == 404, path  # even the public club's insides are members-only


def test_creating_a_club_validates_and_junior_clubs_are_forced_private(env):
    profile(env, ALICE, "Alice Owner")
    for body, text in (({"name": "ab"}, "3-40"), ({"name": "Visit www.club.com"}, "web address"), ({"name": "Good Name", "visibility": "public", "audience": "junior"}, "junior club is always private"),
                       ({"name": "Good Name", "visibility": "private", "join_policy": "open"}, "only a public club")):
        r = call(env, ALICE, "POST", "", json=body)
        assert r.status_code == 400 and text in r.json()["detail"], body
    make(env, ALICE, "Real Club")
    assert call(env, BOB, "POST", "", json={"name": "real club"}).status_code in (409, 428)  # unique name (BOB has no profile yet, so 428 is also right)
    profile(env, BOB, "Bob Admin")
    assert call(env, BOB, "POST", "", json={"name": "real club"}).status_code == 409
    for i in range(2):
        make(env, ALICE, f"Extra Club {i}")
    assert call(env, ALICE, "POST", "", json={"name": "One Too Many"}).status_code == 429  # three clubs a day


def test_a_young_person_cannot_start_a_club(env):
    profile(env, DAVE, "Dave Junior", "U17")
    r = call(env, DAVE, "POST", "", json={"name": "Kids Club", "audience": "junior"})
    assert r.status_code == 403 and "Only adults" in r.json()["detail"]


# ---------------------------------------------------------------- joining: open, invite, request

def test_an_open_public_club_admits_directly_and_a_removed_member_can_not_return(env):
    profile(env, ALICE, "Alice Owner")
    cid = make(env, ALICE, "Open Water Club", visibility="public", join_policy="open")
    profile(env, BOB, "Bob Admin")
    assert call(env, BOB, "POST", "/join", 200, json={"club_id": cid}).json()["status"] == "joined"
    assert call(env, BOB, "POST", "/join", 409, json={"club_id": cid})
    call(env, ALICE, "POST", f"/{cid}/members/{ref_of(env, ALICE, cid, 'Bob Admin')}/remove", 200, json={"reason": "Repeated rudeness at practice"})
    assert call(env, BOB, "GET", f"/{cid}").json()["my_role"] is None
    r = call(env, BOB, "POST", "/join", json={"club_id": cid})
    assert r.status_code == 403 and "can't rejoin" in r.json()["detail"]


def test_a_private_club_cannot_be_joined_without_its_link(env):
    profile(env, ALICE, "Alice Owner")
    cid = make(env, ALICE, "Private Quiet Club")
    profile(env, BOB, "Bob Admin")
    assert call(env, BOB, "POST", "/join", json={"club_id": cid}).status_code == 404


def test_rules_must_be_accepted_to_join(env):
    profile(env, ALICE, "Alice Owner")
    cid = make(env, ALICE, "Rule Club", join_policy="invite", rules="No wake. Be on time.")
    tok = invite(env, ALICE, cid)["token"]
    profile(env, BOB, "Bob Admin")
    preview = call(env, BOB, "POST", "/invite-preview", 200, json={"token": tok}).json()
    assert preview["rules"] == "No wake. Be on time." and preview["name"] == "Rule Club" and preview["cannot_join_because"] is None
    r = call(env, BOB, "POST", "/join", json={"token": tok})
    assert r.status_code == 428 and "rules" in r.json()["detail"]
    assert join(env, BOB, tok).json()["status"] == "joined"


def test_invites_expire_revoke_and_run_out(env):
    profile(env, ALICE, "Alice Owner")
    cid = make(env, ALICE, "Invite Club", join_policy="invite")
    for sub, name in ((BOB, "Bob Admin"), (CAROL, "Carol Coach"), (DAVE, "Dave Athlete"), (ERIN, "Erin Athlete")):
        profile(env, sub, name)
    revoked, expired, single = invite(env, ALICE, cid), invite(env, ALICE, cid), invite(env, ALICE, cid, max_uses=1)
    call(env, ALICE, "POST", f"/{cid}/invites/{revoked['invite_id']}/revoke", 200)
    from catch.core.models import ClubInvite

    with Session(env.engine) as s:
        row = s.get(ClubInvite, expired["invite_id"])
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        s.add(row)
        s.commit()
    assert join(env, BOB, revoked["token"], 404).json()["detail"].startswith("This invite link")
    assert join(env, BOB, expired["token"], 404)
    assert join(env, BOB, single["token"]).json()["status"] == "joined"
    assert join(env, CAROL, single["token"], 404)  # used up
    shown = call(env, ALICE, "GET", f"/{cid}/invites", 200).json()["invites"]
    assert {i["state"] for i in shown} == {"revoked", "expired", "active"} and all(i["token"] is None for i in shown)  # a token is shown once, at creation
    for bad in ({"days": 0}, {"days": 31}, {"max_uses": 0}):
        assert call(env, ALICE, "POST", f"/{cid}/invites", json=bad).status_code == 400
    assert call(env, DAVE, "POST", f"/{cid}/invites", json={}).status_code == 404  # not a member


def test_a_request_club_holds_the_applicant_until_staff_decide_and_a_rejection_is_final_for_that_request(env):
    profile(env, ALICE, "Alice Owner")
    cid = make(env, ALICE, "Request Club", visibility="public", join_policy="request")
    for sub, name in ((BOB, "Bob Admin"), (CAROL, "Carol Coach")):
        profile(env, sub, name)
    assert call(env, BOB, "POST", "/join", 200, json={"club_id": cid, "message": "I row Sundays"}).json()["status"] == "requested"
    assert call(env, BOB, "POST", "/join", 409, json={"club_id": cid})  # one pending request per club
    assert call(env, CAROL, "POST", "/join", 200, json={"club_id": cid}).json()["status"] == "requested"
    queue = call(env, ALICE, "GET", f"/{cid}/requests", 200).json()["requests"]
    assert {r["handle"] for r in queue} == {"Bob Admin", "Carol Coach"} and queue[0]["message"] == "I row Sundays"
    bob_req = next(r["request_id"] for r in queue if r["handle"] == "Bob Admin")
    carol_req = next(r["request_id"] for r in queue if r["handle"] == "Carol Coach")
    r = call(env, ALICE, "POST", f"/{cid}/requests/{carol_req}/decide", json={"approve": False})
    assert r.status_code == 400 and "reason" in r.json()["detail"].lower()
    call(env, ALICE, "POST", f"/{cid}/requests/{carol_req}/decide", 200, json={"approve": False, "reason": "Club is full"})
    call(env, ALICE, "POST", f"/{cid}/requests/{bob_req}/decide", 200, json={"approve": True})
    mine = call(env, BOB, "GET", "/mine", 200).json()
    assert [k["name"] for k in mine["clubs"]] == ["Request Club"]  # approval completed the join as Bob
    assert call(env, CAROL, "GET", "/mine", 200).json()["requests"][0]["status"] == "rejected"
    assert call(env, CAROL, "GET", f"/{cid}", 200).json()["my_role"] is None


def test_an_applicant_can_withdraw_and_nobody_else_can(env):
    profile(env, ALICE, "Alice Owner")
    cid = make(env, ALICE, "Request Club", visibility="public", join_policy="request")
    profile(env, BOB, "Bob Admin")
    call(env, BOB, "POST", "/join", 200, json={"club_id": cid})
    rid = call(env, BOB, "GET", "/mine", 200).json()["requests"][0]["request_id"]
    assert call(env, ALICE, "DELETE", f"/requests/{rid}").status_code == 404
    call(env, BOB, "DELETE", f"/requests/{rid}", 200)
    assert call(env, ALICE, "GET", f"/{cid}/requests", 200).json()["requests"] == []


# ---------------------------------------------------------------- roles

def test_the_role_matrix_through_the_api(env):
    cid = adult_club(env)
    bob, carol, dave, alice = (ref_of(env, ALICE, cid, h) for h in ("Bob Admin", "Carol Coach", "Dave Athlete", "Alice Owner"))
    role = lambda sub, target, new, expect: call(env, sub, "PUT", f"/{cid}/members/{target}/role", expect, json={"role": new})  # noqa: E731
    role(BOB, dave, "coach", 200)                                  # an admin promotes an athlete
    role(BOB, carol, "admin", 403)                                 # ...but can't mint another admin
    role(BOB, alice, "athlete", 403)                               # ...or touch the owner
    role(CAROL, dave, "athlete", 403)                              # a coach manages no roles
    role(DAVE, carol, "athlete", 403)
    role(ALICE, dave, "owner", 400)                                # ownership is a transfer, not a role
    role(ALICE, dave, "wizard", 400)
    role(ALICE, bob, "athlete", 200)
    assert [m["role"] for m in members(env, DAVE, cid)] == ["owner", "coach", "coach", "athlete"] or {m["handle"]: m["role"] for m in members(env, DAVE, cid)}["Bob Admin"] == "athlete"
    call(env, BOB, "POST", f"/{cid}/members/{dave}/remove", 403, json={"reason": "no longer an admin"})   # Bob was demoted


def test_removing_a_member_needs_a_reason_the_right_role_and_is_audited(env):
    cid = adult_club(env)
    refs = {h: ref_of(env, ALICE, cid, h) for h in ("Alice Owner", "Bob Admin", "Carol Coach", "Dave Athlete")}
    rm = lambda sub, who, reason="Repeatedly ignored the safety rules": call(env, sub, "POST", f"/{cid}/members/{refs[who]}/remove", json={"reason": reason})  # noqa: E731
    assert rm(CAROL, "Bob Admin").status_code == 403 and rm(CAROL, "Alice Owner").status_code == 403 and rm(DAVE, "Carol Coach").status_code == 403
    assert rm(BOB, "Alice Owner").status_code == 403 and rm(BOB, "Carol Coach", "").status_code == 400
    assert rm(CAROL, "Dave Athlete").status_code == 200      # a coach removes an athlete
    log = call(env, ALICE, "GET", f"/{cid}/audit", 200).json()["events"]
    removal = next(e for e in log if e["action"] == "member_removed")
    assert removal["by"] == "Carol Coach" and removal["about"] == "Dave Athlete" and "safety rules" in removal["reason"]
    assert call(env, DAVE, "GET", f"/{cid}").status_code == 404 and call(env, DAVE, "GET", f"/{cid}/members").status_code == 404   # a private club no longer admits it exists
    assert call(env, DAVE, "GET", f"/{cid}/audit").status_code == 404 and call(env, CAROL, "GET", f"/{cid}/audit", 200)   # staff read the trail; a removed member can't


def test_leaving_and_transferring_ownership(env):
    cid = adult_club(env)
    refs = {h: ref_of(env, ALICE, cid, h) for h in ("Bob Admin", "Carol Coach")}
    assert call(env, ALICE, "POST", f"/{cid}/leave").status_code == 403           # the owner transfers first
    call(env, DAVE, "POST", f"/{cid}/leave", 200)
    assert call(env, DAVE, "GET", f"/{cid}").status_code == 404 and len(members(env, ALICE, cid)) == 3
    preview = call(env, ALICE, "POST", f"/{cid}/transfer", 200, json={"member_ref": refs["Bob Admin"]}).json()
    assert preview["transferred"] is False and "Bob Admin" in preview["preview"] and call(env, BOB, "GET", f"/{cid}").json()["my_role"] == "admin"
    assert call(env, BOB, "POST", f"/{cid}/transfer", 403, json={"member_ref": refs["Carol Coach"], "confirm": True})   # an admin can't hand it over
    call(env, ALICE, "POST", f"/{cid}/transfer", 200, json={"member_ref": refs["Bob Admin"], "confirm": True})
    assert call(env, BOB, "GET", f"/{cid}").json()["my_role"] == "owner" and call(env, ALICE, "GET", f"/{cid}").json()["my_role"] == "admin"
    call(env, ALICE, "POST", f"/{cid}/leave", 200)


def test_deleting_a_club_is_owner_only_and_needs_confirmation(env):
    cid = adult_club(env)
    assert call(env, BOB, "POST", f"/{cid}/delete", 403, json={"confirm": True})
    preview = call(env, ALICE, "POST", f"/{cid}/delete", 200, json={}).json()
    assert preview["deleted"] is False and "permanently" in preview["preview"] and call(env, DAVE, "GET", f"/{cid}", 200)
    call(env, ALICE, "POST", f"/{cid}/delete", 200, json={"confirm": True})
    assert call(env, DAVE, "GET", f"/{cid}").status_code == 404
    with Session(env.engine) as s:
        assert s.exec(select(ClubMember).where(ClubMember.club_id == cid)).all() == []


def test_a_member_is_never_named_by_their_account_id(env):
    cid = adult_club(env)
    blob = json.dumps(members(env, DAVE, cid))
    for uid in (ALICE, BOB, CAROL, DAVE):
        assert uid not in blob
    refs_here = {m["member_ref"] for m in members(env, DAVE, cid)}
    other = make(env, ALICE, "Second Club")
    call(env, ALICE, "GET", f"/{other}/members", 200)
    assert not refs_here & {m["member_ref"] for m in members(env, ALICE, other)}  # the same person has a different reference in each club


def test_settings_changes_are_admin_only_and_audience_never_changes(env):
    cid = adult_club(env)
    assert call(env, CAROL, "PATCH", f"/{cid}", json={"description": "x"}).status_code == 403
    assert call(env, DAVE, "PATCH", f"/{cid}", json={"description": "x"}).status_code == 403
    assert call(env, BOB, "PATCH", f"/{cid}", 200, json={"description": "Row at dawn.", "location": "Boston"}).json()["description"] == "Row at dawn."
    call(env, BOB, "PATCH", f"/{cid}", json={"audience": "junior"})
    assert club_row(env, cid).audience == "adult"  # an unknown field is ignored, never applied
    assert call(env, BOB, "PATCH", f"/{cid}", json={"visibility": "public", "join_policy": "open"}).status_code == 200
    assert call(env, BOB, "PATCH", f"/{cid}", json={"visibility": "private"}).status_code == 400  # open must stay public


# ---------------------------------------------------------------- junior clubs

def test_a_young_person_can_only_join_a_junior_club_by_invitation_and_a_coach_approves(env):
    cid = junior_club(env)
    dave = call(env, DAVE, "GET", f"/{cid}")
    assert dave.status_code == 404                                           # unlisted and invisible until admitted
    adult_pub = make(env, ALICE, "Adult Open Club", visibility="public", join_policy="open")
    assert call(env, DAVE, "POST", "/join", 403, json={"club_id": adult_pub}).json()["detail"].startswith("adult clubs are for adults")
    tok = invite(env, CAROL, cid)["token"]
    assert call(env, DAVE, "POST", "/invite-preview", 200, json={"token": tok}).json()["will_need_approval"] is True
    assert join(env, DAVE, tok).json()["status"] == "requested"
    rid = call(env, CAROL, "GET", f"/{cid}/requests", 200).json()["requests"][0]
    assert rid["age_class"] == "youth" and rid["can_decide"] is True
    call(env, ALICE, "POST", f"/{cid}/requests/{rid['request_id']}/decide", 200, json={"approve": True})   # the owner is a coach here too
    assert call(env, DAVE, "GET", "/mine", 200).json()["clubs"][0]["my_role"] == "athlete"
    assert call(env, DAVE, "GET", f"/{cid}/requests").status_code == 403


def test_an_adult_cannot_join_a_junior_club_as_an_athlete_and_a_youth_cannot_be_staff(env):
    cid = junior_club(env)
    profile(env, BOB, "Bob Adult")
    tok = invite(env, CAROL, cid)["token"]
    r = call(env, BOB, "POST", "/join", json={"token": tok})
    assert r.status_code == 403 and "junior club's athletes are young members" in r.json()["detail"]
    coach_tok = invite(env, ALICE, cid, "coach")["token"]
    r = call(env, DAVE, "POST", "/join", json={"token": coach_tok, "accept_rules": True})
    assert r.status_code == 403
    assert call(env, CAROL, "POST", f"/{cid}/invites", 403, json={"role": "coach"})   # a coach can't invite a coach
    admit_youth(env, cid, DAVE)
    dave = ref_of(env, ALICE, cid, "Dave Junior")
    r = call(env, ALICE, "PUT", f"/{cid}/members/{dave}/role", json={"role": "coach"})
    assert r.status_code == 400 and "young members" in r.json()["detail"]    # promotion can't make a minor staff


def test_under_sixteen_needs_a_guardian_on_file_before_a_junior_club(env):
    cid = junior_club(env)
    profile(env, FRANK, "Frank Young", "U15", guardian=True)
    call(env, FRANK, "PUT", "/profile", 400, json={"handle": "Frank Young", "age_band": "U15", "attest_min_age": True})  # can't quietly drop consent
    tok = invite(env, CAROL, cid)["token"]
    assert join(env, FRANK, tok).json()["status"] == "requested"
    shown = call(env, CAROL, "GET", f"/{cid}/requests", 200).json()["requests"][0]
    assert shown["guardian_consent"] is True    # the coach can see consent is recorded


def test_a_junior_club_may_have_a_logo_and_links_in_posts_but_not_in_its_description(env):
    cid = junior_club(env)
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 100
    r = env.c.put(f"/api/clubs/{cid}/logo", headers={**bearer(ALICE), "content-type": "image/png"}, content=png)
    assert r.status_code == 200 and call(env, ALICE, "GET", f"/{cid}", 200).json()["has_logo"] is True
    assert env.c.get(f"/api/clubs/{cid}/logo", headers=bearer(CAROL)).status_code == 200               # members see it
    assert env.c.get(f"/api/clubs/{cid}/logo", headers=bearer(DAVE)).status_code == 404                # an outsider (not yet admitted) does not
    call(env, CAROL, "POST", f"/{cid}/announcements", 200, json={"title": "Practice", "body": "See www.example.com for the plan"})
    assert call(env, ALICE, "POST", "", 400, json={"name": "Junior Two", "audience": "junior", "description": "visit www.example.com"})


def test_every_junior_post_not_written_by_a_coach_or_the_owner_waits_for_a_coach(env):
    cid = junior_club(env)
    junior_admin(env, cid)
    admit_youth(env, cid, DAVE)
    mine = call(env, BOB, "POST", f"/{cid}/announcements", 200, json={"title": "Regatta", "body": "Saturday, 8am."}).json()
    assert mine["status"] == "pending" and "coach approves" in mine["message"]
    coach = call(env, CAROL, "POST", f"/{cid}/announcements", 200, json={"title": "Practice", "body": "Tuesday, 6am."}).json()
    assert coach["status"] == "published"                                           # a coach's own post goes straight out
    owner = call(env, ALICE, "POST", f"/{cid}/announcements", 200, json={"title": "Kit", "body": "Bring a bottle."}).json()
    assert owner["status"] == "published"                                           # and so does the owner's: the owner is a coach here
    assert {a["title"] for a in call(env, DAVE, "GET", f"/{cid}/announcements", 200).json()["announcements"]} == {"Practice", "Kit"}
    staff_view = call(env, CAROL, "GET", f"/{cid}/announcements", 200).json()["announcements"]
    pending = next(a for a in staff_view if a["status"] == "pending")
    assert pending["can_approve"] is True
    assert call(env, BOB, "GET", f"/{cid}/announcements", 200).json()["announcements"][0]["can_approve"] is False   # an admin can't approve, even a post of their own
    assert call(env, BOB, "POST", f"/{cid}/posts/announcement/{pending['id']}/decide", json={"action": "approve"}).status_code == 403
    assert call(env, DAVE, "POST", f"/{cid}/posts/announcement/{pending['id']}/decide", json={"action": "approve"}).status_code == 403
    call(env, ALICE, "POST", f"/{cid}/posts/announcement/{pending['id']}/decide", 200, json={"action": "approve"})   # the owner approves
    assert {a["title"] for a in call(env, DAVE, "GET", f"/{cid}/announcements", 200).json()["announcements"]} == {"Practice", "Regatta", "Kit"}
    assert call(env, CAROL, "POST", f"/{cid}/announcements", 200, json={"title": "T", "body": "B"})
    assert call(env, DAVE, "POST", f"/{cid}/announcements", 403, json={"title": "Hi", "body": "I can post?"})


def test_a_rejection_needs_a_reason_and_is_recorded(env):
    cid = junior_club(env)
    junior_admin(env, cid)
    p = call(env, BOB, "POST", f"/{cid}/announcements", 200, json={"title": "Party", "body": "Pizza after."}).json()["id"]
    assert call(env, CAROL, "POST", f"/{cid}/posts/announcement/{p}/decide", json={"action": "reject"}).status_code == 400
    call(env, CAROL, "POST", f"/{cid}/posts/announcement/{p}/decide", 200, json={"action": "reject", "reason": "Not appropriate for this club"})
    log = call(env, CAROL, "GET", f"/{cid}/audit", 200).json()["events"]
    assert any(e["action"] == "announcement_rejected" and "Not appropriate" in e["reason"] for e in log)


# ---------------------------------------------------------------- isolation between clubs

def test_a_member_of_one_club_reaches_nothing_in_another(env):
    one = adult_club(env, name="Club One")
    profile(env, ERIN, "Erin Owner")
    two = make(env, ERIN, "Club Two")
    call(env, ERIN, "PUT", f"/{two}/prefs", 200, json={"accept_rules": True})
    sess = call(env, ERIN, "POST", f"/{two}/sessions", 200, json={"title": "Secret", "session_type": "erg", "date": date.today().isoformat()}).json()["id"]
    post = call(env, ERIN, "POST", f"/{two}/announcements", 200, json={"title": "Private news", "body": "Only for club two"}).json()["id"]
    chal = call(env, ERIN, "POST", f"/{two}/challenges", 200, json={"title": "Two Cup", "metric": "sessions", "goal": 8, "start": date.today().isoformat(), "end": (date.today() + timedelta(days=13)).isoformat()}).json()["id"]
    reads = ("", "/members", "/announcements", "/calendar", "/challenges", f"/challenges/{chal}", "/summary", "/audit", "/leaderboard", "/invites", "/requests")
    for path in reads:
        for sub in (ALICE, BOB, CAROL, DAVE):
            assert call(env, sub, "GET", f"/{two}{path}").status_code in (404,), (sub, path)
    writes = [("POST", f"/{two}/announcements", {"title": "x", "body": "y"}), ("POST", f"/{two}/sessions", {"title": "x", "date": date.today().isoformat()}),
              ("POST", f"/{two}/challenges/{chal}/join", None), ("POST", f"/{two}/invites", {}), ("PATCH", f"/{two}", {"description": "pwned"}),
              ("POST", f"/{two}/leave", None), ("POST", f"/{two}/posts/announcement/{post}/decide", {"action": "hide", "reason": "x"}),
              ("POST", f"/{two}/report", {"target_type": "club", "reason": "spam"}), ("PUT", f"/{two}/prefs", {"share_numbers": True}),
              ("POST", f"/{two}/sessions/{sess}/participation", {"canonical_id": 1}), ("POST", f"/{two}/delete", {"confirm": True})]
    for method, path, body in writes:
        r = call(env, DAVE, method, path, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (method, path, r.status_code)
    assert club_row(env, two).description is None and call(env, ERIN, "GET", f"/{two}/announcements", 200).json()["announcements"][0]["title"] == "Private news"
    assert {k["name"] for k in call(env, DAVE, "GET", "/mine", 200).json()["clubs"]} == {"Club One"}
    assert one != two


# ---------------------------------------------------------------- team training

def test_staff_publish_sessions_and_members_choose_whether_to_associate_a_workout(env):
    cid = adult_club(env)
    today = date.today()
    s = call(env, CAROL, "POST", f"/{cid}/sessions", 200, json={"title": "Steady 60", "session_type": "erg", "date": today.isoformat(), "start_time": "06:30", "duration_min": 60}).json()
    assert s["status"] == "published"
    assert call(env, DAVE, "POST", f"/{cid}/sessions", 403, json={"title": "Mine", "session_type": "erg", "date": today.isoformat()})
    for bad in ({"start_time": "6:30"}, {"duration_min": 0}, {"session_type": "swim"}, {"date": (today + timedelta(days=500)).isoformat()}):
        assert call(env, CAROL, "POST", f"/{cid}/sessions", json={"title": "Bad", "session_type": "erg", "date": today.isoformat(), **bad}).status_code in (400, 422), bad
    _, mine = activity(env, DAVE, "garmin", "g1", 0, duration=3600, distance=14000)
    _, elsewhere = activity(env, DAVE, "garmin", "g2", 5, duration=3600, distance=14000)
    cal = call(env, DAVE, "GET", f"/{cid}/calendar", 200).json()["sessions"]
    assert cal[0]["participants"] == 0 and cal[0]["i_took_part"] is False
    assert call(env, DAVE, "POST", f"/{cid}/sessions/{s['id']}/participation", 400, json={"canonical_id": elsewhere}).json()["detail"].startswith("That workout isn't on this session's day")
    assert call(env, DAVE, "POST", f"/{cid}/sessions/{s['id']}/participation", 404, json={"canonical_id": 999999})
    _, bobs = activity(env, BOB, "garmin", "gb", 0)
    assert call(env, DAVE, "POST", f"/{cid}/sessions/{s['id']}/participation", 404, json={"canonical_id": bobs})   # someone else's workout is simply not found
    assert call(env, DAVE, "POST", f"/{cid}/sessions/{s['id']}/participation", 200, json={"canonical_id": mine}).json() == {"took_part": True, "shared_numbers": False}
    cal = call(env, CAROL, "GET", f"/{cid}/calendar", 200).json()["sessions"]
    assert cal[0]["participants"] == 1
    call(env, DAVE, "DELETE", f"/{cid}/sessions/{s['id']}/participation", 200)
    assert call(env, CAROL, "GET", f"/{cid}/calendar", 200).json()["sessions"][0]["participants"] == 0


def test_a_team_summary_is_aggregate_only_and_hides_a_total_until_three_members_share(env):
    cid = adult_club(env)
    profile(env, ERIN, "Erin Athlete")
    join(env, ERIN, invite(env, ALICE, cid)["token"])
    today = date.today()
    sid = call(env, CAROL, "POST", f"/{cid}/sessions", 200, json={"title": "Steady 60", "session_type": "erg", "date": today.isoformat()}).json()["id"]
    users = [DAVE, BOB, ALICE, ERIN]
    for i, sub in enumerate(users):
        _, cn = activity(env, sub, "garmin", f"gs{i}", 0, distance=10000 + i * 1000, duration=3600)
        share = i != 3                                                             # Erin takes part but shares no numbers
        call(env, sub, "POST", f"/{cid}/sessions/{sid}/participation", 200, json={"canonical_id": cn, "share_numbers": share})
    s = call(env, DAVE, "GET", f"/{cid}/summary", 200).json()
    assert s["sessions"] == 1 and s["participations"] == 4 and s["members"] == 5
    assert s["distance_m"]["suppressed"] is False and s["distance_m"]["total"] == 33000 and s["distance_m"]["shared"] == 3   # 3 sharers: a total may appear
    call(env, ALICE, "DELETE", f"/{cid}/sessions/{sid}/participation", 200)
    s = call(env, DAVE, "GET", f"/{cid}/summary", 200).json()
    assert s["participations"] == 3 and s["distance_m"]["suppressed"] is True and s["distance_m"]["total"] is None   # two sharers: nothing that could be one person's number
    blob = json.dumps(s)
    for uid in (ALICE, BOB, CAROL, DAVE, ERIN):
        assert uid not in blob
    assert "Dave" not in blob and "handle" not in blob and "owner" not in blob.replace("owner_id", "")


def test_a_junior_clubs_team_session_waits_for_a_coach(env):
    cid = junior_club(env)
    junior_admin(env, cid)
    admit_youth(env, cid, DAVE)
    r = call(env, BOB, "POST", f"/{cid}/sessions", 200, json={"title": "Erg test", "session_type": "test", "date": date.today().isoformat()}).json()
    assert r["status"] == "pending"
    assert call(env, DAVE, "GET", f"/{cid}/calendar", 200).json()["sessions"] == []
    call(env, CAROL, "POST", f"/{cid}/posts/session/{r['id']}/decide", 200, json={"action": "approve"})
    assert [s["title"] for s in call(env, DAVE, "GET", f"/{cid}/calendar", 200).json()["sessions"]] == ["Erg test"]


# ---------------------------------------------------------------- the club results board

def test_the_club_board_ranks_only_verified_results_and_only_what_a_member_chose_to_share(env):
    cid = adult_club(env)
    ids = {}
    for sub, ext, secs, account, verified in ((DAVE, "c-dave", 420.0, "10", True), (CAROL, "c-carol", 400.0, "20", True), (BOB, "c-bob", 380.0, "30", False)):
        ids[sub] = activity(env, sub, "concept2", ext, -3, duration=secs, distance=2000, account=account, verified=verified)[0]
    share = lambda sub: call(env, sub, "POST", f"/{cid}/results", json={"ref": {"kind": "concept2_result", "id": ids[sub]}})  # noqa: E731
    assert [share(s).status_code for s in (DAVE, CAROL, BOB)] == [200, 200, 200]
    assert share(DAVE).status_code == 409                                         # once per result
    board = call(env, ALICE, "GET", f"/{cid}/leaderboard", 200, params={"board": "2000m"}).json()
    assert [(r["name"], r["rank"], r["verification"]) for r in board["ranked"]] == [("Carol Coach", 1, "verified"), ("Dave Athlete", 2, "verified")]
    assert [(r["name"], r["verification"]) for r in board["unverified"]] == [("Bob Admin", "provider_linked")]   # never above a verified one
    assert call(env, ALICE, "GET", f"/{cid}/leaderboard", 404, params={"board": "1234m"})
    nothing = call(env, ALICE, "GET", f"/{cid}/leaderboard", 200, params={"board": "5000m"}).json()
    assert nothing["ranked"] == [] and "choose what they share" in nothing["note"]
    call(env, CAROL, "DELETE", f"/{cid}/results/{next(r['result_id'] for r in call(env, CAROL, 'GET', f'/{cid}/leaderboard', 200, params={'board': '2000m'}).json()['ranked'] if r['is_me'])}", 200)
    assert [r["name"] for r in call(env, ALICE, "GET", f"/{cid}/leaderboard", 200, params={"board": "2000m"}).json()["ranked"]] == ["Dave Athlete"]
    odd = activity(env, DAVE, "concept2", "c-1960", -2, duration=400.0, distance=1960, account="10")[0]
    assert call(env, DAVE, "POST", f"/{cid}/results", 400, json={"ref": {"kind": "concept2_result", "id": odd}}).json()["detail"].startswith("Only an exact")


def test_staff_can_hide_a_shared_result_with_a_reason(env):
    cid = adult_club(env)
    act = activity(env, DAVE, "concept2", "c-dave", -3, duration=420.0, distance=2000, account="10")[0]
    rid = call(env, DAVE, "POST", f"/{cid}/results", 200, json={"ref": {"kind": "concept2_result", "id": act}}).json()["id"]
    assert call(env, DAVE, "POST", f"/{cid}/results/{rid}/hide", 403, json={"reason": "no"})
    assert call(env, CAROL, "POST", f"/{cid}/results/{rid}/hide", 400, json={"reason": ""})
    call(env, CAROL, "POST", f"/{cid}/results/{rid}/hide", 200, json={"reason": "Result is not from this member"})
    assert call(env, ALICE, "GET", f"/{cid}/leaderboard", 200, params={"board": "2000m"}).json()["ranked"] == []


# ---------------------------------------------------------------- challenges

def challenge(env, sub, cid, **kw):
    body = {"title": "Metres Cup", "metric": "distance", "goal": 100000, "start": date.today().isoformat(), "end": (date.today() + timedelta(days=13)).isoformat(), **kw}
    return call(env, sub, "POST", f"/{cid}/challenges", 200, json=body).json()["id"]


def test_unsafe_or_unclear_challenges_are_refused_with_what_to_change(env):
    cid = adult_club(env)
    start, end = date.today().isoformat(), (date.today() + timedelta(days=13)).isoformat()
    for body, text in (({"metric": "distance"}, "set a goal"), ({"metric": "distance", "goal": 10_000_000}, "a week"), ({"metric": "time", "goal": 360000, "day_cap_s": 40000}, "hours a day"),
                       ({"metric": "sessions", "goal": 8, "min_session_s": 300}, "15 minutes"), ({"metric": "weight", "goal": 10}, "distance, time"),
                       ({"metric": "consistency", "target_per_week": 7}, "more earns nothing"),
                       ({"metric": "sessions", "goal": 8, "start": (date.today() - timedelta(days=3)).isoformat()}, "past"), ({"metric": "sessions", "goal": 8, "end": start}, "weeks")):
        r = call(env, CAROL, "POST", f"/{cid}/challenges", json={"title": "Bad One", "start": start, "end": end, **body})
        assert r.status_code == 400 and text in r.json()["detail"], (body, r.text)
    assert call(env, DAVE, "POST", f"/{cid}/challenges", 403, json={"title": "Mine", "metric": "sessions", "goal": 8, "start": start, "end": end})
    ok = call(env, CAROL, "POST", f"/{cid}/challenges", 200, json={"title": "Good One", "metric": "sessions", "goal": 8, "start": start, "end": end}).json()
    assert ok["status"] == "active" and any("Equal scores share a rank" in line for line in ok["rules"])


def test_a_distance_challenge_scores_from_the_members_own_provider_activities_with_caps(env):
    cid = adult_club(env)
    ch = challenge(env, CAROL, cid, goal=60000)
    activity(env, DAVE, "garmin", "d1", 0, distance=15000)
    activity(env, DAVE, "garmin", "d1b", 0, distance=20000, hour=18)       # same day: the daily cap (30 km) counts 15 + 15
    activity(env, DAVE, "garmin", "d2", 1, distance=12000)
    activity(env, DAVE, "garmin", "d3", 2, distance=9000)
    activity(env, DAVE, "garmin", "run", 3, distance=9000, atype="running")  # not rowing
    activity(env, DAVE, "garmin", "far", 40, distance=9000)                  # outside the window
    with tenant.use_owner(DAVE), Session(env.engine) as s:                     # typed-in work never counts
        a = upsert_activity(s, "catch_strength", "typed1", type="strength", start=datetime.combine(date.today() + timedelta(days=4), datetime.min.time(), tzinfo=UTC).replace(hour=15), duration=3600.0, distance=50000.0)
        resolve_canonical(s, a.canonical_id)
    r = call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 200).json()
    assert r["joined"] is True and r["value"] == "51.0 km"                  # day one's 35 km counts as the 30 km daily cap, + 12 + 9; the run, the far-off ride and the typed session add nothing
    info = call(env, DAVE, "GET", f"/{cid}/challenges/{ch}", 200).json()
    assert info["my_value"] == info["standings"][0]["value"] == "51.0 km"


def test_challenge_scoring_end_to_end_with_ranking_ties_and_exclusions(env):
    cid = adult_club(env)
    ch = challenge(env, CAROL, cid, goal=40000, metric="distance")
    for sub, dist in ((DAVE, 20000), (BOB, 20000), (ALICE, 45000), (CAROL, 5000)):
        activity(env, sub, "garmin", f"e-{sub[:4]}", 0, distance=dist)
    activity(env, ALICE, "garmin", "e-alice2", 1, distance=30000)
    excluded_id, excluded_canonical = activity(env, CAROL, "garmin", "e-carol-x", 1, distance=25000)
    with tenant.use_owner(CAROL), Session(env.engine) as s:
        k = s.get(CanonicalActivity, excluded_canonical)
        k.overrides_json = json.dumps({"exclude_from_totals": True})
        s.add(k)
        s.commit()
    for sub in (DAVE, BOB, ALICE, CAROL):
        call(env, sub, "POST", f"/{cid}/challenges/{ch}/join", 200)
    rows = call(env, DAVE, "GET", f"/{cid}/challenges/{ch}", 200).json()["standings"]
    assert [(r["name"], r["rank"], r["value"]) for r in sorted(rows, key=lambda r: (r["rank"], r["name"]))] == [
        ("Alice Owner", 1, "40.0 km"), ("Bob Admin", 2, "20.0 km"), ("Dave Athlete", 2, "20.0 km"), ("Carol Coach", 4, "5.0 km")]   # 1-2-2-4; Alice's 75 km counts as the 40 km goal; Carol's excluded 25 km counts for nothing
    assert call(env, DAVE, "GET", f"/{cid}/challenges", 200).json()["challenges"][0]["participants"] == 4


def test_a_hand_typed_concept2_result_does_not_count_but_a_verified_one_does(env):
    cid = adult_club(env)
    ch = challenge(env, CAROL, cid, goal=60000)
    activity(env, DAVE, "concept2", "typed-by-hand", 0, distance=20000, account="31", verified=False)    # no `verified` flag: typed into the logbook
    activity(env, DAVE, "concept2", "from-the-pm5", 1, distance=8000, account="31", verified=True)
    activity(env, DAVE, "garmin", "watch", 2, distance=5000)
    assert call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 200).json()["value"] == "13.0 km"   # 8 + 5; the 20 km typed result adds nothing
    rules = call(env, DAVE, "GET", f"/{cid}/challenges/{ch}", 200).json()["rules"]
    assert any("flagged verified by Concept2" in r and "Garmin and Whoop don't say" in r for r in rules)   # the sentence users see matches what the code does


def test_the_same_activity_cannot_count_for_two_accounts(env):
    cid = adult_club(env)
    ch = challenge(env, CAROL, cid, goal=60000)
    activity(env, DAVE, "concept2", "shared-c2", 0, distance=12000, account="777")
    activity(env, BOB, "concept2", "shared-c2", 0, distance=12000, account="777")   # the same Concept2 result seen through a second Catch account
    activity(env, BOB, "garmin", "bobs-own", 1, distance=5000)
    assert call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 200).json()["value"] == "12.0 km"
    assert call(env, BOB, "POST", f"/{cid}/challenges/{ch}/join", 200).json()["value"] == "5.0 km"    # the contested result stays Dave's; Bob keeps his own
    call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/leave", 200)                                       # leaving releases the claim
    assert call(env, BOB, "GET", f"/{cid}/challenges/{ch}", 200).json()["my_value"] == "17.0 km"


def test_opting_out_leaves_the_standings(env):
    cid = adult_club(env)
    ch = challenge(env, CAROL, cid, goal=60000)
    activity(env, DAVE, "garmin", "x1", 0, distance=10000)
    call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 200)
    assert len(call(env, CAROL, "GET", f"/{cid}/challenges/{ch}", 200).json()["standings"]) == 1
    call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/leave", 200)
    assert call(env, CAROL, "GET", f"/{cid}/challenges/{ch}", 200).json()["standings"] == []
    info = call(env, DAVE, "GET", f"/{cid}/challenges/{ch}", 200).json()
    assert info["my_value"] is None and info["joined"] is False and info["can_join"] is True    # and they may come back while it's open


def test_no_endpoint_accepts_a_score_so_a_member_cannot_post_one(env):
    spec = env.c.get("/openapi.json").json() if env.c.get("/openapi.json").status_code == 200 else None
    from catch.main import app

    schema = app.openapi()
    bodies = []
    for path, ops in schema["paths"].items():
        if path.startswith("/api/clubs") and "challenges" in path:
            for op in ops.values():
                ref = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema", {}).get("$ref")
                if ref:
                    bodies.append(schema["components"]["schemas"][ref.split("/")[-1]])
    assert bodies, "the challenge routes should have request bodies"
    for body in bodies:
        assert not {"value", "score", "distance", "total", "rank", "result"} & set(body.get("properties", {})), body["title"]
    assert spec is None or spec


def test_a_closed_challenge_is_frozen_and_cannot_be_joined(env):
    cid = adult_club(env)
    ch = challenge(env, CAROL, cid, goal=60000)
    activity(env, DAVE, "garmin", "f1", 0, distance=10000)
    call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 200)
    with Session(env.engine) as s:
        row = s.get(ClubChallenge, ch)
        row.start_date, row.end_date = date.today() - timedelta(days=20), date.today() - timedelta(days=6)
        s.add(row)
        s.commit()
    activity(env, DAVE, "garmin", "late", -10, distance=5000)
    info = call(env, DAVE, "GET", f"/{cid}/challenges/{ch}", 200).json()
    assert info["phase"] == "closed" and info["can_join"] is False
    assert call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 409) and call(env, BOB, "POST", f"/{cid}/challenges/{ch}/join", 409)
    assert info["standings"][0]["raw"] == 10000        # frozen: the later activity did not change it
    assert call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/excuse", 400, json={"week": date.today().isoformat()})


def test_consistency_rewards_regularity_and_an_excused_week_is_not_a_penalty(env):
    cid = adult_club(env)
    monday = date.today() - timedelta(days=date.today().weekday())
    nxt = monday + timedelta(days=7)
    ch = call(env, CAROL, "POST", f"/{cid}/challenges", 200, json={"title": "Steady Weeks", "metric": "consistency", "target_per_week": 3, "start": nxt.isoformat(), "end": (nxt + timedelta(days=13)).isoformat()}).json()["id"]
    with Session(env.engine) as s:                                       # a challenge can't be created in the past, so bring it to this week directly
        row = s.get(ClubChallenge, ch)
        row.start_date, row.end_date = monday, monday + timedelta(days=13)
        s.add(row)
        s.commit()
    for i in range(3):
        activity(env, DAVE, "garmin", f"c{i}", -date.today().weekday() + i, duration=2400)
    call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 200)
    info = call(env, DAVE, "GET", f"/{cid}/challenges/{ch}", 200).json()
    assert info["my_detail"]["met"] == 1 and info["target_per_week"] == 3 and info["my_value"] == "1 of 1 weeks"
    week2 = (monday + timedelta(days=7)).isoformat()
    assert call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/excuse", 200, json={"week": week2}).json()["excused_weeks"] == [week2]
    assert call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/excuse", 400, json={"week": (monday + timedelta(days=60)).isoformat()})
    assert call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/excuse", 200, json={"week": week2, "excused": False}).json()["excused_weeks"] == []
    plain = challenge(env, CAROL, cid, goal=20000)
    call(env, DAVE, "POST", f"/{cid}/challenges/{plain}/join", 200)
    assert call(env, DAVE, "POST", f"/{cid}/challenges/{plain}/excuse", 400, json={"week": monday.isoformat()}).json()["detail"].startswith("Only a consistency")


def test_a_junior_challenge_waits_for_a_coach_and_has_tighter_limits(env):
    cid = junior_club(env)
    junior_admin(env, cid)
    admit_youth(env, cid, DAVE)
    start, end = date.today().isoformat(), (date.today() + timedelta(days=13)).isoformat()
    r = call(env, BOB, "POST", f"/{cid}/challenges", 200, json={"title": "Squad Cup", "metric": "time", "goal": 4 * 3600, "start": start, "end": end}).json()
    assert r["status"] == "pending" and call(env, DAVE, "GET", f"/{cid}/challenges", 200).json()["challenges"] == []
    assert call(env, CAROL, "POST", f"/{cid}/challenges", 400, json={"title": "Too Much", "metric": "time", "goal": 40 * 3600, "start": start, "end": end}).json()["detail"].count("8 hours a week")
    call(env, CAROL, "POST", f"/{cid}/posts/challenge/{r['id']}/decide", 200, json={"action": "approve"})
    assert [c["title"] for c in call(env, DAVE, "GET", f"/{cid}/challenges", 200).json()["challenges"]] == ["Squad Cup"]


# ---------------------------------------------------------------- privacy: nothing private reaches a club

def test_no_private_health_or_training_value_appears_in_any_club_response(env):
    from catch.core.models import BodyComp, DailyWellness, Note

    cid = adult_club(env)
    sentinels = {"hrv": 87.654, "weight": 71.234, "sleep": 27123, "kcal": 3141, "note": "SENTINEL-NOTE-TEXT", "fat": 18.765}
    for who in (DAVE, CAROL, BOB):
        with tenant.use_owner(who), Session(env.engine) as s:
            s.add(DailyWellness(date=date.today(), source="garmin", resting_hr=41, hrv_rmssd=sentinels["hrv"], sleep_seconds=sentinels["sleep"]))
            s.add(BodyComp(source="withings", external_id=f"bc-{who[:4]}", ts=datetime.now(UTC), weight_kg=sentinels["weight"], fat_pct=sentinels["fat"]))
            s.add(Note(date=date.today(), text=sentinels["note"], rpe=9))
            s.commit()
    sid = call(env, CAROL, "POST", f"/{cid}/sessions", 200, json={"title": "Steady 60", "session_type": "erg", "date": date.today().isoformat()}).json()["id"]
    ch = challenge(env, CAROL, cid, goal=60000)
    for who in (DAVE, CAROL, BOB):
        _, cn = activity(env, who, "garmin", f"p-{who[:4]}", 0, distance=12000)
        call(env, who, "POST", f"/{cid}/sessions/{sid}/participation", 200, json={"canonical_id": cn, "share_numbers": True})
        call(env, who, "POST", f"/{cid}/challenges/{ch}/join", 200)
    call(env, CAROL, "POST", f"/{cid}/announcements", 200, json={"title": "Hello", "body": "Welcome"})
    seen = []
    for who in (ALICE, BOB, CAROL, DAVE):
        for path in ("", "/members", "/announcements", "/calendar", "/challenges", f"/challenges/{ch}", "/summary", "/audit", "/leaderboard", "/invites", "/requests"):
            r = call(env, who, "GET", f"/{cid}{path}")
            if r.status_code == 200:
                seen.append(r.text)
        seen.append(call(env, who, "GET", "/mine", 200).text)
    blob = "\n".join(seen).lower().replace("nothing about weight, calories, recovery or sleep is used or shown.", "").replace("no recovery, sleep, weight or nutrition data is ever included.", "")  # disclaimers say what is NOT used
    assert len(seen) > 30
    for name, value in sentinels.items():
        assert str(value).lower() not in blob, f"{name} leaked into a club response"
    for word in ("hrv", "resting_hr", "weight_kg", "fat_pct", "sleep_seconds", "calories", "recovery", "strain", "rpe"):
        assert word not in blob, word


# ---------------------------------------------------------------- blocks, reports, moderation

def test_blocking_hides_a_member_from_my_views_only(env):
    cid = adult_club(env)
    dave = ref_of(env, ALICE, cid, "Dave Athlete")
    assert call(env, BOB, "POST", f"/{cid}/blocks/{dave}", 200).json() == {"blocked": True}
    seen = {m["handle"] for m in members(env, CAROL, cid)}
    assert "Dave Athlete" in seen                                                        # only the blocker's view changes
    ch = challenge(env, CAROL, cid, goal=60000)
    activity(env, DAVE, "garmin", "b1", 0, distance=10000)
    call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 200)
    assert call(env, BOB, "GET", f"/{cid}/challenges/{ch}", 200).json()["standings"] == []
    assert len(call(env, CAROL, "GET", f"/{cid}/challenges/{ch}", 200).json()["standings"]) == 1
    assert call(env, DAVE, "POST", f"/{cid}/blocks/{ref_of(env, DAVE, cid, 'Dave Athlete')}").status_code == 400   # not yourself
    call(env, BOB, "DELETE", f"/{cid}/blocks/{dave}", 200)
    assert len(call(env, BOB, "GET", f"/{cid}/challenges/{ch}", 200).json()["standings"]) == 1


def test_reports_three_distinct_reporters_hide_an_announcement_and_staff_never_see_who(env):
    cid = adult_club(env)
    profile(env, ERIN, "Erin Athlete")
    join(env, ERIN, invite(env, ALICE, cid)["token"])
    post = call(env, CAROL, "POST", f"/{cid}/announcements", 200, json={"title": "Spicy", "body": "A questionable post"}).json()["id"]
    rep = lambda sub: call(env, sub, "POST", f"/{cid}/report", json={"target_type": "announcement", "target_id": str(post), "reason": "inappropriate"})  # noqa: E731
    assert rep(DAVE).status_code == 200 and rep(DAVE).status_code == 409
    assert rep(BOB).status_code == 200
    assert [a["status"] for a in call(env, ERIN, "GET", f"/{cid}/announcements", 200).json()["announcements"]] == ["published"]
    assert rep(ERIN).status_code == 200
    assert call(env, ERIN, "GET", f"/{cid}/announcements", 200).json()["announcements"] == []          # auto-hidden after the third
    log = call(env, ALICE, "GET", f"/{cid}/audit", 200).json()["events"]
    assert any(e["action"] == "post_auto_hidden" for e in log) and "reporter" not in json.dumps(log).lower()
    for sub in (ALICE, CAROL):
        assert call(env, sub, "GET", f"/{cid}/reports").status_code in (404, 405)                # there is no endpoint through which staff read reports
    for bad in ({"target_type": "club", "reason": "nonsense"}, {"target_type": "pizza", "reason": "spam"}, {"target_type": "announcement", "target_id": "9999", "reason": "spam"}):
        assert call(env, DAVE, "POST", f"/{cid}/report", json=bad).status_code in (400, 404), bad


def test_reporting_a_member_goes_to_moderators_who_can_remove_them_but_not_from_their_own_club(env):
    cid = adult_club(env)
    dave = ref_of(env, CAROL, cid, "Dave Athlete")
    assert call(env, CAROL, "POST", f"/{cid}/report", 200, json={"target_type": "member", "target_id": dave, "reason": "harassment", "detail": "Messages after practice"})
    assert call(env, CAROL, "POST", f"/{cid}/report", 400, json={"target_type": "member", "target_id": ref_of(env, CAROL, cid, "Carol Coach"), "reason": "spam"})  # not yourself
    mod = lambda method, path, **kw: env.c.request(method, f"/api/moderation/clubs{path}", headers=bearer(MOD), **kw)  # noqa: E731
    queue = mod("GET", "/queue")
    assert queue.status_code == 200 and queue.json()["reports"][0]["club_name"] == "River Rowing Club" and queue.json()["reports"][0]["reports"] == 1
    assert "reporter" not in queue.text.lower() and CAROL not in queue.text
    detail = mod("GET", f"/{cid}").json()
    assert detail["reports"][0]["about"] == "Dave Athlete" and detail["reports"][0]["reason"] == "harassment" and CAROL not in json.dumps(detail)
    target = detail["reports"][0]["target_id"]
    r0 = mod("POST", f"/{cid}/action", json={"action": "remove_member", "reason": "", "target_id": target})
    assert r0.status_code == 422 and r0.json()["detail"] == "A reason is required."   # the leaderboard moderation convention
    assert mod("POST", f"/{cid}/action", json={"action": "explode", "reason": "x"}).status_code == 422
    assert mod("POST", f"/{cid}/action", json={"action": "remove_member", "reason": "Confirmed harassment", "target_id": target}).status_code == 200
    assert call(env, DAVE, "GET", f"/{cid}").status_code == 404   # removed from a private club: it no longer admits it exists
    log = call(env, ALICE, "GET", f"/{cid}/audit", 200).json()["events"]
    assert any(e["action"] == "moderator_remove_member" and e["by"] == "a platform moderator" and "harassment" in e["reason"] for e in log)
    assert mod("GET", "/queue").json()["reports"] == []                                          # actioned reports leave the queue
    for sub in (ALICE, DAVE):
        assert env.c.get("/api/moderation/clubs/queue", headers=bearer(sub)).status_code == 404   # not a moderator: the endpoint doesn't exist for you
    with Session(env.engine) as s:
        s.add(ClubMember(club_id=cid, owner_id=MOD, club_audience="adult", role="athlete"))
        s.commit()
    r = mod("POST", f"/{cid}/action", json={"action": "suspend_club", "reason": "x"})
    assert r.status_code == 403 and "belong to" in r.json()["detail"]


def test_a_suspended_club_leaves_discovery_but_members_keep_read_access(env):
    cid = adult_club(env, policy="open", visibility="public", name="Public Rowers")
    assert env.c.post(f"/api/moderation/clubs/{cid}/action", headers=bearer(MOD), json={"action": "suspend_club", "reason": "Under review after reports"}).status_code == 200
    assert call(env, ERIN, "GET", "/discover", 200).json()["clubs"] == []
    assert call(env, ERIN, "GET", f"/{cid}").status_code == 404
    assert call(env, DAVE, "GET", f"/{cid}", 200).json()["status"] == "suspended"
    profile(env, ERIN, "Erin Athlete")
    assert call(env, ERIN, "POST", "/join", 404, json={"club_id": cid})
    env.c.post(f"/api/moderation/clubs/{cid}/action", headers=bearer(MOD), json={"action": "restore_club", "reason": "Cleared"})
    assert [k["name"] for k in call(env, ERIN, "GET", "/discover", 200).json()["clubs"]] == ["Public Rowers"]


# ---------------------------------------------------------------- logos, public board filter, account deletion

def test_a_logo_is_admin_only_small_and_visible_to_members_and_public_visitors(env):
    cid = adult_club(env, policy="open", visibility="public", name="Public Rowers")
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 200
    put = lambda sub, data, ctype="image/png": env.c.put(f"/api/clubs/{cid}/logo", headers={**bearer(sub), "content-type": ctype}, content=data)  # noqa: E731
    assert put(CAROL, png).status_code == 403 and put(DAVE, png).status_code == 403
    assert put(ALICE, b"not an image").status_code == 400 and put(ALICE, png, "text/html").status_code == 400
    assert put(ALICE, png + b"x" * 270000).status_code == 413
    assert put(ALICE, png).status_code == 200
    got = call(env, ERIN, "GET", f"/{cid}/logo", 200)
    assert got.content == png and got.headers["content-type"] == "image/png" and got.headers["x-content-type-options"] == "nosniff"
    assert call(env, DAVE, "GET", f"/{cid}", 200).json()["has_logo"] is True
    call(env, ALICE, "DELETE", f"/{cid}/logo", 200)
    assert call(env, ERIN, "GET", f"/{cid}/logo").status_code == 404
    private = make(env, ALICE, "Private Quiet Club")
    env.c.put(f"/api/clubs/{private}/logo", headers={**bearer(ALICE), "content-type": "image/png"}, content=png)
    assert call(env, ERIN, "GET", f"/{private}/logo").status_code == 404


def test_deleting_an_account_hands_a_club_to_the_longest_standing_eligible_member_or_deletes_it(env):
    cid = adult_club(env)
    solo = make(env, ALICE, "Solo Club")
    club_store.delete_owner_data(ALICE)
    assert [m["role"] for m in members(env, BOB, cid)].count("owner") == 1
    assert {m["handle"]: m["role"] for m in members(env, BOB, cid)}["Bob Admin"] == "owner"     # the admin, not the athlete, takes over
    with Session(env.engine) as s:
        assert s.get(Club, solo) is None                                                         # nobody to take it over
        from catch.core.models import ClubAudit

        assert any(a.action == "club_deleted_owner_left_no_successor" for a in s.exec(select(ClubAudit).where(ClubAudit.club_id == solo)).all())
        kept = s.exec(select(ClubAudit).where(ClubAudit.club_id == cid)).all()
        assert kept and all(a.actor_id != ALICE and a.subject_owner_id != ALICE for a in kept)   # what they did stays, detached from them
    assert call(env, ALICE, "GET", f"/{cid}").status_code == 404


def test_a_junior_clubs_owner_leaving_goes_to_an_adult_never_to_a_young_athlete(env):
    cid = junior_club(env)
    admit_youth(env, cid, DAVE)
    club_store.delete_owner_data(ALICE)
    roles = {m["handle"]: m["role"] for m in members(env, CAROL, cid)}
    assert roles["Coach Carol"] == "owner" and roles["Dave Junior"] == "athlete"


def test_the_public_board_club_filter_cannot_reveal_a_junior_or_private_club(env):
    cid = adult_club(env)
    act = activity(env, DAVE, "concept2", "c-dave", -3, duration=420.0, distance=2000, account="10")[0]
    call(env, DAVE, "PUT", f"/{cid}/prefs", 200, json={"include_public_results": True})
    r = env.c.get("/api/leaderboards/boards/2000m", headers=bearer(ALICE), params={"club": cid})
    assert r.status_code == 200 and r.json()["total"] == 0                         # a private club's membership isn't enumerable through the public board
    assert act and call(env, DAVE, "GET", f"/{cid}", 200).json()["my_prefs"]["include_public_results"] is True   # it only affects this club's own board


# ---------------------------------------------------------------- the invariants never rely on the happy path

def test_the_service_refuses_what_the_database_would_also_refuse(env):
    """CHECK constraints run on SQLite too, so a service bug that built an impossible row would fail here, not just on Postgres."""
    cid = junior_club(env)
    admit_youth(env, cid, DAVE)
    with Session(env.engine) as s:
        from sqlalchemy.exc import IntegrityError

        s.add(ClubMember(club_id=cid, owner_id=BOB, club_audience="junior", role="athlete", age_class="adult"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        s.add(ClubMember(club_id=cid, owner_id=BOB, club_audience="junior", role="coach", age_class="youth"))
        with pytest.raises(IntegrityError):
            s.commit()
