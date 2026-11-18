# ruff: noqa: F811  (the `env` fixture is imported from the API suite and used by name)
"""Session 27: what the club tools let an assistant read on a real public deployment. A tool acts as the signed-in athlete and nobody else, so it
reaches exactly what that person could reach in the app: their own clubs, never another club's, never a private or junior club they aren't in, and
never a member's training or health data."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlmodel import Session

from catch.coach import tools
from catch.core import principal as pr
from catch.core import tenant
from tests.tenancy.test_clubs_api import (  # noqa: F401  (fixtures and helpers shared with the API suite)
    ALICE, BOB, CAROL, DAVE, ERIN, FRANK, activity, adult_club, admit_youth, call, challenge, env, invite, join, junior_club, make, profile,
)


def run(env, owner, name, args=None):
    with tenant.use_owner(owner), Session(env.engine) as s:
        return tools.call_tool(s, name, args or {}, {"principal": pr.athlete_for(owner)})


def test_a_member_reads_their_own_club_through_the_tools(env):
    cid = adult_club(env)
    call(env, CAROL, "POST", f"/{cid}/announcements", 200, json={"title": "Practice", "body": "Tuesday 6am"})
    call(env, CAROL, "POST", f"/{cid}/sessions", 200, json={"title": "Steady 60", "session_type": "erg", "date": date.today().isoformat()})
    mine = run(env, DAVE, "get_my_clubs")
    assert mine["available"] is True and [c["name"] for c in mine["clubs"]] == ["River Rowing Club"] and mine["clubs"][0]["my_role"] == "athlete"
    club = run(env, DAVE, "get_club", {"club_id": cid})
    assert {m["handle"]: m["role"] for m in club["members"]}["Carol Coach"] == "coach" and club["announcements"][0]["title"] == "Practice"
    assert run(env, DAVE, "get_club_calendar", {"club_id": cid})["sessions"][0]["title"] == "Steady 60"
    ch = challenge(env, CAROL, cid, goal=60000)
    activity(env, DAVE, "garmin", "t1", 0, distance=10000)
    call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 200)
    listed = run(env, DAVE, "get_club_challenges", {"club_id": cid})["challenges"]
    assert listed[0]["title"] == "Metres Cup" and listed[0]["joined"] is True
    detail = run(env, DAVE, "get_club_challenges", {"club_id": cid, "challenge_id": ch})
    assert detail["standings"][0]["name"] == "Dave Athlete" and any("Equal scores share a rank" in r for r in detail["challenge"]["rules"])
    board = run(env, DAVE, "get_club_leaderboard", {"club_id": cid, "board": "2000m"})
    assert board["ranked"] == [] and "verified" in board["note"].lower()


def test_a_tool_cannot_reach_a_club_the_person_is_not_in(env):
    junior = junior_club(env)                       # Alice (owner), Carol (coach), Dave and Erin (young, not yet admitted)
    other = make(env, ALICE, "Club Two")
    profile(env, BOB, "Bob Stranger")
    for name in ("get_club", "get_club_calendar", "get_club_challenges", "get_club_leaderboard"):
        for club_id in (other, junior):
            for who in (BOB, DAVE):
                with pytest.raises(ValueError, match="Not found"):
                    run(env, who, name, {"club_id": club_id})
    assert run(env, BOB, "get_my_clubs")["clubs"] == [] and [c["name"] for c in run(env, ALICE, "get_my_clubs")["clubs"]] == ["Club Two", "Junior Squad"]


def test_a_public_club_can_be_read_without_its_insides(env):
    profile(env, ALICE, "Alice Owner")
    pub = make(env, ALICE, "Open Water Club", visibility="public", join_policy="open", description="Row at dawn.")
    out = run(env, BOB, "get_club", {"club_id": pub})
    assert out["club"]["name"] == "Open Water Club" and out["club"]["my_role"] is None and "members" not in out and "announcements" not in out
    with pytest.raises(ValueError):
        run(env, BOB, "get_club_calendar", {"club_id": pub})


def test_a_young_members_club_tools_show_handles_not_who_they_are(env):
    cid = junior_club(env)
    admit_youth(env, cid, DAVE)
    out = run(env, DAVE, "get_club", {"club_id": cid})
    assert {m["handle"] for m in out["members"]} == {"Alice Owner", "Coach Carol", "Dave Junior"}
    blob = json.dumps(out)
    for uid in (ALICE, CAROL, DAVE):
        assert uid not in blob
    assert "guardian" not in blob.lower() and "age" not in {k for m in out["members"] for k in m}   # a member's age class and consent are staff-only and not in tool output
    with pytest.raises(ValueError, match="role can't use"):
        tools.call_tool(Session(env.engine), "get_club", {"club_id": cid}, {"principal": pr.Principal(role=pr.COACH_ROLE, id=1, name="Coach")})


def test_no_private_value_reaches_a_club_tool(env):
    from datetime import datetime, timezone

    from catch.core.models import BodyComp, DailyWellness

    cid = adult_club(env)
    with tenant.use_owner(DAVE), Session(env.engine) as s:
        s.add(DailyWellness(date=date.today(), source="garmin", resting_hr=41, hrv_rmssd=87.654, sleep_seconds=27123))
        s.add(BodyComp(source="withings", external_id="bc", ts=datetime.now(timezone.utc), weight_kg=71.234, fat_pct=18.765))
        s.commit()
    ch = challenge(env, CAROL, cid, goal=60000)
    activity(env, DAVE, "garmin", "x", 0, distance=10000)
    call(env, DAVE, "POST", f"/{cid}/challenges/{ch}/join", 200)
    sid = call(env, CAROL, "POST", f"/{cid}/sessions", 200, json={"title": "Steady 60", "session_type": "erg", "date": date.today().isoformat()}).json()["id"]
    call(env, DAVE, "POST", f"/{cid}/sessions/{sid}/participation", 200, json={"canonical_id": activity(env, DAVE, "garmin", "y", 0)[1], "share_numbers": True})
    seen = [run(env, who, name, {"club_id": cid, **({"include_summary": True} if name == "get_club_calendar" else {})})
            for who in (ALICE, CAROL, BOB) for name in ("get_club", "get_club_calendar", "get_club_challenges", "get_club_leaderboard")]
    blob = json.dumps(seen).lower()
    for value in ("87.654", "71.234", "27123", "18.765"):
        assert value not in blob
    assert DAVE not in blob and not (timedelta(0) and blob == "")
