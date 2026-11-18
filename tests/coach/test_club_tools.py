"""Session 27: the five read-only club tools — registry shape, athlete-only access, personal-install behaviour, labels, MCP parity.
Behaviour under a real public deployment (what a member can and can't read through them) is tests/tenancy/test_clubs_tools.py."""

from __future__ import annotations

import asyncio

import pytest

from catch.coach import tools
from catch.core import principal as pr

CLUB_TOOLS = {"get_my_clubs", "get_club", "get_club_calendar", "get_club_challenges", "get_club_leaderboard"}
ATHLETE = pr.ATHLETE
COACH = pr.Principal(role=pr.COACH_ROLE, id=1, name="Coach")
VIEWER = pr.VIEWER


def test_the_five_tools_are_registered_read_only_with_closed_schemas():
    assert CLUB_TOOLS <= set(tools.TOOLS) and len(tools.TOOLS) == 66
    for name in CLUB_TOOLS:
        spec = tools.TOOLS[name]
        assert spec["write"] is False and spec["input_schema"]["additionalProperties"] is False
        assert "confirm" not in spec["input_schema"]["properties"]
        # no argument can name another person: a tool acts as the signed-in athlete and nobody else
        assert not {"owner_id", "user_id", "member", "member_ref", "athlete_id", "owner"} & set(spec["input_schema"]["properties"]), name


def test_there_is_no_club_write_tool_by_design():
    club_named = {n for n in tools.TOOLS if "club" in n}
    assert club_named == CLUB_TOOLS
    assert not [n for n in tools.TOOLS if any(w in n for w in ("create_club", "join_club", "invite", "approve", "remove_member", "moderate", "post_announcement", "create_challenge"))]


@pytest.mark.parametrize("name", sorted(CLUB_TOOLS))
def test_a_coach_token_or_viewer_is_refused(session, name):
    for who in (COACH, VIEWER):
        with pytest.raises(ValueError):
            tools.call_tool(session, name, {"club_id": "x"}, {"principal": who})


@pytest.mark.parametrize("name", sorted(CLUB_TOOLS))
def test_on_a_personal_install_they_report_unavailable_instead_of_failing(session, name):
    assert tools.call_tool(session, name, {"club_id": "x"}, {"principal": ATHLETE})["available"] is False


def test_a_coach_role_device_token_still_reaches_only_its_five_tools():
    assert not CLUB_TOOLS & set(pr.COACH_TOOLS)


def test_chip_labels_exist_for_every_tool():
    from catch.coach.chat import _tool_label

    for name in CLUB_TOOLS:
        assert _tool_label(name, {}) != name


def test_the_mcp_server_exposes_the_same_tools_and_says_what_it_does_not_do():
    from catch.mcp_server.server import build_server

    class Backend:
        async def call_tool(self, name, args):
            return {}

    server = build_server(Backend())
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert CLUB_TOOLS <= names and names == set(tools.TOOLS)
    assert "no club write tool exists" in server.instructions


def test_the_system_prompt_names_every_club_tool_and_the_safeguards():
    from pathlib import Path

    text = (Path(tools.__file__).parent / "system_prompt.md").read_text()
    for name in CLUB_TOOLS:
        assert f"`{name}`" in text
    assert "junior club" in text and "excuse a week" in text
