"""What is sent to an AI provider is governed by the person's consent and per-category choices, enforced in the service layer
(session 28). These tests run with the REAL rules (the suite-wide default allows everything)."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlmodel import select

from catch.coach import ai_sharing, chat, memory, tools
from catch.coach.vision import VisionError, run_vision, vision_available
from catch.core.models import AthleteFact, CoachConversation, ToolCallLog
from catch.core.principal import ATHLETE

pytestmark = pytest.mark.real_ai_sharing


def _via(name, session, args=None, via="ai_coach"):
    return tools.call_tool(session, name, args or {}, ctx={"principal": ATHLETE, "via": via})


def test_every_tool_is_classified_so_a_new_tool_can_not_slip_past_the_rules():
    assert set(ai_sharing.TOOL_CATEGORY) == set(tools.TOOLS)
    assert {c for c in ai_sharing.TOOL_CATEGORY.values() if c} <= set(ai_sharing.CATEGORIES)


def test_nothing_is_shared_until_the_person_has_agreed(session):
    assert ai_sharing.enabled_categories(session) == set() and not ai_sharing.has_consented(session)
    for name in ("get_today", "list_workouts", "get_nutrition", "recall", "get_calendar"):
        out = _via(name, session)
        assert out["unavailable"] is True and out["reason"] == "sharing_disabled", name
    assert _via("get_connected_providers", session) is not None  # connection status is not personal data


def test_acknowledging_alone_turns_nothing_on_and_each_category_is_its_own_switch(session):
    ai_sharing.update(session, acknowledge=True, categories={})
    assert ai_sharing.has_consented(session) and ai_sharing.enabled_categories(session) == set()
    assert _via("get_nutrition", session)["unavailable"]
    ai_sharing.update(session, acknowledge=False, categories={"nutrition": True})
    assert ai_sharing.enabled_categories(session) == {"nutrition"}
    assert "unavailable" not in _via("get_nutrition", session)
    assert _via("get_today", session)["unavailable"]  # wellness still off
    ai_sharing.update(session, acknowledge=False, categories={"nutrition": False})
    assert _via("get_nutrition", session)["unavailable"]


def test_you_cannot_switch_things_on_without_acknowledging_first(session):
    with pytest.raises(ai_sharing.SharingError):
        ai_sharing.update(session, acknowledge=False, categories={"wellness": True})
    with pytest.raises(ai_sharing.SharingError):
        ai_sharing.update(session, acknowledge=True, categories={"made_up": True})


def test_withdrawing_consent_switches_everything_off_again(session):
    ai_sharing.update(session, acknowledge=True, categories={"wellness": True, "workouts": True})
    assert not _via("get_today", session).get("unavailable")
    ai_sharing.revoke(session)
    assert not ai_sharing.has_consented(session) and ai_sharing.enabled_categories(session) == set()
    assert _via("get_today", session)["unavailable"]


def test_a_young_person_cannot_share_health_data_without_a_guardian_ack(session):
    with pytest.raises(ai_sharing.SharingError, match="parent or guardian"):
        ai_sharing.update(session, acknowledge=True, categories={"wellness": True}, age_band="u16")
    ai_sharing.update(session, acknowledge=True, categories={"calendar_library": True}, age_band="u16")  # not health: fine
    state = ai_sharing.update(session, acknowledge=False, categories={"wellness": True}, guardian_ack=True)
    assert next(c for c in state["categories"] if c["key"] == "wellness")["enabled"] is True and state["guardian_ack"] is True


def test_the_rules_bind_the_mcp_path_too_but_not_a_direct_rest_caller(session):
    assert _via("get_today", session, via="mcp")["unavailable"]
    assert "unavailable" not in _via("get_today", session, via="rest")  # the person's own API client, not a model


def test_writes_obey_the_category_switch_too_and_still_need_confirmation(session):
    # A write's preview echoes stored data (forget/update previews show the current text), so "off" means off for writes as well.
    memory.remember(session, "injury", "SECRET-KNEE-SURGERY-2024")
    assert _via("remember", session, {"category": "other", "text": "x"})["unavailable"] is True
    assert "SECRET-KNEE-SURGERY-2024" not in str(_via("forget", session, {"ref": "fact:1"}, via="mcp"))
    ai_sharing.update(session, acknowledge=True, categories={"memory": True})
    out = _via("remember", session, {"category": "other", "text": "x"})
    assert out["saved"] is False and "preview" in out and len(session.exec(select(AthleteFact)).all()) == 1


def test_a_tool_that_mixes_categories_loses_the_parts_that_are_off(session):
    from datetime import date as _date

    from catch.core.models import CheckIn, Note

    session.add(CheckIn(date=_date.today(), soreness=3, niggle_area="SECRET-LEFT-KNEE"))
    session.add(Note(date=_date.today(), text="SECRET-NOTE"))
    session.commit()
    ai_sharing.update(session, acknowledge=True, categories={"wellness": True})
    today = _via("get_today", session)
    assert "checkin" not in today and "upcoming_events" not in today and "SECRET-LEFT-KNEE" not in str(today)
    ai_sharing.update(session, acknowledge=False, categories={"notes_checkins": True, "calendar_library": True})
    assert "checkin" in _via("get_today", session) and "upcoming_events" in _via("get_today", session)
    ai_sharing.update(session, acknowledge=False, categories={"notes_checkins": False})
    assert _via("get_trends", session, {"metric": "checkin_soreness"})["unavailable"] is True  # a check-in metric is that category's data


def test_earlier_tool_results_stop_being_replayed_once_their_category_is_off(session):
    ai_sharing.update(session, acknowledge=True, categories={"wellness": True, "memory": True})
    history = [
        {"role": "assistant", "blocks": [{"type": "tool_call", "id": "a", "name": "get_today", "input": {}}, {"type": "tool_call", "id": "b", "name": "recall", "input": {}}]},
        {"role": "user", "blocks": [{"type": "tool_result", "id": "a", "output": {"recovery": 80}, "is_error": False}, {"type": "tool_result", "id": "b", "output": {"results": ["SECRET"]}, "is_error": False}]},
    ]
    assert ai_sharing.scrub_history(session, history) == history  # both allowed: untouched
    ai_sharing.update(session, acknowledge=False, categories={"memory": False})
    scrubbed = ai_sharing.scrub_history(session, history)
    results = {b["id"]: b["output"] for b in scrubbed[1]["blocks"]}
    assert results["a"] == {"recovery": 80} and results["b"]["reason"] == "sharing_disabled" and "SECRET" not in str(scrubbed)


def test_a_device_token_caller_cannot_dodge_the_gate_by_omitting_the_client_header():
    from starlette.requests import Request

    from catch.api.routes_coach import _via

    def req(**h):
        return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in h.items()]})

    assert _via(req(Authorization="Bearer abcDEF123_-token-with-no-dots")) == "mcp"
    assert _via(req(Authorization="Bearer a.b.c")) == "rest"  # the web app's own JWT
    assert _via(req()) == "rest"  # the web app's cookie
    assert _via(req(**{"X-Catch-Client": "mcp"})) == "mcp"


def test_the_memory_block_only_holds_what_was_agreed(session):
    memory.remember(session, "injury", "left knee")
    memory.set_goal(session, text="sub 7 2k")
    everything = memory.memory_block(session)
    assert "left knee" in everything and "sub 7 2k" in everything
    nothing = memory.memory_block(session, allowed=set())
    assert "left knee" not in nothing and "sub 7 2k" not in nothing and "not shared with the AI" in nothing
    only_memory = memory.memory_block(session, allowed={"memory"})
    assert "left knee" in only_memory and "Today's check-in" not in only_memory


def test_chat_refuses_until_consent_and_sends_no_provider_request(session, monkeypatch):
    conv = CoachConversation()
    session.add(conv)
    session.commit()
    called = []

    async def resolve(*a, **k):
        called.append(1)
        raise AssertionError("the provider must not be resolved without consent")

    monkeypatch.setattr(chat, "_resolve_provider", resolve)

    async def go():
        return [e async for e in chat.run_turn(session, conv.id, "hello")]

    events = asyncio.run(go())
    assert [e["type"] for e in events] == ["consent_required"] and not called


def test_photo_features_need_the_photos_category(session):
    assert asyncio.run(vision_available(session))["reason"] == "sharing_off"
    ai_sharing.update(session, acknowledge=True, categories={"wellness": True})
    with pytest.raises(VisionError, match="switched off"):
        asyncio.run(run_vision(session, "meal", object()))  # refused before the request is even looked at
    ai_sharing.update(session, acknowledge=False, categories={"photos": True})
    assert asyncio.run(vision_available(session))["reason"] != "sharing_off"


def test_denied_calls_and_mcp_calls_land_in_the_audit_log_without_their_arguments(session):
    _via("get_today", session, via="mcp")  # denied (nothing agreed)
    ai_sharing.update(session, acknowledge=True, categories={"calendar_library": True, "memory": True})
    _via("get_upcoming_events", session, via="mcp")
    _via("remember", session, {"category": "other", "text": "very private words"}, via="mcp")
    rows = session.exec(select(ToolCallLog).order_by(ToolCallLog.id)).all()
    assert [(r.tool, r.via, r.outcome, r.is_write) for r in rows] == [
        ("get_today", "mcp", "denied", False), ("get_upcoming_events", "mcp", "ok", False), ("remember", "mcp", "preview", True),
    ]
    assert all("very private words" not in repr(r.__dict__) for r in rows) and all(len(r.args_hash or "") in (0, 32) for r in rows)


def test_in_app_reads_are_not_logged_but_writes_and_denials_are(session):
    ai_sharing.update(session, acknowledge=True, categories={"workouts": True})
    _via("get_zones", session)  # a successful in-app read: not logged
    _via("tag_activity", session, {"id": 1, "tags": ["x"]})  # a write preview: logged
    assert [r.tool for r in session.exec(select(ToolCallLog)).all()] == ["tag_activity"]
    assert date.today()  # (keeps the import used)
