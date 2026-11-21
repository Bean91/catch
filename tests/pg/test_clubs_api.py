"""Session 27 through the real runtime path: the FastAPI app as `catch_api`, every request taking the signed-in user's identity as `authenticated`,
real GoTrue accounts, the membership RLS policies from migration 0006. tests/tenancy/test_clubs_api.py proves the service's own checks on SQLite;
tests/pg/test_clubs.py proves the database refuses what it should. This proves they work TOGETHER: the service's writes are admitted by the policies, the
paths that need the system role (counts, invites, moderation, deletion) work, and a member of one club still reaches nothing of another's."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlmodel import Session

from catch.core import config, tenant
from catch.core.models import ProviderConnection
from catch.sync.canonical import resolve_canonical
from catch.sync.upsert import upsert_activity
from tests.pg.conftest import signup
from tests.pg.test_runtime import app  # noqa: F401  (the fixture: the real app on the catch_api engine)


@pytest.fixture(autouse=True)
def _users_on_the_test_hosts_calendar(monkeypatch):
    """Dates here come from the host's date.today(); a public account with no zone reads days in UTC (session 32, docs/time.md)."""
    from catch.core import localtime

    monkeypatch.setattr(localtime, "fallback_zone_name", localtime.host_zone_name)

pytestmark = pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")
UTC = timezone.utc


@pytest.fixture()
def env(app, runtime, admin, monkeypatch):  # noqa: F811
    monkeypatch.setattr("catch.api.routes_clubs.limits.check_rate", lambda owner, bucket="club": None)
    monkeypatch.setattr("catch.api.routes_leaderboards.limits.check_rate", lambda owner, bucket="chat": None)
    previous = config.settings.moderator_ids
    yield app
    object.__setattr__(config.settings, "moderator_ids", previous)
    with admin.begin() as conn:
        for t in ("club_audit", "clubs", "club_profiles"):
            conn.execute(text(f"DELETE FROM catch.{t}"))


class Who:
    """A signed-in person with the helpers a test wants."""

    def __init__(self, client, name: str):
        self.client, self.user = client, signup(name)
        self.id = self.user.id

    def call(self, method, path, expect=None, **kw):
        r = self.client.request(method, f"/api/clubs{path}", headers=self.user.headers, **kw)
        if expect is not None:
            assert r.status_code == expect, f"{method} {path} -> {r.status_code} {r.text}"
        return r

    def profile(self, handle, band="adult", guardian=False):
        return self.call("PUT", "/profile", 200, json={"handle": handle, "age_band": band, "attest_min_age": True, "guardian_consent": guardian}).json()

    def make(self, name, **kw):
        return self.call("POST", "", 200, json={"name": name, "visibility": "private", "join_policy": "request", **kw}).json()["club_id"]

    def invite(self, cid, role="athlete", **kw):
        return self.call("POST", f"/{cid}/invites", 200, json={"role": role, **kw}).json()["token"]

    def join(self, token, expect=200):
        return self.call("POST", "/join", expect, json={"token": token, "accept_rules": True})

    def members(self, cid):
        return self.call("GET", f"/{cid}/members", 200).json()["members"]

    def ref(self, cid, handle):
        return next(m["member_ref"] for m in self.members(cid) if m["handle"] == handle)


def people(app, *names):  # noqa: F811
    return [Who(app, n) for n in names]


def seed_activity(runtime, who: Who, source: str, ext: str, day: int, *, distance=10000.0, duration=3600.0, account="1"):
    when = datetime.combine(date.today() + timedelta(days=day), datetime.min.time(), tzinfo=UTC).replace(hour=15)
    with tenant.use_owner(who.id), Session(runtime) as s:
        if source == "concept2" and s.get(ProviderConnection, tenant.pk("concept2")) is None:
            s.add(ProviderConnection(provider="concept2", auth_method="personal_token", account_id=account, last4="abcd"))
            s.commit()
        fields = dict(type="rower" if source == "concept2" else "rowing_v2", start=when, duration=duration, distance=distance)
        if source == "concept2":
            fields.update(workout_type="FixedDistanceSplits", c2_user_id=account, c2_verified=True, c2_weight_class="H",
                          raw_json=json.dumps({"id": ext, "user_id": int(account), "verified": True, "weight_class": "H"}))
        a = upsert_activity(s, source, ext, **fields)
        resolve_canonical(s, a.canonical_id)
        return a.id, a.canonical_id


# ---------------------------------------------------------------- the adult lifecycle under real policies

def test_an_adult_club_runs_end_to_end_under_row_level_security(env, runtime, admin):
    owner, bob, carol, stranger = people(env, "o", "b", "c", "s")
    for who, handle in ((owner, "PgOwner"), (bob, "PgBob"), (carol, "PgCarol"), (stranger, "PgStranger")):
        who.profile(handle)
    cid = owner.make("Pg River Club", join_policy="invite", rules="Be kind.", description="Row at dawn.")
    # an invite admits directly: the approved-request row and the membership insert are both admitted by the policies, as the joiner
    assert bob.join(owner.invite(cid)).json()["status"] == "joined"
    assert carol.join(owner.invite(cid)).json()["status"] == "joined"
    owner.call("PUT", f"/{cid}/members/{owner.ref(cid, 'PgCarol')}/role", 200, json={"role": "coach"})
    assert {m["handle"]: m["role"] for m in bob.members(cid)} == {"PgOwner": "owner", "PgBob": "athlete", "PgCarol": "coach"}

    # discovery count and the invite preview come through the system role, and carry no member list
    assert stranger.call("POST", "/invite-preview", 200, json={"token": owner.invite(cid)}).json()["name"] == "Pg River Club"
    assert stranger.call("GET", f"/{cid}").status_code == 404

    # a coach posts, an athlete reads, nobody outside does
    carol.call("POST", f"/{cid}/announcements", 200, json={"title": "Practice", "body": "Tuesday 6am"})
    assert [a["title"] for a in bob.call("GET", f"/{cid}/announcements", 200).json()["announcements"]] == ["Practice"]
    assert stranger.call("GET", f"/{cid}/announcements").status_code == 404

    # a coach removes an athlete (recorded with the reason); the removed member's private club vanishes for them
    carol.call("POST", f"/{cid}/members/{carol.ref(cid, 'PgBob')}/remove", 200, json={"reason": "Ignored the safety briefing twice"})
    assert bob.call("GET", f"/{cid}").status_code == 404
    log = owner.call("GET", f"/{cid}/audit", 200).json()["events"]
    assert any(e["action"] == "member_removed" and e["by"] == "PgCarol" and e["about"] == "PgBob" for e in log)
    assert bob.join(owner.invite(cid), 403).json()["detail"] == "You can't rejoin this club."   # the tombstone holds on the real table

    # an athlete leaving writes their own audit row (INSERT ... RETURNING under the audit SELECT policy), then the membership
    dave = Who(env, "d")
    dave.profile("PgDave")
    assert dave.join(owner.invite(cid)).json()["status"] == "joined"
    dave.call("POST", f"/{cid}/leave", 200)
    left = owner.call("GET", f"/{cid}/audit", 200).json()["events"]
    assert dave.call("GET", f"/{cid}").status_code == 404 and any(e["action"] == "member_left" for e in left), left

    # ownership moves through the SECURITY DEFINER function, and only the owner can call it
    assert carol.call("POST", f"/{cid}/transfer", 403, json={"member_ref": carol.ref(cid, "PgOwner"), "confirm": True})
    owner.call("POST", f"/{cid}/transfer", 200, json={"member_ref": owner.ref(cid, "PgCarol"), "confirm": True})
    assert {m["handle"]: m["role"] for m in carol.members(cid)}["PgCarol"] == "owner"
    assert owner.call("POST", f"/{cid}/delete", 403, json={"confirm": True})   # now an admin: not the owner

    # the new owner deletes it, and the cascade removes every dependent row
    carol.call("POST", f"/{cid}/delete", 200, json={"confirm": True})
    with admin.connect() as conn:
        for table in ("club_members", "club_invites", "club_announcements", "club_join_requests", "club_member_prefs"):
            assert conn.execute(text(f"SELECT count(*) FROM catch.{table} WHERE club_id = :c"), {"c": cid}).scalar() == 0, table


def test_a_member_of_one_club_reaches_nothing_in_another_on_the_real_database(env):
    a, b = people(env, "x", "y")
    a.profile("PgAlpha")
    b.profile("PgBeta")
    one, two = a.make("Pg Club One"), b.make("Pg Club Two")
    two_post = b.call("POST", f"/{two}/announcements", 200, json={"title": "Private", "body": "Only club two"}).json()["id"]
    for path in ("", "/members", "/announcements", "/calendar", "/challenges", "/summary", "/audit", "/leaderboard", "/invites", "/requests"):
        assert a.call("GET", f"/{two}{path}").status_code == 404, path
    for method, path, body in (("POST", f"/{two}/announcements", {"title": "x", "body": "y"}), ("PATCH", f"/{two}", {"description": "pwned"}), ("POST", f"/{two}/leave", None),
                               ("POST", f"/{two}/posts/announcement/{two_post}/decide", {"action": "hide", "reason": "x"}), ("POST", f"/{two}/delete", {"confirm": True})):
        assert a.call(method, path, **({"json": body} if body is not None else {})).status_code == 404, (method, path)
    assert [k["name"] for k in a.call("GET", "/mine", 200).json()["clubs"]] == ["Pg Club One"] and one
    assert b.call("GET", f"/{two}/announcements", 200).json()["announcements"][0]["title"] == "Private"


# ---------------------------------------------------------------- junior clubs

def test_the_junior_rules_hold_end_to_end_on_the_real_database(env):
    owner, coach, kid, adult, adm = people(env, "jo", "jc", "jk", "ja", "jx")
    owner.profile("PgJrOwner")
    adm.profile("PgJrAdmin")
    coach.profile("PgJrCoach")
    kid.profile("PgKid", "U17")
    adult.profile("PgAdultAthlete")
    cid = owner.make("Pg Junior Squad", audience="junior")
    assert coach.join(owner.invite(cid, "coach")).json()["status"] == "requested"
    rid = owner.call("GET", f"/{cid}/requests", 200).json()["requests"][0]["request_id"]
    owner.call("POST", f"/{cid}/requests/{rid}/decide", 200, json={"approve": True})
    assert coach.call("GET", "/mine", 200).json()["clubs"][0]["my_role"] == "coach"     # the applicant completes the join as themselves

    assert adm.join(owner.invite(cid, "coach")).json()["status"] == "requested"
    rid = next(r["request_id"] for r in owner.call("GET", f"/{cid}/requests", 200).json()["requests"] if r["handle"] == "PgJrAdmin")
    owner.call("POST", f"/{cid}/requests/{rid}/decide", 200, json={"approve": True})
    adm.call("GET", "/mine", 200)
    owner.call("PUT", f"/{cid}/members/{owner.ref(cid, 'PgJrAdmin')}/role", 200, json={"role": "admin"})   # staff, but not a coach

    # a young person asks; the owner (a coach here) or the coach can admit them, an admin can't; an adult can't be an athlete; and none of it is visible beforehand
    assert kid.call("GET", f"/{cid}").status_code == 404 and adult.call("GET", f"/{cid}").status_code == 404
    assert adult.call("POST", "/join", 403, json={"token": coach.invite(cid), "accept_rules": True})
    assert kid.join(coach.invite(cid)).json()["status"] == "requested"
    kid_req = coach.call("GET", f"/{cid}/requests", 200).json()["requests"][0]["request_id"]
    assert adm.call("POST", f"/{cid}/requests/{kid_req}/decide", 403, json={"approve": True})
    owner.call("POST", f"/{cid}/requests/{kid_req}/decide", 200, json={"approve": True})
    assert kid.call("GET", "/mine", 200).json()["clubs"][0]["my_role"] == "athlete"

    # posts: an admin's wait for a coach (or the owner), the coach's and owner's don't; the athlete sees only what's published
    held = adm.call("POST", f"/{cid}/announcements", 200, json={"title": "Regatta", "body": "Saturday"}).json()
    assert held["status"] == "pending"
    coach.call("POST", f"/{cid}/announcements", 200, json={"title": "Practice", "body": "Tuesday"})
    assert [a["title"] for a in kid.call("GET", f"/{cid}/announcements", 200).json()["announcements"]] == ["Practice"]
    assert adm.call("POST", f"/{cid}/posts/announcement/{held['id']}/decide", 403, json={"action": "approve"})
    coach.call("POST", f"/{cid}/posts/announcement/{held['id']}/decide", 200, json={"action": "approve"})
    assert {a["title"] for a in kid.call("GET", f"/{cid}/announcements", 200).json()["announcements"]} == {"Practice", "Regatta"}
    assert kid.call("POST", f"/{cid}/announcements", 403, json={"title": "Me", "body": "Hi"})

    # the owner leaving goes to an adult (the coach), never the young athlete
    with pytest.raises(AssertionError):
        owner.call("POST", f"/{cid}/leave", 200)                                          # the owner transfers first
    owner.call("POST", f"/{cid}/transfer", 200, json={"member_ref": owner.ref(cid, "PgJrCoach"), "confirm": True})
    assert kid.call("POST", f"/{cid}/transfer", 403, json={"member_ref": kid.ref(cid, "PgKid"), "confirm": True})
    assert {m["handle"]: m["role"] for m in kid.members(cid)}["PgJrCoach"] == "owner"


# ---------------------------------------------------------------- challenges and team training

def test_challenge_claims_conflict_across_accounts_and_standings_cross_members_under_rls(env, runtime):
    owner, dave, bob = people(env, "co", "cd", "cb")
    for who, handle in ((owner, "PgChOwner"), (dave, "PgChDave"), (bob, "PgChBob")):
        who.profile(handle)
    cid = owner.make("Pg Challenge Club", join_policy="invite")
    dave.join(owner.invite(cid))
    bob.join(owner.invite(cid))
    start, end = date.today().isoformat(), (date.today() + timedelta(days=13)).isoformat()
    ch = owner.call("POST", f"/{cid}/challenges", 200, json={"title": "Metres", "metric": "distance", "goal": 60000, "start": start, "end": end}).json()["id"]
    seed_activity(runtime, dave, "concept2", "shared-c2", 0, distance=12000, account="777")
    seed_activity(runtime, bob, "concept2", "shared-c2", 0, distance=12000, account="777")   # the same Concept2 result seen through a second account
    seed_activity(runtime, bob, "garmin", "bob-own", 1, distance=5000)
    assert dave.call("POST", f"/{cid}/challenges/{ch}/join", 200).json()["value"] == "12.0 km"
    # Bob's claim on the shared result collides on the real primary key (inside a savepoint, so his transaction survives) and he keeps his own
    assert bob.call("POST", f"/{cid}/challenges/{ch}/join", 200).json()["value"] == "5.0 km"
    standings = owner.call("GET", f"/{cid}/challenges/{ch}", 200).json()["standings"]                     # a member reads others' standings through the policy
    assert [(s["name"], s["value"]) for s in standings] == [("PgChDave", "12.0 km"), ("PgChBob", "5.0 km")]
    assert bob.call("GET", f"/{cid}/challenges/{ch}", 200).json()["my_value"] == "5.0 km"
    dave.call("POST", f"/{cid}/challenges/{ch}/leave", 200)                                              # leaving releases Dave's claim
    assert bob.call("GET", f"/{cid}/challenges/{ch}", 200).json()["my_value"] == "17.0 km"
    # nobody can write someone else's standing, even by calling the table
    with tenant.use_owner(dave.id), Session(runtime) as s:
        assert s.execute(text("UPDATE club_challenge_entries SET value = 999999 WHERE owner_id = :o"), {"o": bob.id}).rowcount == 0


def test_participation_counts_and_summaries_are_aggregate_only_on_the_real_database(env, runtime):
    owner, a, b, c = people(env, "to", "ta", "tb", "tc")
    for who, handle in ((owner, "PgTeamOwner"), (a, "PgTeamA"), (b, "PgTeamB"), (c, "PgTeamC")):
        who.profile(handle)
    cid = owner.make("Pg Team Club", join_policy="invite")
    for who in (a, b, c):
        who.join(owner.invite(cid))
    sid = owner.call("POST", f"/{cid}/sessions", 200, json={"title": "Steady 60", "session_type": "erg", "date": date.today().isoformat()}).json()["id"]
    for i, who in enumerate((a, b, c)):
        _, cn = seed_activity(runtime, who, "garmin", f"t{i}", 0, distance=10000 + 1000 * i)
        who.call("POST", f"/{cid}/sessions/{sid}/participation", 200, json={"canonical_id": cn, "share_numbers": True})
    s = a.call("GET", f"/{cid}/summary", 200).json()
    assert s["participations"] == 3 and s["distance_m"]["total"] == 33000
    assert a.call("GET", f"/{cid}/calendar", 200).json()["sessions"][0]["participants"] == 3
    c.call("DELETE", f"/{cid}/sessions/{sid}/participation", 200)
    s = a.call("GET", f"/{cid}/summary", 200).json()
    assert s["distance_m"]["total"] is None and s["distance_m"]["suppressed"] is True    # two sharers: nothing that could be one person's number
    blob = json.dumps(s)
    assert all(w.id not in blob for w in (owner, a, b, c))


# ---------------------------------------------------------------- moderation, deletion, logo

def test_reports_moderation_and_account_deletion_through_the_system_role(env, runtime, admin):
    owner, a, b, c, mod = people(env, "mo", "ma", "mb", "mc", "mm")
    object.__setattr__(config.settings, "moderator_ids", mod.id)
    for who, handle in ((owner, "PgModOwner"), (a, "PgModA"), (b, "PgModB"), (c, "PgModC")):
        who.profile(handle)
    cid = owner.make("Pg Moderated Club", visibility="public", join_policy="open")
    for who in (a, b, c):
        assert who.call("POST", "/join", 200, json={"club_id": cid}).json()["status"] == "joined"
    post = owner.call("POST", f"/{cid}/announcements", 200, json={"title": "Spicy", "body": "A questionable post"}).json()["id"]
    for who in (a, b, c):
        who.call("POST", f"/{cid}/report", 200, json={"target_type": "announcement", "target_id": str(post), "reason": "inappropriate"})
    assert a.call("GET", f"/{cid}/announcements", 200).json()["announcements"] == []      # the third distinct report hid it (system role UPDATE)
    assert any(e["action"] == "post_auto_hidden" for e in owner.call("GET", f"/{cid}/audit", 200).json()["events"])
    for who in (owner, a):                                                                # reports are the reporter's and the moderators', no one else's
        assert who.call("GET", f"/{cid}/reports").status_code in (404, 405)
    with tenant.use_owner(owner.id), Session(runtime) as s:
        assert s.execute(text("SELECT count(*) FROM club_reports")).scalar() == 0
    with tenant.use_owner(a.id), Session(runtime) as s:
        assert s.execute(text("SELECT count(*) FROM club_reports")).scalar() == 1         # only their own
    h = lambda who: who.user.headers  # noqa: E731
    queue = env.get("/api/moderation/clubs/queue", headers=h(mod))
    assert queue.status_code == 200 and queue.json()["reports"][0]["reports"] == 3 and a.id not in queue.text
    assert env.get("/api/moderation/clubs/queue", headers=h(owner)).status_code == 404
    assert env.post(f"/api/moderation/clubs/{cid}/action", headers=h(mod), json={"action": "suspend_club", "reason": "Under review"}).status_code == 200
    assert mod.call("GET", "/discover", 200).json()["clubs"] == [] and a.call("GET", f"/{cid}", 200).json()["status"] == "suspended"
    with admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM catch.club_audit WHERE club_id = :c AND actor_kind = 'moderator'"), {"c": cid}).scalar() == 1

    # deleting the owner's account hands the club to the longest-standing eligible member, and what they did stays, detached from them
    assert env.request("DELETE", "/api/account", headers=h(owner), json={"confirm": "DELETE"}).status_code == 200
    assert {m["handle"]: m["role"] for m in a.members(cid)}["PgModA"] == "owner"
    with admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM catch.club_audit WHERE actor_id = :o OR subject_owner_id = :o"), {"o": owner.id}).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM catch.club_audit WHERE club_id = :c AND action = 'club_created'"), {"c": cid}).scalar() == 1
    # a club whose last member deletes their account is deleted with them, leaving only its audit trail
    for who in (a, b, c):
        assert env.request("DELETE", "/api/account", headers=h(who), json={"confirm": "DELETE"}).status_code == 200
    with admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM catch.clubs WHERE club_id = :c"), {"c": cid}).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM catch.club_audit WHERE club_id = :c"), {"c": cid}).scalar() >= 1


def test_a_logo_is_stored_and_served_under_the_visibility_policy(env):
    owner, member, stranger = people(env, "lo", "lm", "ls")
    for who, handle in ((owner, "PgLogoOwner"), (member, "PgLogoMember"), (stranger, "PgLogoStranger")):
        who.profile(handle)
    pub = owner.make("Pg Public Logos", visibility="public", join_policy="open")
    priv = owner.make("Pg Private Logos")
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 200
    for cid in (pub, priv):
        r = env.put(f"/api/clubs/{cid}/logo", headers={**owner.user.headers, "content-type": "image/png"}, content=png)
        assert r.status_code == 200, r.text
    member.call("POST", "/join", 200, json={"club_id": pub})
    assert stranger.call("GET", f"/{pub}/logo", 200).content == png and stranger.call("GET", f"/{priv}/logo").status_code == 404
    assert env.put(f"/api/clubs/{pub}/logo", headers={**member.user.headers, "content-type": "image/png"}, content=png).status_code == 403
    assert [k["name"] for k in stranger.call("GET", "/discover", 200).json()["clubs"]] == ["Pg Public Logos"]
