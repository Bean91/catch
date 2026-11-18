"""Session 27 on real Postgres: membership-scoped RLS for clubs (docs/clubs.md §10). Everything here is plain SQL run as
`authenticated` with a user's claims — the exact identity switch tenant_hooks performs — so these prove what the DATABASE
refuses regardless of what the application remembers to check. The SQLite suite (tests/tenancy/test_clubs_*.py) proves the
service logic; tests/pg/test_clubs_api.py runs the API on this same stack."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.pg.conftest import RUNTIME_PASSWORD, run_alembic
from tests.pg.test_rls import as_user

pytestmark = pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")

MEMBERS_COLS = "club_id, owner_id, club_audience, role, status, age_class, joined_at"


@pytest.fixture()
def env(clean, admin, runtime):
    yield admin, runtime
    with admin.begin() as conn:
        for t in ("club_audit", "clubs", "club_profiles"):
            conn.execute(text(f"DELETE FROM catch.{t}"))


# ---------------------------------------------------------------- seeding (as the database owner, bypassing RLS)

def users(admin, *names):
    ids = {}
    with admin.begin() as conn:
        for n in names:
            ids[n] = str(uuid.uuid4())  # auth.uid() casts the claim to uuid
            conn.execute(text("INSERT INTO catch.user_profiles (id, created_at) VALUES (:i, now())"), {"i": ids[n]})
    return ids


def profile(admin, uid, age="adult"):
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO catch.club_profiles (owner_id, handle, handle_ci, age_band, age_class, created_at, updated_at) "
                          "VALUES (:u, :u, :u, :b, :c, now(), now())"), {"u": uid, "b": "U17" if age == "youth" else "adult", "c": age})


def mkclub(admin, creator, *, audience="adult", visibility="private", policy="request", status="active", cid=None):
    cid = cid or f"c-{uuid.uuid4().hex[:8]}"
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO catch.clubs (club_id, name, name_ci, visibility, audience, join_policy, status, has_logo, created_by, created_at) "
                          "VALUES (:c, :n, :n, :v, :a, :p, :s, false, :u, now())"), {"c": cid, "n": cid, "v": visibility, "a": audience, "p": policy, "s": status, "u": creator})
    return cid


def mkmember(admin, cid, uid, role="athlete", audience="adult", status="active"):
    age = "youth" if role == "athlete" and audience == "junior" else "adult"
    with admin.begin() as conn:
        conn.execute(text(f"INSERT INTO catch.club_members ({MEMBERS_COLS}) VALUES (:c, :u, :a, :r, :s, :g, now())"), {"c": cid, "u": uid, "a": audience, "r": role, "s": status, "g": age})
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO catch.club_profiles (owner_id, handle, handle_ci, age_band, age_class, created_at, updated_at) VALUES (:u, :u, :u, :b, :g, now(), now()) "
                          "ON CONFLICT (owner_id) DO NOTHING"), {"u": uid, "b": "U17" if age == "youth" else "adult", "g": age})


def team(admin, *, audience="adult", visibility="private", policy="request"):
    """owner, admin, coach, two athletes in one club."""
    u = users(admin, "own", "adm", "coa", "ath", "bth")
    cid = mkclub(admin, u["own"], audience=audience, visibility=visibility, policy=policy)
    for role, n in (("owner", "own"), ("admin", "adm"), ("coach", "coa"), ("athlete", "ath"), ("athlete", "bth")):
        mkmember(admin, cid, u[n], role, audience)
    return cid, u


def run(runtime, uid, sql, **p):
    with as_user(runtime, uid) as conn:
        r = conn.execute(text(sql), p)
        out = r.all() if r.returns_rows else r.rowcount
        conn.commit()  # as_user rolls back on exit; the next statement (a separate transaction) must see this one's effect
        return out


def denied(runtime, uid, sql, **p):
    with pytest.raises(DBAPIError):
        run(runtime, uid, sql, **p)


# ---------------------------------------------------------------- helpers are not silently false

def test_the_predicates_are_true_for_a_real_member_and_false_for_everyone_else(env):
    admin, runtime = env
    cid, u = team(admin)
    out = users(admin, "out")["out"]
    with as_user(runtime, u["ath"]) as conn:
        q = lambda sql, **p: conn.execute(text(sql), {"c": cid, "u": u["ath"], "o": u["own"], "x": out, **p}).scalar()  # noqa: E731
        assert q("SELECT catch_club.role_of(:c, :u)") == "athlete"
        assert q("SELECT catch_club.is_member(:c, :u)") is True and q("SELECT catch_club.is_staff(:c, :u)") is False
        assert q("SELECT catch_club.is_staff(:c, :o)") is True and q("SELECT catch_club.is_admin(:c, :o)") is True
        assert q("SELECT catch_club.is_member(:c, :x)") is False and q("SELECT catch_club.role_of(:c, :x)") is None
        assert q("SELECT catch_club.member_count(:c)") == 5


# ---------------------------------------------------------------- cross-club isolation

def test_a_member_of_one_club_reads_nothing_private_from_another(env):
    admin, runtime = env
    c1, u1 = team(admin)
    c2, u2 = team(admin)
    with admin.begin() as conn:
        for cid, owner in ((c1, u1["own"]), (c2, u2["own"])):
            conn.execute(text("INSERT INTO catch.club_announcements (club_id, author_id, title, body, status, created_at) VALUES (:c, :o, 'hello', 'body', 'published', now())"), {"c": cid, "o": owner})
            conn.execute(text("INSERT INTO catch.club_sessions (club_id, created_by, title, session_type, date, status, created_at) VALUES (:c, :o, 's', 'erg', :d, 'published', now())"), {"c": cid, "o": owner, "d": date.today()})
            conn.execute(text("INSERT INTO catch.club_audit (club_id, actor_id, actor_kind, action, reason_text, created_at) VALUES (:c, :o, 'staff', 'x', 'why', now())"), {"c": cid, "o": owner})
    for me, mine, theirs in ((u1["own"], c1, c2), (u1["ath"], c1, c2), (u2["coa"], c2, c1)):
        assert {r[0] for r in run(runtime, me, "SELECT club_id FROM clubs")} == {mine}, "a private club of someone else is visible"
        assert {r[0] for r in run(runtime, me, "SELECT club_id FROM club_members")} == {mine}
        assert {r[0] for r in run(runtime, me, "SELECT club_id FROM club_announcements")} == {mine}
        assert {r[0] for r in run(runtime, me, "SELECT club_id FROM club_sessions")} == {mine}
        assert run(runtime, me, "SELECT count(*) FROM club_members WHERE club_id = :c", c=theirs) == [(0,)]
        assert run(runtime, me, "UPDATE clubs SET description = 'x' WHERE club_id = :c", c=theirs) == 0
        assert run(runtime, me, "DELETE FROM club_announcements WHERE club_id = :c", c=theirs) == 0
    # the audit trail is staff-only, and only for their own club
    assert {r[0] for r in run(runtime, u1["own"], "SELECT club_id FROM club_audit")} == {c1}
    assert run(runtime, u1["ath"], "SELECT count(*) FROM club_audit") == [(0,)]


def test_a_public_club_is_discoverable_but_its_insides_are_not(env):
    admin, runtime = env
    cid, u = team(admin, visibility="public", policy="open")
    outsider = users(admin, "out")["out"]
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO catch.club_announcements (club_id, author_id, title, body, status, created_at) VALUES (:c, :o, 'a', 'b', 'published', now())"), {"c": cid, "o": u["own"]})
    assert {r[0] for r in run(runtime, outsider, "SELECT club_id FROM clubs")} == {cid}
    assert run(runtime, outsider, "SELECT count(*) FROM club_members") == [(0,)]
    assert run(runtime, outsider, "SELECT count(*) FROM club_announcements") == [(0,)]
    assert run(runtime, outsider, "SELECT catch_club.member_count(:c)", c=cid) == [(5,)]  # a count, never a list


def test_a_junior_club_is_never_discoverable_and_a_suspended_one_leaves_discovery(env):
    admin, runtime = env
    outsider = users(admin, "out")["out"]
    jc, _ = team(admin, audience="junior")
    pc, up = team(admin, visibility="public", policy="open")
    assert {r[0] for r in run(runtime, outsider, "SELECT club_id FROM clubs")} == {pc}
    with admin.begin() as conn:
        conn.execute(text("UPDATE catch.clubs SET status = 'suspended' WHERE club_id = :c"), {"c": pc})
    assert run(runtime, outsider, "SELECT count(*) FROM clubs") == [(0,)]
    assert {r[0] for r in run(runtime, up["ath"], "SELECT club_id FROM clubs")} == {pc}  # members keep read access


# ---------------------------------------------------------------- the schema's own invariants

def test_the_age_and_junior_rules_are_check_constraints_not_just_code(env):
    admin, _ = env
    u = users(admin, "own", "a", "b")
    jc = mkclub(admin, u["own"], audience="junior")
    for uid, role, age, ok in (
        (u["own"], "owner", "adult", True), (u["a"], "athlete", "youth", True),
        (u["b"], "athlete", "adult", False),    # an adult athlete in a junior club
    ):
        with admin.connect() as conn:
            try:
                conn.execute(text(f"INSERT INTO catch.club_members ({MEMBERS_COLS}) VALUES (:c, :u, 'junior', :r, 'active', :g, now())"), {"c": jc, "u": uid, "r": role, "g": age})
                conn.commit()
                assert ok
            except Exception:
                conn.rollback()
                assert not ok
    ac = mkclub(admin, u["own"])
    for role, age in (("athlete", "youth"), ("coach", "youth")):  # a young person in an adult club, or as junior-club staff
        with admin.connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(text(f"INSERT INTO catch.club_members ({MEMBERS_COLS}) VALUES (:c, :u, 'adult', :r, 'active', :g, now())"), {"c": ac, "u": u["b"], "r": role, "g": age})
    with admin.connect() as conn:
        with pytest.raises(DBAPIError):  # a junior club must be private and request-only
            conn.execute(text("INSERT INTO catch.clubs (club_id, name, name_ci, visibility, audience, join_policy, status, has_logo, created_at) VALUES ('j2','j2','j2','public','junior','open','active',false,now())"))


def test_there_is_exactly_one_active_owner_and_audience_cannot_change(env):
    admin, _ = env
    cid, u = team(admin, audience="junior")
    with admin.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("UPDATE catch.club_members SET role = 'owner' WHERE club_id = :c AND owner_id = :u"), {"c": cid, "u": u["coa"]})
    with admin.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("UPDATE catch.clubs SET audience = 'adult' WHERE club_id = :c"), {"c": cid})


def test_a_volume_challenge_cannot_exist_without_a_cap(env):
    admin, _ = env
    cid, u = team(admin)
    ins = ("INSERT INTO catch.club_challenges (club_id, created_by, title, metric, sport, start_date, end_date, goal, min_session_s, status, created_at) "
           "VALUES (:c, :o, 't', :m, 'rowing', :s, :e, :g, 1200, 'active', now())")
    base = {"c": cid, "o": u["own"], "s": date.today(), "e": date.today() + timedelta(days=14)}
    for metric in ("distance", "time"):
        with admin.connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(text(ins), {**base, "m": metric, "g": None})
    with admin.begin() as conn:
        conn.execute(text(ins), {**base, "m": "distance", "g": 100000})


# ---------------------------------------------------------------- roles, enforced by policies

def test_the_role_matrix_is_enforced_by_the_database(env):
    admin, runtime = env
    cid, u = team(admin)
    upd = "UPDATE club_members SET role = :r WHERE club_id = :c AND owner_id = :t"
    assert run(runtime, u["adm"], upd, r="coach", c=cid, t=u["bth"]) == 1                 # admin promotes an athlete
    denied(runtime, u["adm"], upd, r="admin", c=cid, t=u["ath"])                           # ...but cannot mint another admin
    assert run(runtime, u["adm"], upd, r="athlete", c=cid, t=u["own"]) == 0                # ...nor touch the owner
    assert run(runtime, u["coa"], upd, r="athlete", c=cid, t=u["adm"]) == 0                # a coach cannot demote an admin
    assert run(runtime, u["ath"], upd, r="athlete", c=cid, t=u["bth"]) == 0                # an athlete manages no one
    assert run(runtime, u["ath"], upd, r="owner", c=cid, t=u["ath"]) == 0                  # nobody promotes themselves
    assert run(runtime, u["ath"], upd, r="admin", c=cid, t=u["ath"]) == 0
    rm = "UPDATE club_members SET status = 'removed' WHERE club_id = :c AND owner_id = :t"
    assert run(runtime, u["coa"], rm, c=cid, t=u["ath"]) == 1                              # a coach removes an athlete
    assert run(runtime, u["coa"], rm, c=cid, t=u["own"]) == 0
    assert run(runtime, u["ath"], "SELECT catch_club.is_member(:c, :u)", c=cid, u=u["ath"]) == [(False,)]  # removed means out
    stranger = users(admin, "str")["str"]
    for who, sees in ((u["own"], 1), (u["coa"], 1), (stranger, 0)):  # staff still read the handle of someone they removed (the audit trail stays legible); a stranger doesn't
        assert run(runtime, who, "SELECT count(*) FROM club_profiles WHERE owner_id = :t", t=u["ath"]) == [(sees,)], who
    assert [r[0] for r in run(runtime, u["ath"], "SELECT status FROM club_members")] == ["removed"]         # they see only their own tombstone


def test_a_member_cannot_flip_their_own_role_or_status_through_the_prefs_table_or_columns(env):
    admin, runtime = env
    cid, u = team(admin)
    denied(runtime, u["ath"], "UPDATE club_members SET age_class = 'adult' WHERE owner_id = :u", u=u["ath"])   # no column grant
    assert run(runtime, u["ath"], "INSERT INTO club_member_prefs (club_id, owner_id, include_public_results, share_numbers) VALUES (:c, :u, false, true)", c=cid, u=u["ath"]) == 1
    denied(runtime, u["ath"], "INSERT INTO club_member_prefs (club_id, owner_id, include_public_results, share_numbers) VALUES (:c, :u, false, true)", c=cid, u=u["own"])  # someone else's
    denied(runtime, u["own"], "UPDATE clubs SET status = 'suspended' WHERE club_id = :c", c=cid)  # moderators only: no column grant
    denied(runtime, u["own"], "UPDATE clubs SET audience = 'adult' WHERE club_id = :c", c=cid)
    assert run(runtime, u["adm"], "UPDATE clubs SET description = 'new' WHERE club_id = :c", c=cid) == 1
    assert run(runtime, u["coa"], "UPDATE clubs SET description = 'new' WHERE club_id = :c", c=cid) == 0


def test_leaving_is_allowed_but_the_owner_must_transfer_first(env):
    admin, runtime = env
    cid, u = team(admin)
    assert run(runtime, u["ath"], "DELETE FROM club_members WHERE club_id = :c AND owner_id = :u", c=cid, u=u["ath"]) == 1
    assert run(runtime, u["own"], "DELETE FROM club_members WHERE club_id = :c AND owner_id = :u", c=cid, u=u["own"]) == 0
    with as_user(runtime, u["adm"]) as conn:  # only the owner may hand it over
        with pytest.raises(DBAPIError):
            conn.execute(text("SELECT catch_club.transfer_ownership(:c, :t)"), {"c": cid, "t": u["coa"]})
    with as_user(runtime, u["own"]) as conn:
        conn.execute(text("SELECT catch_club.transfer_ownership(:c, :t)"), {"c": cid, "t": u["adm"]})
        assert dict(conn.execute(text("SELECT owner_id, role FROM club_members WHERE role IN ('owner','admin')")).all()) == {u["adm"]: "owner", u["own"]: "admin"}
    with as_user(runtime, u["own"]) as conn:  # a non-member can't be handed a club
        with pytest.raises(DBAPIError):
            conn.execute(text("SELECT catch_club.transfer_ownership(:c, 'nobody')"), {"c": cid})


# ---------------------------------------------------------------- joining

def _join(runtime, uid, cid, role="athlete", audience="adult"):
    age = "youth" if role == "athlete" and audience == "junior" else "adult"
    return run(runtime, uid, f"INSERT INTO club_members ({MEMBERS_COLS}) VALUES (:c, :u, :a, :r, 'active', :g, now())", c=cid, u=uid, a=audience, r=role, g=age)


def test_open_join_works_only_for_a_public_adult_club_and_only_as_athlete(env):
    admin, runtime = env
    cid, _ = team(admin, visibility="public", policy="open")
    private, _ = team(admin)
    joiner = users(admin, "j")["j"]
    profile(admin, joiner)
    denied(runtime, joiner, f"INSERT INTO club_members ({MEMBERS_COLS}) VALUES (:c, :u, 'adult', 'coach', 'active', 'adult', now())", c=cid, u=joiner)
    denied(runtime, joiner, f"INSERT INTO club_members ({MEMBERS_COLS}) VALUES (:c, :u, 'adult', 'athlete', 'active', 'adult', now())", c=private, u=joiner)
    assert _join(runtime, joiner, cid) == 1
    youth = users(admin, "y")["y"]
    profile(admin, youth, "youth")
    denied(runtime, youth, f"INSERT INTO club_members ({MEMBERS_COLS}) VALUES (:c, :u, 'adult', 'athlete', 'active', 'youth', now())", c=cid, u=youth)  # youth never joins an adult club


def test_a_removed_member_cannot_rejoin_even_an_open_club(env):
    admin, runtime = env
    cid, u = team(admin, visibility="public", policy="open")
    run(runtime, u["coa"], "UPDATE club_members SET status = 'removed' WHERE club_id = :c AND owner_id = :t", c=cid, t=u["ath"])
    assert run(runtime, u["ath"], "DELETE FROM club_members WHERE club_id = :c AND owner_id = :u", c=cid, u=u["ath"]) == 0  # their own tombstone isn't theirs to delete away
    assert run(runtime, u["ath"], "SELECT status FROM club_members") == [("removed",)]
    denied(runtime, u["ath"], f"INSERT INTO club_members ({MEMBERS_COLS}) VALUES (:c, :u, 'adult', 'athlete', 'active', 'adult', now())", c=cid, u=u["ath"])


def _invite(admin, cid, by, role="athlete", *, days=7, max_uses=None, revoked=False):
    token = uuid.uuid4().hex
    with admin.begin() as conn:
        iid = conn.execute(text("INSERT INTO catch.club_invites (club_id, token_hash, role, created_by, expires_at, max_uses, revoked_at, created_at) "
                                "VALUES (:c, :t, :r, :b, now() + make_interval(days => :d), :m, :rv, now()) RETURNING id"),
                           {"c": cid, "t": token, "r": role, "b": by, "d": days, "m": max_uses, "rv": datetime.now(timezone.utc) if revoked else None}).scalar()
    return iid, token


REQ = ("INSERT INTO club_join_requests (club_id, owner_id, role, status, via_invite_id, created_at{extra}) VALUES (:c, :u, :r, :s, :i, now(){extra_v})")


def _request(runtime, uid, cid, inv, role="athlete", status="pending"):
    return run(runtime, uid, REQ.format(extra="", extra_v=""), c=cid, u=uid, r=role, s=status, i=inv)


def test_an_invite_link_joins_a_private_adult_club_directly_only_while_valid(env):
    admin, runtime = env
    cid, u = team(admin, policy="invite")
    good, _ = _invite(admin, cid, u["own"])
    expired, _ = _invite(admin, cid, u["own"], days=-1)
    revoked, _ = _invite(admin, cid, u["own"], revoked=True)
    single, _ = _invite(admin, cid, u["own"], max_uses=1)
    a, b, c, d, e = (users(admin, n)[n] for n in "abcde")
    for x in (a, b, c, d, e):
        profile(admin, x)
    denied(runtime, a, REQ.format(extra="", extra_v=""), c=cid, u=a, r="athlete", s="approved", i=None)       # a private club needs an invite
    denied(runtime, a, REQ.format(extra="", extra_v=""), c=cid, u=a, r="athlete", s="approved", i=expired)
    denied(runtime, a, REQ.format(extra="", extra_v=""), c=cid, u=a, r="athlete", s="approved", i=revoked)
    assert _request(runtime, a, cid, good, status="approved") == 1
    assert _join(runtime, a, cid) == 1                                                                         # the approved request lets them in
    denied(runtime, b, REQ.format(extra="", extra_v=""), c=cid, u=b, r="coach", s="approved", i=good)          # an athlete invite doesn't make a coach
    assert _request(runtime, c, cid, single, status="approved") == 1
    denied(runtime, d, REQ.format(extra="", extra_v=""), c=cid, u=d, r="athlete", s="approved", i=single)      # max uses reached
    denied(runtime, e, f"INSERT INTO club_members ({MEMBERS_COLS}) VALUES (:c, :u, 'adult', 'athlete', 'active', 'adult', now())", c=cid, u=e)  # no request, no entry


def test_nobody_can_approve_their_own_request_and_a_request_in_a_request_club_waits(env):
    admin, runtime = env
    cid, u = team(admin, visibility="public", policy="request")
    a = users(admin, "a")["a"]
    profile(admin, a)
    denied(runtime, a, REQ.format(extra="", extra_v=""), c=cid, u=a, r="athlete", s="approved", i=None)
    assert _request(runtime, a, cid, None) == 1
    denied(runtime, a, f"INSERT INTO club_members ({MEMBERS_COLS}) VALUES (:c, :u, 'adult', 'athlete', 'active', 'adult', now())", c=cid, u=a)  # pending is not approved
    assert run(runtime, a, "UPDATE club_join_requests SET status = 'approved', decided_by = :u WHERE owner_id = :u", u=a) == 0
    assert run(runtime, u["ath"], "UPDATE club_join_requests SET status = 'approved', decided_by = :u WHERE owner_id = :a", u=u["ath"], a=a) == 0  # an athlete decides nothing
    other = users(admin, "o2")["o2"]
    profile(admin, other)
    assert _request(runtime, other, cid, None) == 1
    denied(runtime, u["coa"], "UPDATE club_join_requests SET status = 'approved', decided_by = :x WHERE owner_id = :a", x=u["own"], a=other)  # can't attribute a decision to someone else
    assert run(runtime, u["coa"], "UPDATE club_join_requests SET status = 'approved', decided_by = :u WHERE owner_id = :a", u=u["coa"], a=a) == 1
    assert _join(runtime, a, cid) == 1


def test_the_junior_club_rules_hold_at_the_database(env):
    admin, runtime = env
    cid, u = team(admin, audience="junior")
    inv_a, _ = _invite(admin, cid, u["coa"])
    inv_c, _ = _invite(admin, cid, u["own"], "coach")
    kid, other, adult, adult2 = (users(admin, n)[n] for n in ("kid", "oth", "adu", "ad2"))
    for who, age in ((kid, "youth"), (other, "youth"), (adult, "adult"), (adult2, "adult")):
        profile(admin, who, age)
    # a young person asks; nothing is ever auto-approved in a junior club
    assert _request(runtime, kid, cid, inv_a) == 1
    denied(runtime, other, REQ.format(extra="", extra_v=""), c=cid, u=other, r="athlete", s="approved", i=inv_a)
    denied(runtime, adult, REQ.format(extra="", extra_v=""), c=cid, u=adult, r="athlete", s="pending", i=inv_a)        # an adult isn't an athlete here
    denied(runtime, kid, REQ.format(extra="", extra_v=""), c=cid, u=kid, r="coach", s="pending", i=inv_c)              # and a young person is never staff
    # only a COACH approves an athlete: the owner and an admin cannot
    decide = "UPDATE club_join_requests SET status = 'approved', decided_by = :d WHERE owner_id = :k"
    assert run(runtime, u["own"], decide, d=u["own"], k=kid) == 0
    assert run(runtime, u["adm"], decide, d=u["adm"], k=kid) == 0
    assert run(runtime, u["coa"], decide, d=u["coa"], k=kid) == 1
    assert _join(runtime, kid, cid, "athlete", "junior") == 1
    assert run(runtime, kid, "UPDATE club_members SET role = 'coach' WHERE owner_id = :u", u=kid) == 0     # nobody promotes themselves
    # an adult can join as a coach: by invite, approved by an owner/admin (not a coach)
    assert _request(runtime, adult, cid, inv_c, "coach") == 1
    assert run(runtime, u["coa"], decide + " AND role = 'coach'", d=u["coa"], k=adult) == 0
    assert run(runtime, u["adm"], decide + " AND role = 'coach'", d=u["adm"], k=adult) == 1
    assert _join(runtime, adult, cid, "coach", "junior") == 1


def test_a_young_person_cannot_create_a_club_or_see_a_junior_club_they_were_not_invited_to(env):
    admin, runtime = env
    kid = users(admin, "kid")["kid"]
    profile(admin, kid, "youth")
    denied(runtime, kid, "INSERT INTO clubs (club_id, name, name_ci, visibility, audience, join_policy, status, has_logo, created_by, created_at) "
                         "VALUES ('k1','k1','k1','private','junior','request','active',false,:u,now())", u=kid)
    cid, _ = team(admin, audience="junior")
    assert run(runtime, kid, "SELECT count(*) FROM clubs WHERE club_id = :c", c=cid) == [(0,)]


# ---------------------------------------------------------------- posts and approval

def _post_sql(table):
    if table == "club_announcements":
        return "INSERT INTO club_announcements (club_id, author_id, title, body, status, created_at) VALUES (:c, :u, 't', 'b', :s, now())", {}
    return "INSERT INTO club_sessions (club_id, created_by, title, session_type, date, status, created_at) VALUES (:c, :u, 't', 'erg', :d, :s, now())", {"d": date.today()}


def _post(runtime, uid, cid, status, table="club_announcements"):
    sql, extra = _post_sql(table)
    return run(runtime, uid, sql, c=cid, u=uid, s=status, **extra)


def _post_denied(runtime, uid, cid, status, table="club_announcements"):
    sql, extra = _post_sql(table)
    denied(runtime, uid, sql, c=cid, u=uid, s=status, **extra)


@pytest.mark.parametrize("table", ["club_announcements", "club_sessions"])
def test_in_a_junior_club_only_a_coach_publishes_and_anyone_elses_post_waits(env, table):
    admin, runtime = env
    cid, u = team(admin, audience="junior")
    _post_denied(runtime, u["own"], cid, "published", table)
    assert _post(runtime, u["own"], cid, "pending", table) == 1
    assert _post(runtime, u["adm"], cid, "pending", table) == 1
    _post_denied(runtime, u["adm"], cid, "published", table)
    assert _post(runtime, u["coa"], cid, "published", table) == 1                         # a coach's own post goes straight out
    _post_denied(runtime, u["ath"], cid, "pending", table)                                # athletes post nothing
    assert run(runtime, u["ath"], f"SELECT count(*) FROM {table}") == [(1,)]              # pending ones are invisible to athletes...
    assert run(runtime, u["adm"], f"SELECT count(*) FROM {table}") == [(3,)]              # ...and visible to staff
    approve = f"UPDATE {table} SET status = 'published' WHERE club_id = :c AND status = 'pending'"
    denied(runtime, u["own"], approve, c=cid)                                             # the owner can't publish what isn't theirs to publish here
    assert run(runtime, u["coa"], approve, c=cid) == 2
    assert run(runtime, u["ath"], f"SELECT count(*) FROM {table}") == [(3,)]
    down = "hidden" if table == "club_announcements" else "cancelled"
    assert run(runtime, u["own"], f"UPDATE {table} SET status = '{down}' WHERE club_id = :c", c=cid) == 3  # any staff can take a post down


def test_in_an_adult_club_any_staff_publishes_directly(env):
    admin, runtime = env
    cid, u = team(admin)
    for who in ("own", "adm", "coa"):
        assert _post(runtime, u[who], cid, "published") == 1
    _post_denied(runtime, u["ath"], cid, "published")
    denied(runtime, u["coa"], "INSERT INTO club_announcements (club_id, author_id, title, body, status, created_at) VALUES (:c, :x, 't', 'b', 'published', now())", c=cid, x=u["own"])  # not as someone else


# ---------------------------------------------------------------- participation, challenges, claims

def _challenge(admin, cid, by, *, end=None, status="active"):
    with admin.begin() as conn:
        return conn.execute(text("INSERT INTO catch.club_challenges (club_id, created_by, title, metric, sport, start_date, end_date, goal, min_session_s, status, created_at) "
                                 "VALUES (:c, :o, 't', 'distance', 'rowing', :s, :e, 100000, 1200, :st, now()) RETURNING id"),
                            {"c": cid, "o": by, "s": date.today() - timedelta(days=20), "e": end or date.today() + timedelta(days=10), "st": status}).scalar()


def test_challenge_standings_are_written_only_by_their_owner_and_only_while_open(env):
    admin, runtime = env
    cid, u = team(admin)
    open_id = _challenge(admin, cid, u["own"])
    closed_id = _challenge(admin, cid, u["own"], end=date.today() - timedelta(days=5))
    pending_id = _challenge(admin, cid, u["own"], status="pending")
    ins = "INSERT INTO club_challenge_entries (challenge_id, owner_id, club_id, status, value, joined_at, updated_at) VALUES (:i, :u, :c, 'joined', 0, now(), now())"
    assert run(runtime, u["ath"], ins, i=open_id, u=u["ath"], c=cid) == 1
    denied(runtime, u["ath"], ins, i=closed_id, u=u["ath"], c=cid)           # frozen after the grace period
    denied(runtime, u["ath"], ins, i=pending_id, u=u["ath"], c=cid)          # not approved yet
    denied(runtime, u["bth"], ins, i=open_id, u=u["ath"], c=cid)             # can't enter on someone else's behalf
    assert run(runtime, u["ath"], "UPDATE club_challenge_entries SET value = 5000 WHERE challenge_id = :i", i=open_id) == 1
    assert run(runtime, u["bth"], "UPDATE club_challenge_entries SET value = 999999 WHERE challenge_id = :i", i=open_id) == 0   # no tampering with another's score
    assert run(runtime, u["bth"], "SELECT value FROM club_challenge_entries WHERE challenge_id = :i", i=open_id) == [(5000,)]   # but the standing is club-visible
    outsider = users(admin, "out")["out"]
    assert run(runtime, outsider, "SELECT count(*) FROM club_challenge_entries") == [(0,)]
    denied(runtime, outsider, ins, i=open_id, u=outsider, c=cid)             # not a member: the composite FK refuses it


def test_one_provider_activity_cannot_be_claimed_by_two_accounts(env):
    admin, runtime = env
    cid, u = team(admin)
    ch = _challenge(admin, cid, u["own"])
    claim = "INSERT INTO club_challenge_claims (challenge_id, activity_key, owner_id) VALUES (:i, :k, :u)"
    assert run(runtime, u["ath"], claim, i=ch, k="hmac-1", u=u["ath"]) == 1
    with pytest.raises(DBAPIError):
        run(runtime, u["bth"], claim, i=ch, k="hmac-1", u=u["bth"])         # the primary key is global even though B can't see A's row
    assert run(runtime, u["bth"], "SELECT count(*) FROM club_challenge_claims") == [(0,)]
    denied(runtime, u["bth"], claim, i=ch, k="hmac-2", u=u["ath"])           # nor claim in someone else's name


def test_session_participation_needs_a_published_session_and_membership(env):
    admin, runtime = env
    cid, u = team(admin)
    with admin.begin() as conn:
        pub = conn.execute(text("INSERT INTO catch.club_sessions (club_id, created_by, title, session_type, date, status, created_at) VALUES (:c, :o, 's', 'erg', :d, 'published', now()) RETURNING id"), {"c": cid, "o": u["own"], "d": date.today()}).scalar()
        pend = conn.execute(text("INSERT INTO catch.club_sessions (club_id, created_by, title, session_type, date, status, created_at) VALUES (:c, :o, 's', 'erg', :d, 'pending', now()) RETURNING id"), {"c": cid, "o": u["own"], "d": date.today()}).scalar()
    ins = "INSERT INTO club_session_participation (session_id, owner_id, club_id, shared_distance_m, created_at) VALUES (:s, :u, :c, :d, now())"
    assert run(runtime, u["ath"], ins, s=pub, u=u["ath"], c=cid, d=None) == 1
    denied(runtime, u["bth"], ins, s=pend, u=u["bth"], c=cid, d=None)
    denied(runtime, u["bth"], ins, s=pub, u=u["ath"], c=cid, d=None)
    outsider = users(admin, "out")["out"]
    denied(runtime, outsider, ins, s=pub, u=outsider, c=cid, d=None)


# ---------------------------------------------------------------- audit, reports, results, logos

def test_the_audit_log_is_append_only_for_everyone_the_app_runs_as(env):
    admin, runtime = env
    cid, u = team(admin)
    ins = "INSERT INTO club_audit (club_id, actor_id, actor_kind, action, reason_text, created_at) VALUES (:c, :a, 'staff', 'x', 'because', now())"
    assert run(runtime, u["coa"], ins, c=cid, a=u["coa"]) == 1
    denied(runtime, u["coa"], ins, c=cid, a=u["own"])                      # no forging someone else's action
    outsider = users(admin, "out")["out"]
    denied(runtime, outsider, ins, c=cid, a=outsider)                      # nor writing into a club you're not in
    assert run(runtime, u["ath"], ins, c=cid, a=u["ath"]) == 1                # an athlete's own act (leaving) is recorded...
    assert run(runtime, u["ath"], "SELECT count(*) FROM club_audit") == [(1,)]  # ...and they can read just that, not the staff's entries
    denied(runtime, u["own"], "UPDATE club_audit SET reason_text = 'edited'")
    denied(runtime, u["own"], "DELETE FROM club_audit")
    with runtime.connect() as conn:                                        # the bare runtime role, as account deletion uses it
        with pytest.raises(DBAPIError):
            conn.execute(text("DELETE FROM catch.club_audit"))
    with runtime.begin() as conn:
        conn.execute(text("UPDATE catch.club_audit SET actor_id = NULL WHERE actor_id = :a"), {"a": u["coa"]})   # detaching a deleted person is allowed
    with runtime.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("UPDATE catch.club_audit SET reason_text = 'rewritten'"))


def test_reports_are_visible_to_the_reporter_and_never_to_the_club_staff(env):
    admin, runtime = env
    cid, u = team(admin, visibility="public", policy="open")
    outsider = users(admin, "out")["out"]
    rep = "INSERT INTO club_reports (club_id, target_type, target_id, reporter_id, reason, status, created_at) VALUES (:c, 'club', :c, :r, 'spam', 'open', now())"
    assert run(runtime, outsider, rep, c=cid, r=outsider) == 1
    denied(runtime, u["ath"], rep, c=cid, r=u["own"])                      # can't report as someone else
    assert run(runtime, outsider, "SELECT count(*) FROM club_reports") == [(1,)]
    for who in ("own", "adm", "coa", "ath"):
        assert run(runtime, u[who], "SELECT count(*) FROM club_reports") == [(0,)]
    private, _ = team(admin)
    denied(runtime, outsider, "INSERT INTO club_reports (club_id, target_type, target_id, reporter_id, reason, status, created_at) VALUES (:c, 'club', :c, :r, 'spam', 'open', now())", c=private, r=outsider)


def test_club_results_and_logos_follow_membership_and_visibility(env):
    admin, runtime = env
    pub, up = team(admin, visibility="public", policy="open")
    priv, uq = team(admin)
    outsider = users(admin, "out")["out"]
    with admin.begin() as conn:
        for cid in (pub, priv):
            conn.execute(text("INSERT INTO catch.club_logos (club_id, content_type, data, updated_at) VALUES (:c, 'image/jpeg', :d, now())"), {"c": cid, "d": b"\xff\xd8jpeg"})
    assert {r[0] for r in run(runtime, outsider, "SELECT club_id FROM club_logos")} == {pub}
    assert run(runtime, up["adm"], "UPDATE club_logos SET content_type = 'image/png' WHERE club_id = :c", c=pub) == 1
    assert run(runtime, up["coa"], "UPDATE club_logos SET content_type = 'image/png' WHERE club_id = :c", c=pub) == 0
    denied(runtime, up["adm"], "INSERT INTO club_logos (club_id, content_type, data, updated_at) VALUES ('c-new','image/png', :d, now())", d=b"x" * 300000)
    res = "INSERT INTO club_results (club_id, owner_id, board_key, value, verification, source_key, status, created_at) VALUES (:c, :u, '2000m', 4000, 'verified', :k, 'active', now())"
    assert run(runtime, uq["ath"], res, c=priv, u=uq["ath"], k="s1") == 1
    denied(runtime, uq["bth"], res, c=priv, u=uq["ath"], k="s2")           # can't share someone else's result
    denied(runtime, outsider, res, c=priv, u=outsider, k="s3")
    assert run(runtime, uq["bth"], "SELECT count(*) FROM club_results") == [(1,)]
    assert run(runtime, outsider, "SELECT count(*) FROM club_results") == [(0,)]
    assert run(runtime, uq["coa"], "UPDATE club_results SET status = 'hidden'") == 1                 # staff can hide a shared result
    assert run(runtime, uq["bth"], "SELECT count(*) FROM club_results") == [(0,)]


def test_an_invite_preview_shows_only_what_a_holder_needs_and_nothing_for_a_dead_link(env):
    admin, runtime = env
    cid, u = team(admin, policy="invite")
    _, token = _invite(admin, cid, u["own"])
    _, dead = _invite(admin, cid, u["own"], revoked=True)
    out = users(admin, "out")["out"]
    row = run(runtime, out, "SELECT club_id, name, audience, role FROM catch_club.invite_preview(:t)", t=token)
    assert row == [(cid, cid, "adult", "athlete")]
    assert run(runtime, out, "SELECT count(*) FROM catch_club.invite_preview(:t)", t=dead) == [(0,)]
    assert run(runtime, out, "SELECT count(*) FROM club_invites") == [(0,)]         # the invites table itself stays staff-only


def test_blocks_are_private_to_their_owner(env):
    admin, runtime = env
    ids = users(admin, "a", "b")
    a, b = ids["a"], ids["b"]
    assert run(runtime, a, "INSERT INTO club_blocks (owner_id, blocked_owner_id, created_at) VALUES (:a, :b, now())", a=a, b=b) == 1
    assert run(runtime, a, "SELECT count(*) FROM club_blocks") == [(1,)]
    assert run(runtime, b, "SELECT count(*) FROM club_blocks") == [(0,)]
    denied(runtime, b, "INSERT INTO club_blocks (owner_id, blocked_owner_id, created_at) VALUES (:a, :b, now())", a=a, b=b)


# ---------------------------------------------------------------- the Python matrix and the SQL predicates say the same thing

@pytest.mark.parametrize("audience", ["adult", "junior"])
def test_the_python_permission_matrix_equals_the_sql_predicates_for_every_combination(env, audience):
    import itertools

    from catch.analytics import clubs as c

    admin, _ = env
    cid, u = team(admin, audience=audience)
    outsider = users(admin, "out")["out"]
    actors = {"owner": u["own"], "admin": u["adm"], "coach": u["coa"], "athlete": u["ath"], None: outsider}
    roster = {"owner": u["own"], "admin": u["adm"], "coach": u["coa"], "athlete": u["ath"]}
    with admin.connect() as conn:
        def sql(expr, **p):
            return conn.execute(text(f"SELECT {expr}"), {"c": cid, **p}).scalar()

        for (arole, auid), new_role in itertools.product(actors.items(), c.ROLES):
            assert sql("catch_club.can_assign_role(:c, :a, :r)", a=auid, r=new_role) is c.can_assign_role(arole, new_role), (arole, new_role)
        for (arole, auid), (trole, tuid) in itertools.product(actors.items(), roster.items()):
            assert sql("catch_club.can_manage_member(:c, :a, :t, :r)", a=auid, t=tuid, r=trole) is c.can_manage_member(arole, trole, same_person=auid == tuid), (arole, trole)
        for (arole, auid), req in itertools.product(actors.items(), c.INVITE_ROLES):
            assert sql("catch_club.may_decide_request(:c, :a, :r)", a=auid, r=req) is c.may_decide_request(arole, audience, req), (arole, req)
        for arole, auid in actors.items():
            assert sql("catch_club.may_publish(:c, :a)", a=auid) is c.may_publish(arole, audience), arole
            assert sql("catch_club.is_staff(:c, :a)", a=auid) is (arole in c.STAFF_ROLES), arole
            assert sql("catch_club.is_admin(:c, :a)", a=auid) is (arole in c.ADMIN_ROLES), arole


# ---------------------------------------------------------------- grants and the migration itself

def test_the_grants_are_what_the_design_says(admin):
    from tests.tenancy.test_structure import CLUB_SCOPED

    with admin.connect() as conn:
        priv = lambda role, t, p: conn.execute(text("SELECT has_table_privilege(:r, :t, :p)"), {"r": role, "t": f"catch.{t}", "p": p}).scalar()  # noqa: E731
        fn = lambda role, f: conn.execute(text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"), {"r": role, "f": f}).scalar()  # noqa: E731
        for t in CLUB_SCOPED:
            assert priv("authenticated", t, "SELECT"), t
            assert not priv("anon", t, "SELECT") and not priv("service_role", t, "SELECT"), t
            assert priv("catch_api", t, "SELECT"), t
        assert not priv("authenticated", "club_audit", "UPDATE") and not priv("authenticated", "club_audit", "DELETE")
        assert not priv("catch_api", "club_audit", "DELETE")
        assert not priv("authenticated", "club_invites", "DELETE") and not priv("authenticated", "club_reports", "UPDATE")
        for f in ("catch_club.is_member(text, text)", "catch_club.invite_preview(text)", "catch_club.transfer_ownership(text, text)"):
            assert fn("authenticated", f) and fn("catch_api", f), f
            assert not fn("anon", f), f
        assert not conn.execute(text("SELECT has_schema_privilege('authenticated', 'catch_private', 'USAGE')")).scalar()  # 0002's boundary is untouched
        assert not conn.execute(text("SELECT has_schema_privilege('anon', 'catch_club', 'USAGE')")).scalar()


def test_the_old_leaderboard_clubs_are_carried_over_without_losing_or_misplacing_anyone(admin):
    """Upgrade a database that holds session 26 club rows. Runs last in the file: it rolls the schema back to 0005 and forward again."""
    assert run_alembic("downgrade", "0005").returncode == 0
    ids = [str(uuid.uuid4()) for _ in range(6)]
    c1, c2, c3 = (f"lc{i}-{uuid.uuid4().hex[:6]}" for i in (1, 2, 3))
    with admin.begin() as conn:
        for i, uid in enumerate(ids):
            conn.execute(text("INSERT INTO catch.user_profiles (id, created_at) VALUES (:i, now())"), {"i": uid})
            conn.execute(text("INSERT INTO catch.public_athletes (public_id, owner_id, handle, handle_ci, display_mode, age_group, age_provenance, active, created_at) "
                              "VALUES (:p, :o, :h, :h, 'handle', :g, 'self_declared', true, now())"),
                         {"p": f"p{i}-{uid}", "o": uid, "h": f"h{i}-{uid}", "g": "U17" if i == 2 else None})
        for cid, creator in ((c1, ids[0]), (c2, ids[3]), (c3, ids[2])):
            conn.execute(text("INSERT INTO catch.clubs (club_id, name, name_ci, code_hash, created_by, created_at) VALUES (:c, :c, :c, :h, :u, now())"), {"c": cid, "h": f"hash-{cid}", "u": creator})
        joined = lambda days: f"now() - interval '{days} days'"  # noqa: E731
        for cid, member, days in ((c1, 0, 9), (c1, 1, 8), (c1, 2, 7),      # c1: creator, an adult, a U17
                                  (c2, 1, 20), (c2, 4, 5),                  # c2: the creator is gone; the earliest member should inherit it
                                  (c3, 2, 3)):                               # c3: only a U17 — nobody to carry over
            conn.execute(text(f"INSERT INTO catch.club_members (club_id, public_id, joined_at) VALUES (:c, :p, {joined(days)})"), {"c": cid, "p": f"p{member}-{ids[member]}"})
    up = run_alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr[-1500:]
    with admin.begin() as conn:
        conn.execute(text(f"ALTER ROLE catch_api PASSWORD '{RUNTIME_PASSWORD}'"))
    with admin.connect() as conn:
        roles = {(c, o): r for c, o, r in conn.execute(text("SELECT club_id, owner_id, role FROM catch.club_members WHERE club_id IN (:a, :b, :c)"), {"a": c1, "b": c2, "c": c3})}
        assert roles == {(c1, ids[0]): "owner", (c1, ids[1]): "athlete", (c2, ids[1]): "owner", (c2, ids[4]): "athlete"}
        assert conn.execute(text("SELECT count(*) FROM catch.clubs WHERE club_id = :c"), {"c": c3}).scalar() == 0, "a club with no one to carry over is dropped"
        meta = conn.execute(text("SELECT visibility, audience, join_policy, status FROM catch.clubs WHERE club_id = :c"), {"c": c1}).one()
        assert meta == ("private", "adult", "invite", "active")
        invite = conn.execute(text("SELECT role, token_hash, expires_at > now() AND expires_at < now() + interval '31 days', revoked_at IS NULL FROM catch.club_invites WHERE club_id = :c"), {"c": c1}).one()
        assert invite == ("athlete", f"hash-{c1}", True, True)
        dropped = conn.execute(text("SELECT subject_owner_id, action FROM catch.club_audit WHERE club_id IN (:a, :c)"), {"a": c1, "c": c3}).all()
        assert sorted(dropped) == sorted([(ids[2], "migration_member_not_carried"), (ids[2], "migration_member_not_carried")])
        assert conn.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='catch' AND table_name='clubs' AND column_name='code_hash'")).scalar() == 0
    with admin.begin() as conn:
        for t in ("club_audit", "clubs"):
            conn.execute(text(f"DELETE FROM catch.{t}"))
        conn.execute(text("DELETE FROM catch.public_athletes WHERE owner_id = ANY(:ids)"), {"ids": ids})
        conn.execute(text("DELETE FROM catch.user_profiles WHERE id = ANY(:ids)"), {"ids": ids})
