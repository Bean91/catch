from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from sqlmodel import select

from catch.analytics.planning import week_start
from catch.coach import chat, memory, tools
from catch.core.models import Event, PlannedWorkout
from catch.sync import planning as sp

MON = week_start(sp.today())
D = (MON + timedelta(days=2)).isoformat()

WRITE_CALLS = {
    "create_planned_workout": {"date": D, "session_type": "erg", "duration_min": 60},
    "create_event": {"name": "Nationals", "date": (MON + timedelta(days=60)).isoformat(), "type": "race", "priority": "A"},
}


def _count(session, model):
    return len(session.exec(select(model)).all())


def _seed(session):
    row = sp.create_planned(session, sp.OWNER_ID, {"date": MON + timedelta(days=2), "session_type": "erg", "duration_min": 60})[0]
    ev = sp.create_event(session, sp.OWNER_ID, {"name": "Head", "date": MON + timedelta(days=40), "type": "race"})
    return row, ev


def _all_write_calls(session):
    row, ev = _seed(session)
    return {
        "create_planned_workout": {"date": D, "session_type": "strength"},
        "update_planned_workout": {"id": row.id, "duration_min": 90},
        "delete_planned_workout": {"id": row.id},
        "create_event": {"name": "Nationals", "date": (MON + timedelta(days=60)).isoformat(), "type": "race"},
        "update_event": {"id": ev.id, "goal_time": "6:40"},
        "forget": {"ref": f"event:{ev.id}"},
    }


def test_every_calendar_write_tool_previews_without_confirm_and_changes_nothing(session):
    calls = _all_write_calls(session)
    before = (_count(session, PlannedWorkout), _count(session, Event))
    snapshot = [(p.id, p.title, p.duration_min, p.date) for p in session.exec(select(PlannedWorkout)).all()]
    for name, args in calls.items():
        out = tools.call_tool(session, name, args)
        if name == "forget":
            assert out.get("saved") is False and "preview" in out, name
        else:
            assert out["saved"] is False and out["preview"], name
            assert "confirm=true" in out["message"], name
        # Falsy, string and absent values never count as confirmation.
        for fake in (False, "true", 1, None):
            held = tools.call_tool(session, name, {**args, "confirm": fake})
            assert held.get("saved") is False, (name, fake)
    assert (_count(session, PlannedWorkout), _count(session, Event)) == before
    assert snapshot == [(p.id, p.title, p.duration_min, p.date) for p in session.exec(select(PlannedWorkout)).all()]


def test_registry_every_write_tool_with_confirm_declares_it_optional_boolean():
    gated = {"create_planned_workout", "update_planned_workout", "delete_planned_workout", "create_event", "update_event", "forget"}
    for name in gated:
        schema = tools.TOOLS[name]["input_schema"]
        assert schema["properties"]["confirm"]["type"] == "boolean"
        assert "confirm" not in schema["required"]
        assert tools.TOOLS[name]["write"] is True
    for name in ("get_calendar", "get_upcoming_events", "get_event", "get_training_phase"):
        assert tools.TOOLS[name]["write"] is False
    assert "add_event" not in tools.TOOLS


def test_confirmed_writes_actually_save(session):
    created = tools.call_tool(session, "create_planned_workout", {**WRITE_CALLS["create_planned_workout"], "confirm": True})
    assert created["saved"] is True
    pid = created["planned"][0]["id"]
    held = tools.call_tool(session, "update_planned_workout", {"id": pid, "date": (MON + timedelta(days=4)).isoformat()})
    assert held["preview"]["changes"]["date"]["to"] == (MON + timedelta(days=4)).isoformat()
    moved = tools.call_tool(session, "update_planned_workout", {"id": pid, "date": (MON + timedelta(days=4)).isoformat(), "confirm": True})
    assert moved["planned"][0]["date"] == (MON + timedelta(days=4)).isoformat()
    gone = tools.call_tool(session, "delete_planned_workout", {"id": pid, "confirm": True})
    assert gone == {"saved": True, "deleted": 1}


def test_repeat_preview_lists_every_date_before_anything_is_created(session):
    out = tools.call_tool(session, "create_planned_workout", {"date": D, "session_type": "erg", "repeat": {"weekdays": [2, 4], "count": 4}})
    assert out["preview"]["count"] == 4 and len(out["preview"]["dates"]) == 4
    assert _count(session, PlannedWorkout) == 0
    saved = tools.call_tool(session, "create_planned_workout", {"date": D, "session_type": "erg", "repeat": {"weekdays": [2, 4], "count": 4}, "confirm": True})
    assert len(saved["planned"]) == 4


def test_bad_input_fails_at_preview_not_at_confirm(session):
    for args in (
        {"date": D, "session_type": "swim"},
        {"date": D, "session_type": "erg", "target_zone": "Z9"},
        {"date": D, "session_type": "erg", "structure": [{"reps": 0, "work_min": 5}]},
        {"date": D, "session_type": "erg", "repeat": {"weekdays": [0]}},
    ):
        with pytest.raises(ValueError):
            tools.call_tool(session, "create_planned_workout", args)
    with pytest.raises(ValueError):
        tools.call_tool(session, "create_event", {"name": "x", "date": D, "type": "regatta"})
    with pytest.raises(ValueError):
        tools.call_tool(session, "create_event", {"name": "x", "date": "2027-05-01", "type": "race", "priority": "D"})


def test_forget_event_detaches_references_after_confirm(session):
    row, ev = _seed(session)
    sp.update_planned(session, sp.OWNER_ID, row.id, {"event_id": ev.id})
    preview = tools.call_tool(session, "forget", {"ref": f"event:{ev.id}"})
    assert preview["preview"]["planned_sessions_unlinked_from_event"] == 1
    assert tools.call_tool(session, "forget", {"ref": f"event:{ev.id}", "confirm": True}) == {"deleted": True}
    session.expire_all()
    assert session.get(PlannedWorkout, row.id).event_id is None


def test_forget_for_a_fact_is_unchanged(session):
    fact = tools.call_tool(session, "remember", {"category": "other", "text": "x"})
    assert tools.call_tool(session, "forget", {"ref": fact["ref"]}) == {"deleted": True}


def test_read_tools_return_planned_and_completed_separately(session):
    _seed(session)
    cal = tools.call_tool(session, "get_calendar", {"from": MON.isoformat(), "to": (MON + timedelta(days=6)).isoformat()})
    day = next(d for d in cal["days"] if d["planned"])
    assert day["planned"][0]["display_status"] in ("planned", "not_logged") and day["completed"] == []
    assert "intentions" in cal["note"]
    with pytest.raises(ValueError):
        tools.call_tool(session, "get_calendar", {"from": MON.isoformat()})
    with pytest.raises(ValueError):
        tools.call_tool(session, "get_calendar", {"from": MON.isoformat(), "to": (MON + timedelta(days=300)).isoformat()})


def test_upcoming_event_and_phase_tools(session):
    _, ev = _seed(session)
    up = tools.call_tool(session, "get_upcoming_events", {})["events"]
    assert [e["name"] for e in up] == ["Head"]
    detail = tools.call_tool(session, "get_event", {"id": ev.id})
    assert detail["event"]["name"] == "Head" and "projection" in detail and detail["projection"]["available"] is False
    sp.create_phase(session, sp.OWNER_ID, {"kind": "general_prep", "name": "Base", "start_date": MON, "end_date": MON + timedelta(days=20), "target_minutes_per_week": 300})
    sp.approve_phase(session, sp.OWNER_ID, sp.list_phases(session, sp.OWNER_ID)[0].id, approved_by="Coach")
    out = tools.call_tool(session, "get_training_phase", {})
    assert out["phase"]["name"] == "Base" and out["phase"]["coach_approved"] is True and out["weekly_targets"]["minutes"] == 300
    with pytest.raises(sp.NotFound):
        tools.call_tool(session, "get_event", {"id": 9999})


def test_tool_results_are_json_serialisable(session):
    _seed(session)
    for name, args in (
        ("get_calendar", {"from": MON.isoformat(), "to": (MON + timedelta(days=6)).isoformat()}),
        ("get_upcoming_events", {}),
        ("get_training_phase", {}),
    ):
        json.dumps(tools.call_tool(session, name, args))


def test_chat_labels_distinguish_preview_from_save():
    assert chat._tool_label("create_planned_workout", {}) == "Preview adding a planned session"
    assert chat._tool_label("create_planned_workout", {"confirm": True}) == "Add planned session"
    assert chat._tool_label("update_event", {"id": 3}) == "Preview updating event #3"
    assert chat._tool_label("add_event", {"name": "X"}) == "Add event: X"  # persisted history still renders


def test_system_prompt_no_longer_tells_the_model_to_write_events_unprompted():
    text = (tools.__file__.rsplit("/", 1)[0] + "/system_prompt.md")
    body = open(text).read()
    assert "add_event" not in body
    assert "always\npreview first" in body or "always preview first" in body.replace("\n", " ")


def test_mcp_exposes_exactly_the_registry_and_writes_pass_confirm_through():
    from catch.mcp_server.server import build_server

    calls = []

    class Backend:
        async def call_tool(self, name, args):
            calls.append((name, args))
            return {"ok": True}

    server = build_server(Backend())
    registered = {t.name for t in asyncio.run(server.list_tools())}
    assert registered == set(tools.TOOLS)
    for name in ("create_planned_workout", "update_planned_workout", "delete_planned_workout", "create_event", "update_event", "forget"):
        tool = next(t for t in asyncio.run(server.list_tools()) if t.name == name)
        assert "confirm" in tool.input_schema["properties"], name
        assert "confirm" not in tool.input_schema.get("required", []), name
    asyncio.run(server.call_tool("create_event", {"name": "N", "date": "2027-05-01", "type": "race"}))
    assert calls[-1] == ("create_event", {"name": "N", "date": "2027-05-01", "type": "race"})  # no implicit confirm


def test_memory_block_lists_events_added_through_the_service(session):
    sp.create_event(session, sp.OWNER_ID, {"name": "Henley", "date": sp.today() + timedelta(days=9), "type": "race", "priority": "A", "goal_time": "6:40"})
    assert "Henley" in memory.memory_block(session)
