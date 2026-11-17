"""Session 26: the three read-only leaderboard tools — public information only, athlete-only, personal installs unaffected."""

from __future__ import annotations

import asyncio

import pytest

from catch.coach import tools
from catch.core.principal import ATHLETE, VIEWER, coach_principal

COACH = coach_principal(7, "Coach Sam")

LB_TOOLS = {"get_leaderboards", "get_public_athlete_profile", "get_verified_results"}


def test_the_leaderboard_tools_are_registered_read_only_with_strict_schemas():
    assert LB_TOOLS <= set(tools.TOOLS)
    for name in LB_TOOLS:
        spec = tools.TOOLS[name]
        assert spec["write"] is False and spec["input_schema"]["additionalProperties"] is False
        assert "confirm" not in spec["input_schema"]["properties"]
    assert not [n for n in tools.TOOLS if "publish" in n or "unpublish" in n]


@pytest.mark.parametrize("name", sorted(LB_TOOLS))
def test_a_coach_or_viewer_principal_is_refused(session, name):
    for who in (COACH, VIEWER):
        with pytest.raises(ValueError):
            tools.call_tool(session, name, {}, {"principal": who})


@pytest.mark.parametrize("name", sorted(LB_TOOLS))
def test_on_a_personal_install_they_report_unavailable_instead_of_failing(session, name):
    assert tools.call_tool(session, name, {}, {"principal": ATHLETE})["available"] is False


def test_chip_labels_exist_for_every_tool():
    from catch.coach.chat import _tool_label

    for name in LB_TOOLS:
        assert _tool_label(name, {}) != name


def test_the_mcp_server_exposes_the_same_tools():
    from catch.mcp_server.server import build_server

    class Backend:
        async def call_tool(self, name, args):
            return {}

    names = {t.name for t in asyncio.run(build_server(Backend()).list_tools())}
    assert LB_TOOLS <= names and names == set(tools.TOOLS)
