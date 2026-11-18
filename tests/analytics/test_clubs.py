"""catch/analytics/clubs.py — the permission matrix, junior invariants, validators, invites and aggregate suppression."""

from __future__ import annotations

import itertools

import pytest

from catch.analytics import clubs as c

ROLES = c.ROLES


# ---------------------------------------------------------------- age

@pytest.mark.parametrize("band,cls,guardian", [
    ("adult", "adult", False), ("U19", "youth", False), ("U18", "youth", False), ("U17", "youth", False),
    ("U16", "youth", True), ("U15", "youth", True), ("U14", "youth", True),
])
def test_age_bands_map_to_a_class_and_guardian_consent_below_16(band, cls, guardian):
    assert c.age_class_for_band(band) == cls
    assert c.guardian_required(band) is guardian


def test_an_unknown_band_is_refused():
    with pytest.raises(ValueError):
        c.age_class_for_band("U12")  # below the minimum age the leaderboards also refuse
    with pytest.raises(ValueError):
        c.age_class_for_band("40-49")  # leaderboard adult bands aren't club bands: a club only needs adult vs youth


# ---------------------------------------------------------------- the matrix

@pytest.mark.parametrize("actor,new_role,expected", [
    ("owner", "admin", True), ("owner", "coach", True), ("owner", "athlete", True), ("owner", "owner", False),
    ("admin", "coach", True), ("admin", "athlete", True), ("admin", "admin", False), ("admin", "owner", False),
    ("coach", "athlete", True), ("coach", "coach", False), ("coach", "admin", False),
    ("athlete", "athlete", False), ("athlete", "coach", False), (None, "athlete", False),
])
def test_who_can_assign_which_role(actor, new_role, expected):
    assert c.can_assign_role(actor, new_role) is expected


@pytest.mark.parametrize("actor,target,expected", [
    ("owner", "admin", True), ("owner", "coach", True), ("owner", "athlete", True), ("owner", "owner", False),
    ("admin", "coach", True), ("admin", "athlete", True), ("admin", "admin", False), ("admin", "owner", False),
    ("coach", "athlete", True), ("coach", "coach", False), ("coach", "admin", False), ("coach", "owner", False),
    ("athlete", "athlete", False), (None, "athlete", False),
])
def test_who_can_change_or_remove_whom(actor, target, expected):
    assert c.can_manage_member(actor, target) is expected


def test_nobody_manages_themselves():
    for role in ROLES:
        assert c.can_manage_member(role, "athlete", same_person=True) is False


@pytest.mark.parametrize("actor,audience,req_role,expected", [
    # adult clubs: any staff admits an athlete; only owner/admin vets a coach
    ("owner", "adult", "athlete", True), ("admin", "adult", "athlete", True), ("coach", "adult", "athlete", True), ("athlete", "adult", "athlete", False),
    ("owner", "adult", "coach", True), ("admin", "adult", "coach", True), ("coach", "adult", "coach", False),
    # junior clubs: ONLY a coach admits a young athlete; owner and admin cannot
    ("coach", "junior", "athlete", True), ("owner", "junior", "athlete", False), ("admin", "junior", "athlete", False), ("athlete", "junior", "athlete", False),
    ("owner", "junior", "coach", True), ("admin", "junior", "coach", True), ("coach", "junior", "coach", False),
])
def test_who_decides_a_join_request(actor, audience, req_role, expected):
    assert c.may_decide_request(actor, audience, req_role) is expected


@pytest.mark.parametrize("actor,audience,publishes", [
    ("owner", "adult", True), ("admin", "adult", True), ("coach", "adult", True), ("athlete", "adult", False),
    ("owner", "junior", False), ("admin", "junior", False), ("coach", "junior", True), ("athlete", "junior", False),
])
def test_who_publishes_directly_and_whose_post_waits(actor, audience, publishes):
    assert c.may_publish(actor, audience) is publishes
    assert c.post_status_for(actor, audience) == ("published" if publishes else "pending")


def test_invites_for_coaches_are_an_owner_or_admin_decision():
    assert [r for r in ROLES if c.may_create_invite(r, "athlete")] == ["owner", "admin", "coach"]
    assert [r for r in ROLES if c.may_create_invite(r, "coach")] == ["owner", "admin"]


def test_capabilities_give_an_athlete_nothing_administrative_and_the_owner_everything_reasonable():
    athlete = c.capabilities("athlete", "adult")
    admin_only = ("edit_club", "set_roles", "remove_member", "see_requests", "see_audit", "post", "take_down_post", "delete_club", "transfer_ownership",
                  "publish_directly", "decide_athlete_requests", "create_athlete_invite")
    assert not any(athlete[k] for k in admin_only)
    assert athlete["view"] and athlete["report"] and athlete["block"] and athlete["join_challenge"] and athlete["leave"]
    owner = c.capabilities("owner", "adult")
    assert owner["delete_club"] and owner["transfer_ownership"] and not owner["leave"]  # the owner transfers first
    assert not c.capabilities("owner", "junior")["publish_directly"] and c.capabilities("coach", "junior")["publish_directly"]
    assert not c.capabilities("owner", "junior")["decide_athlete_requests"] and c.capabilities("coach", "junior")["decide_athlete_requests"]
    assert not any(c.capabilities(None, "adult").values())  # a non-member can do nothing


def test_every_action_names_only_real_roles():
    for action, roles in c.ACTIONS.items():
        assert set(roles) <= set(ROLES), action


# ---------------------------------------------------------------- who may be in which club

@pytest.mark.parametrize("age,role,audience,ok", [
    ("adult", "athlete", "adult", True), ("adult", "coach", "adult", True), ("adult", "owner", "adult", True),
    ("youth", "athlete", "adult", False), ("youth", "coach", "adult", False),
    ("youth", "athlete", "junior", True), ("adult", "athlete", "junior", False),
    ("adult", "coach", "junior", True), ("adult", "owner", "junior", True), ("adult", "admin", "junior", True),
    ("youth", "coach", "junior", False), ("youth", "owner", "junior", False), ("youth", "admin", "junior", False),
])
def test_the_age_rules_for_every_role_and_audience(age, role, audience, ok):
    assert (c.may_hold_role(age, role, audience) is None) is ok
    # ...and the schema's CHECK says the same thing: youth <=> athlete in a junior club
    assert (age == c.membership_age_class(role, audience)) is ok


def test_the_reason_a_member_can_t_join_is_actionable():
    assert "junior club" in c.may_hold_role("youth", "athlete", "adult")
    assert "adults" in c.may_hold_role("adult", "athlete", "junior")


# ---------------------------------------------------------------- club fields

def fields(**kw):
    base = dict(name="River Rowing Club", visibility="private", audience="adult", join_policy="request")
    return c.validate_club_fields(**{**base, **kw})


def test_a_valid_club_is_normalised():
    f = fields(name="  River   Rowing  Club ", description=" Row  at dawn.\n\n\n\nAll levels.", location=" Boston,  MA ")
    assert (f.name, f.location) == ("River Rowing Club", "Boston, MA") and f.description == "Row at dawn.\n\nAll levels."


@pytest.mark.parametrize("kw,message", [
    ({"name": "ab"}, "3-40"), ({"name": "x" * 41}, "3-40"), ({"name": "Visit www.example.com"}, "web address"), ({"name": "club.com rowing"}, "web address"),
    ({"visibility": "secret"}, "public or private"), ({"audience": "kids"}, "adult or junior"), ({"join_policy": "anyone"}, "open, request or invite"),
    ({"visibility": "private", "join_policy": "open"}, "only a public club"),
    ({"description": "x" * 501}, "500"), ({"location": "x" * 81}, "80"), ({"location": "https://x.example"}, "web address"), ({"rules": "x" * 2001}, "2000"),
])
def test_invalid_club_fields_are_refused_with_a_reason(kw, message):
    with pytest.raises(ValueError, match=message):
        fields(**kw)


@pytest.mark.parametrize("kw", [
    {"visibility": "public"}, {"join_policy": "open"}, {"join_policy": "invite"}, {"visibility": "public", "join_policy": "open"},
])
def test_a_junior_club_is_always_private_and_request_only(kw):
    with pytest.raises(ValueError, match="junior club is always private"):
        fields(audience="junior", **kw)
    assert fields(audience="junior").join_policy == "request"


def test_a_junior_clubs_text_may_not_lead_anywhere_off_the_app():
    for key in ("description", "rules", "location"):
        with pytest.raises(ValueError, match="web address"):
            fields(audience="junior", **{key: "see www.example.com"})
    assert fields(audience="adult", rules="Read the guide at www.example.com").rules  # adults are trusted with a link


def test_posts_are_length_checked_and_junior_posts_carry_no_links():
    assert c.validate_post("  Practice   moved ", "Meet at 6.", "adult") == ("Practice moved", "Meet at 6.")
    assert c.validate_post("Results", "See https://example.com/results", "adult")
    with pytest.raises(ValueError, match="web addresses"):
        c.validate_post("Results", "See https://example.com/results", "junior")
    with pytest.raises(ValueError):
        c.validate_post("", "body", "adult")
    with pytest.raises(ValueError):
        c.validate_post("t" * 81, "body", "adult")
    with pytest.raises(ValueError):
        c.validate_post("t", "b" * 2001, "adult")


def test_a_reason_is_required_where_it_is_required():
    assert c.validate_reason("  too  loud ") == "too loud"
    with pytest.raises(ValueError, match="A reason is required."):
        c.validate_reason("   ")
    assert c.validate_reason("", required=False) == ""
    with pytest.raises(ValueError):
        c.validate_reason("x" * 501)


def test_a_join_message_cannot_carry_a_link_or_run_long():
    assert c.validate_message(" Hi,  I row Sundays ") == "Hi, I row Sundays" and c.validate_message(None) is None and c.validate_message("  ") is None
    for bad in ("add me www.example.com", "x" * 301):
        with pytest.raises(ValueError):
            c.validate_message(bad)


# ---------------------------------------------------------------- invites

def test_invite_tokens_are_unguessable_and_hashed_consistently():
    a, b = c.new_invite_token(), c.new_invite_token()
    assert a != b and len(a) >= 30
    assert c.invite_hash(a) == c.invite_hash(f"  {a}  ") and c.invite_hash(a) != c.invite_hash(b)
    assert len(c.invite_hash(a)) == 64 and a not in c.invite_hash(a)


def test_a_legacy_join_code_still_resolves_in_any_case():
    legacy = c.invite_hash("A1B2C3D4")  # session 26 hashed the UPPER-cased code
    assert legacy in c.invite_hash_candidates("a1b2c3d4") and legacy in c.invite_hash_candidates("A1B2C3D4")
    assert len(c.invite_hash_candidates("ALREADYUPPER")) == 1


def test_invite_lifetime_and_use_limits_are_bounded():
    assert c.invite_expiry_days(None) == 7 and c.invite_expiry_days(30) == 30
    for bad in (0, 31, -1):
        with pytest.raises(ValueError):
            c.invite_expiry_days(bad)
    assert c.invite_max_uses(None) is None and c.invite_max_uses(5) == 5
    for bad in (0, 101):
        with pytest.raises(ValueError):
            c.invite_max_uses(bad)


# ---------------------------------------------------------------- aggregates never describe one person

def test_a_total_needs_at_least_three_members_who_chose_to_share():
    assert c.suppress_small(5, [1000, None, None, None, None]) == {"count": 5, "shared": 1, "total": None, "mean": None, "suppressed": True}
    assert c.suppress_small(5, [1000, 2000]) ["suppressed"] is True
    ok = c.suppress_small(5, [1000, 2000, 3000, None, None])
    assert ok["suppressed"] is False and ok["total"] == 6000 and ok["mean"] == 2000 and ok["count"] == 5


def test_a_team_summary_has_counts_and_suppressed_totals_and_no_member_identifiers():
    sessions = [{"id": 1, "title": "Steady 60", "date": "2026-11-02"}, {"id": 2, "title": "Test day", "date": "2026-11-05"}]
    part = [{"session_id": 1, "shared_distance_m": 14000}, {"session_id": 1, "shared_distance_m": 15000}, {"session_id": 1, "shared_distance_m": 16000},
            {"session_id": 2, "shared_distance_m": 7000}, {"session_id": 2}]
    s = c.team_summary(sessions, part, member_count=10)
    assert s["sessions"] == 2 and s["participations"] == 5 and s["attendance_rate"] == 0.25 and s["mean_participants"] == 2.5
    first, second = s["per_session"]
    assert first["participants"] == 3 and first["distance_m"]["total"] == 45000 and first["distance_m"]["suppressed"] is False
    assert second["participants"] == 2 and second["distance_m"]["total"] is None  # one member shared: that number would be theirs alone
    assert s["distance_m"]["total"] == 52000 and s["duration_s"]["total"] is None
    flat = repr(s)
    assert "owner" not in flat and "handle" not in flat  # structurally no identities
    assert "recovery, sleep, weight or nutrition" in s["note"]


def test_an_empty_team_summary_does_not_divide_by_zero():
    s = c.team_summary([], [], member_count=0)
    assert s["sessions"] == 0 and s["mean_participants"] is None and s["attendance_rate"] is None


def test_the_permission_grid_has_no_gaps():
    """Every (actor, other) combination returns a bool, so a future role can't silently fall through a missing branch."""
    for actor, other in itertools.product((*ROLES, None), ROLES):
        assert isinstance(c.can_assign_role(actor, other), bool) and isinstance(c.can_manage_member(actor, other), bool)
        for audience, req in itertools.product(c.AUDIENCES, c.INVITE_ROLES):
            assert isinstance(c.may_decide_request(actor, audience, req), bool)
