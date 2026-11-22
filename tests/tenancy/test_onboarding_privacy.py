"""Session 34: the privacy step of first-run setup on the public deployment. Completing or skipping setup consents to nothing and publishes
nothing, and that is enforced by the server — AI tool calls are refused, results can't be published, no public athlete exists — not by
what the page shows. Choices made during setup are the same rows Settings → Privacy reads, so they survive resuming and restarting.
Runs with the REAL AI-sharing rules (the suite default allows everything)."""

# ruff: noqa: F811 — the tests take `env`, the leaderboard API tests' fixture imported below, as a parameter (pytest's way of sharing it)
from __future__ import annotations

import pytest
from sqlmodel import Session, select

from catch.coach import tools
from catch.core import tenant
from catch.core.models import AiSharingSettings, LeaderboardSettings, PublicAthlete
from catch.core.principal import ATHLETE
from tests.tenancy.conftest import bearer
from tests.tenancy.test_leaderboards_api import ALICE, BOB, env, preview, seed  # noqa: F401 — `env` is a fixture

pytestmark = pytest.mark.real_ai_sharing


def _finish_setup(env, who, *, via_skip: bool):
    h = bearer(who)
    assert env.c.get("/api/onboarding", headers=h).json()["show"] is True  # a brand-new public account
    if via_skip:
        out = env.c.put("/api/onboarding", headers=h, json={"complete": True})
    else:
        for step in range(1, 6):  # walk every step, privacy (3) included, touching nothing
            assert env.c.put("/api/onboarding", headers=h, json={"step": step}).status_code == 200
        out = env.c.put("/api/onboarding", headers=h, json={"complete": True})
    assert out.json()["state"] == "completed"


@pytest.mark.parametrize("via_skip", [True, False])
def test_finishing_or_skipping_setup_switches_nothing_on(env, via_skip):
    _finish_setup(env, ALICE, via_skip=via_skip)
    h = bearer(ALICE)
    sharing = env.c.get("/api/ai/sharing", headers=h).json()
    assert sharing["consented"] is False and not any(c["enabled"] for c in sharing["categories"])
    assert env.c.get("/api/leaderboards/me", headers=h).json()["settings"]["opted_in"] is False

    # Enforced, not just displayed: the AI coach is refused, nothing can be published, nobody public exists.
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        refused = tools.call_tool(s, "list_workouts", {}, ctx={"principal": ATHLETE, "via": "ai_coach"})
        assert refused["unavailable"] is True and refused["reason"] == "sharing_disabled"
    act = seed(env, ALICE, 1)
    assert preview(env, ALICE, act).status_code == 403
    with Session(env.engine) as s:
        assert s.exec(select(PublicAthlete).execution_options(tenant_unscoped=True)).all() == []


def test_choices_made_in_setup_are_the_settings_rows_and_survive_resume_and_restart(env):
    h = bearer(BOB)
    env.c.put("/api/onboarding", headers=h, json={"step": 3})  # on the privacy step
    assert env.c.put("/api/ai/sharing", headers=h, json={"acknowledge": True, "categories": {"workouts": True}}).status_code == 200
    resumed = env.c.get("/api/onboarding", headers=h).json()
    assert resumed["step"] == 3 and resumed["steps"][3] == "privacy"
    enabled = {c["key"] for c in env.c.get("/api/ai/sharing", headers=h).json()["categories"] if c["enabled"]}
    assert enabled == {"workouts"}  # one switch, not a blanket consent
    env.c.put("/api/onboarding", headers=h, json={"restart": True})
    env.c.put("/api/onboarding", headers=h, json={"complete": True})
    assert {c["key"] for c in env.c.get("/api/ai/sharing", headers=h).json()["categories"] if c["enabled"]} == {"workouts"}
    with tenant.use_owner(BOB), Session(env.engine) as s:
        assert s.exec(select(AiSharingSettings)).one().consented_at is not None
        assert tools.call_tool(s, "list_workouts", {}, ctx={"principal": ATHLETE, "via": "ai_coach"}).get("unavailable") is not True
        assert tools.call_tool(s, "get_wellness", {}, ctx={"principal": ATHLETE, "via": "ai_coach"})["unavailable"] is True
    # Another account is untouched by Bob's choices.
    assert env.c.get("/api/ai/sharing", headers=bearer(ALICE)).json()["consented"] is False


def test_joining_leaderboards_in_setup_still_publishes_nothing(env):
    h = bearer(ALICE)
    joined = env.c.post("/api/leaderboards/me/opt-in", headers=h, json={"confirm": True, "display_mode": "anonymous", "attest_min_age": True})
    assert joined.status_code == 200 and joined.json()["settings"]["opted_in"] is True
    env.c.put("/api/onboarding", headers=h, json={"complete": True})
    assert env.c.get("/api/leaderboards/me/results", headers=h).status_code == 200
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        assert s.exec(select(LeaderboardSettings)).one().opted_in is True
    board = env.c.get("/api/leaderboards/boards/2000m", params={"verification": "include_unverified"}, headers=bearer(BOB)).json()
    assert board["entries"] == [] and board["unverified"] == [] and board["total"] == 0


def test_an_account_saved_at_the_old_sync_step_resumes_on_privacy(env):
    h = bearer(ALICE)
    env.c.put("/api/onboarding", headers=h, json={"step": 3})  # session 32's index 3 was "sync"
    state = env.c.get("/api/onboarding", headers=h).json()
    assert state["steps"] == ["welcome", "connections", "preferences", "privacy", "sync", "done"] and state["steps"][state["step"]] == "privacy"
