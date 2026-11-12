from __future__ import annotations

import asyncio
import json

import pytest
from conftest import TEST_PASSWORD
from sqlmodel import select

from catch.api import deps
from catch.api.deps import hash_token
from catch.coach import chat, memory, tools
from catch.core import principal as pr
from catch.core.models import ApiToken, CoachFeedback, TechniqueNote, WorkoutTemplate
from catch.core.principal import ATHLETE, VIEWER, coach_principal
from catch.sync import coaching_notes as cn
from catch.sync import workout_library as lib

SECRET = "SECRET-PRIVATE-TEXT"
COACH = coach_principal(7, "Coach Sam")
NEW_TOOLS = (
    "search_workout_library", "get_workout_template", "create_workout_template", "update_workout_template",
    "get_technique_notes", "add_technique_note", "get_coach_feedback", "add_coach_feedback",
)
TEMPLATE = {"name": "6x3", "workout_type": "erg_intervals", "structure": {"blocks": [{"reps": 6, "work_s": 180, "rest_s": 120}]}}


def ctx(who=ATHLETE, via="mcp"):
    return {"principal": who, "via": via}


def _call(session, name, args, who=ATHLETE):
    return tools.call_tool(session, name, args, ctx=ctx(who))


def _count(session, model):
    return len(session.exec(select(model)).all())


# --- registry ---------------------------------------------------------------------------------------------------


def test_eight_tools_registered_with_strict_schemas_and_correct_write_flags():
    assert len(tools.TOOLS) == 55
    writes = {"create_workout_template", "update_workout_template", "add_technique_note", "add_coach_feedback"}
    for name in NEW_TOOLS:
        spec = tools.TOOLS[name]
        assert spec["write"] is (name in writes), name
        assert spec["input_schema"]["additionalProperties"] is False
        if name in writes:
            assert "confirm" in spec["input_schema"]["properties"]
    assert pr.COACH_TOOLS <= set(tools.TOOLS)


def test_mcp_wrappers_match_the_registry_exactly_including_new_tools():
    from catch.mcp_server.server import build_server

    class Backend:
        async def call_tool(self, name, args):
            return {}

    server = build_server(Backend())
    listed = {t.name for t in asyncio.run(server.list_tools())}
    assert listed == set(tools.TOOLS) and set(NEW_TOOLS) <= listed


def test_chat_labels_and_system_prompt_cover_the_new_tools():
    for name in NEW_TOOLS:
        assert chat._tool_label(name, {"id": 3, "name": "x"}) != name, name
    assert "Preview" in chat._tool_label("add_coach_feedback", {}) and "Save" in chat._tool_label("add_coach_feedback", {"confirm": True})
    prompt = (chat.Path(chat.__file__).parent / "system_prompt.md").read_text()
    for name in NEW_TOOLS:
        assert name in prompt, name
    assert "cannot measure technique" in " ".join(prompt.split())


# --- every write previews first --------------------------------------------------------------------------------------


def _write_calls(session):
    t = lib.create_template(session, "owner", TEMPLATE)
    return {
        "create_workout_template": {**TEMPLATE, "name": "new one"},
        "update_workout_template": {"id": t.id, "description": "changed"},
        "add_technique_note": {"category": "catch", "text": "hands early", "visibility": "coach"},
        "add_coach_feedback": {"text": "logged", "coach_name": "Kim"},
    }


def test_every_write_previews_and_changes_nothing_without_strict_confirm(session):
    calls = _write_calls(session)
    before = (_count(session, WorkoutTemplate), _count(session, TechniqueNote), _count(session, CoachFeedback))
    desc = session.exec(select(WorkoutTemplate)).first().description
    for name, args in calls.items():
        for fake in (None, False, "true", 1, "yes"):
            out = _call(session, name, {**args, **({} if fake is None else {"confirm": fake})})
            assert out["saved"] is False and out["preview"], (name, fake)
            assert "confirm=true" in out["message"]
    assert (_count(session, WorkoutTemplate), _count(session, TechniqueNote), _count(session, CoachFeedback)) == before
    assert session.exec(select(WorkoutTemplate)).first().description == desc


def test_confirmed_writes_save_exactly_what_was_previewed(session):
    calls = _write_calls(session)
    created = _call(session, "create_workout_template", {**calls["create_workout_template"], "confirm": True})
    assert created["saved"] and created["template"]["name"] == "new one" and created["template"]["summary"]["total_duration_s"] == 6 * 180 + 5 * 120
    updated = _call(session, "update_workout_template", {**calls["update_workout_template"], "confirm": True})
    assert updated["template"]["description"] == "changed"
    note = _call(session, "add_technique_note", {**calls["add_technique_note"], "confirm": True})["note"]
    assert note["shared_with_coach"] is True
    fb = _call(session, "add_coach_feedback", {**calls["add_coach_feedback"], "confirm": True})["feedback"]
    assert fb["coach_name"] == "Kim" and fb["author"]["role"] == "athlete" and fb["created_via"] == "mcp"


def test_archive_through_update_previews_the_change(session):
    t = lib.create_template(session, "owner", TEMPLATE)
    held = _call(session, "update_workout_template", {"id": t.id, "archived": True})
    assert held["saved"] is False and held["preview"]["changes"]["archived"] == {"from": False, "to": True}
    assert lib.get_template(session, "owner", t.id).archived_at is None
    _call(session, "update_workout_template", {"id": t.id, "archived": True, "confirm": True})
    assert lib.get_template(session, "owner", t.id).archived_at is not None
    with pytest.raises(ValueError):
        _call(session, "update_workout_template", {"id": t.id})


def test_examples_cannot_be_updated_and_are_hidden_from_default_search(session):
    lib.seed_examples(session)
    ex = lib.search_templates(session, "owner", only_examples=True)[0]
    with pytest.raises(ValueError, match="read-only"):
        _call(session, "update_workout_template", {"id": ex.id, "name": "x", "confirm": True})
    assert _call(session, "search_workout_library", {})["templates"] == []
    assert len(_call(session, "search_workout_library", {"include_examples": True})["templates"]) >= 6


def test_invalid_input_is_a_value_error_not_a_save(session):
    with pytest.raises(ValueError):
        _call(session, "create_workout_template", {"name": "x", "workout_type": "rate_ladder", "confirm": True})
    with pytest.raises(ValueError):
        _call(session, "add_technique_note", {"category": "speed", "text": "x", "confirm": True})
    assert _count(session, WorkoutTemplate) == 0 and _count(session, TechniqueNote) == 0


# --- principals --------------------------------------------------------------------------------------------------------------


def test_new_tools_fail_closed_without_a_principal(session):
    for name in NEW_TOOLS:
        args = {"id": 1} if name in ("get_workout_template", "update_workout_template") else {"text": "x", "category": "catch", "name": "n", "workout_type": "custom"}
        with pytest.raises(ValueError, match="isn't identified"):
            tools.call_tool(session, name, args, ctx={})
        with pytest.raises(ValueError):
            tools.call_tool(session, name, args, ctx={"principal": VIEWER})
        with pytest.raises(ValueError):
            tools.call_tool(session, name, args)  # no ctx at all
    assert _count(session, TechniqueNote) == 0


def test_coach_principal_is_limited_to_the_coaching_tools_in_call_tool(session):
    for name in set(tools.TOOLS) - pr.COACH_TOOLS:
        with pytest.raises(ValueError, match="role can't use"):
            tools.call_tool(session, name, {}, ctx={"principal": COACH})
    assert tools.call_tool(session, "get_technique_notes", {}, ctx={"principal": COACH})["notes"] == []


def test_coach_can_write_only_shared_feedback_under_their_own_name(session):
    held = _call(session, "add_coach_feedback", {"text": "More length", "focus_areas": ["drive"]}, COACH)
    assert held["saved"] is False and held["preview"]["author"] == "Coach Sam"
    with pytest.raises(ValueError, match="always shared"):
        _call(session, "add_coach_feedback", {"text": "x", "visibility": "private", "confirm": True}, COACH)
    with pytest.raises(ValueError, match="only for feedback the athlete logs"):
        _call(session, "add_coach_feedback", {"text": "x", "coach_name": "Someone Else", "confirm": True}, COACH)
    saved = _call(session, "add_coach_feedback", {"text": "More length", "focus_areas": ["drive"], "confirm": True}, COACH)["feedback"]
    assert saved["author"] == {"role": "coach", "id": COACH.id, "name": "Coach Sam"} and saved["shared"] is True


def test_athlete_only_tools_refuse_a_coach_principal_directly(session):
    for name, args in (("create_workout_template", {**TEMPLATE, "confirm": True}), ("add_technique_note", {"category": "catch", "text": "x", "confirm": True})):
        with pytest.raises(ValueError):
            tools.call_tool(session, name, args, ctx={"principal": COACH})


# --- private never reaches a coach ---------------------------------------------------------------------------------------------


def _seed_private(session):
    cn.create_technique_note(session, "owner", ATHLETE, {"category": "catch", "text": f"{SECRET} note"})
    cn.create_technique_note(session, "owner", ATHLETE, {"category": "finish", "text": "shared finish note", "visibility": "coach"})
    fb = cn.create_feedback(session, "owner", ATHLETE, {"text": f"{SECRET} feedback", "visibility": "private", "focus_areas": ["catch"]})
    shared = cn.create_feedback(session, "owner", ATHLETE, {"text": f"{SECRET} draft", "visibility": "private"})
    cn.update_feedback(session, "owner", ATHLETE, shared.id, {"visibility": "shared", "text": "now visible"})
    cn.create_feedback(session, "owner", coach_principal(9, "Coach Lee"), {"text": "coach shared line"})
    return fb


def test_private_text_never_appears_in_any_coach_visible_tool_response(session):
    _seed_private(session)
    outputs = []
    for name, args in (
        ("get_technique_notes", {}), ("get_technique_notes", {"category": "catch"}), ("get_coach_feedback", {}),
        ("get_coach_feedback", {"category": "catch"}), ("get_coach_feedback", {"coach": "athlete"}), ("search_workout_library", {"query": SECRET}),
    ):
        outputs.append(json.dumps(_call(session, name, args, COACH), default=str))
    assert not any(SECRET in o for o in outputs)
    assert "shared finish note" in outputs[0] and "now visible" in outputs[2] and "coach shared line" in outputs[2]
    athlete_view = json.dumps(_call(session, "get_technique_notes", {}), default=str) + json.dumps(_call(session, "get_coach_feedback", {}), default=str)
    assert SECRET in athlete_view  # the athlete's own assistant does see them


def test_memory_block_and_other_unprompted_surfaces_do_not_carry_notes_or_feedback(session):
    _seed_private(session)
    assert SECRET not in memory.memory_block(session)


def test_previews_of_athlete_writes_never_echo_into_coach_reads(session):
    _call(session, "add_technique_note", {"category": "catch", "text": SECRET})  # preview only
    assert SECRET not in json.dumps(_call(session, "get_technique_notes", {}, COACH), default=str)


# --- over REST: bearer tokens -------------------------------------------------------------------------------------------------------


@pytest.fixture
def tokens(session):
    session.add(ApiToken(name="mine", token_hash=hash_token("athlete-tok")))
    session.add(ApiToken(name="sam", token_hash=hash_token("coach-tok"), role="coach", display_name="Coach Sam"))
    session.commit()
    return {"athlete": {"Authorization": "Bearer athlete-tok"}, "coach": {"Authorization": "Bearer coach-tok"}}


def test_rest_tool_endpoint_filters_private_for_coach_tokens_and_refuses_other_tools(client, session, tokens):
    _seed_private(session)
    coach = client.post("/api/coach/tools/get_technique_notes", json={"args": {}}, headers=tokens["coach"])
    assert coach.status_code == 200 and SECRET not in coach.text and "shared finish note" in coach.text
    athlete = client.post("/api/coach/tools/get_technique_notes", json={"args": {}}, headers=tokens["athlete"])
    assert SECRET in athlete.text
    fb = client.post("/api/coach/tools/get_coach_feedback", json={"args": {}}, headers=tokens["coach"])
    assert SECRET not in fb.text and "coach shared line" in fb.text
    for name in ("get_today", "list_workouts", "get_wellness", "create_workout_template", "add_technique_note"):
        r = client.post(f"/api/coach/tools/{name}", json={"args": {}}, headers=tokens["coach"])
        assert r.status_code == 403, name
    assert client.post("/api/coach/tools/get_today", json={"args": {}}, headers=tokens["athlete"]).status_code == 200


def test_rest_tool_listing_for_a_coach_token_shows_only_coach_tools(client, tokens):
    names = {t["name"] for t in client.get("/api/coach/tools", headers=tokens["coach"]).json()}
    assert names == pr.COACH_TOOLS
    assert len({t["name"] for t in client.get("/api/coach/tools", headers=tokens["athlete"]).json()}) == 55


def test_cookie_login_is_the_athlete_on_the_tool_endpoint(client, session):
    _seed_private(session)
    client.post("/api/login", json={"password": TEST_PASSWORD})
    assert SECRET in client.post("/api/coach/tools/get_technique_notes", json={"args": {}}).text


def test_rest_write_attributes_via_header(client, session, tokens):
    r = client.post("/api/coach/tools/add_coach_feedback", json={"args": {"text": "hello", "confirm": True}}, headers={**tokens["coach"], "X-Catch-Client": "mcp"})
    assert r.json()["feedback"]["created_via"] == "mcp"
    r = client.post("/api/coach/tools/add_coach_feedback", json={"args": {"text": "hello 2", "confirm": True}}, headers=tokens["coach"])
    assert r.json()["feedback"]["created_via"] == "rest"


def test_no_route_hands_a_coach_token_athlete_data_by_accident(client, tokens):
    """Every route that accepts a bearer token must either refuse coach-role tokens
    (`require_tool_auth`) or be one of the two tool endpoints that opt in."""
    from fastapi.routing import APIRoute

    opted_in, seen = set(), 0
    for included in client.app.routes:
        router = getattr(included, "original_router", None)
        if router is None:
            continue
        router_calls = {d.call for dep in router.dependencies for d in _walk_dep(dep)}
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            seen += 1
            calls = {d.call for d in _walk(route.dependant)} | router_calls
            if deps.require_tool_auth_allow_coach in calls:
                opted_in.add((route.path, tuple(sorted(route.methods))))
            if deps.require_tool_auth in calls:
                r = client.request(next(iter(route.methods)), route.path.replace("{name}", "get_today"), headers=tokens["coach"])
                assert r.status_code == 403, route.path
    assert seen > 100
    assert opted_in == {("/api/coach/tools", ("GET",)), ("/api/coach/tools/{name}", ("POST",))}
    # Everything else is cookie-only: a coach (or athlete) bearer token gets 401.
    for path in ("/api/coach/tokens", "/api/coach/conversations", "/api/library/templates", "/api/coach-feedback", "/api/technique-notes", "/api/calendar?from=2026-11-01&to=2026-11-07", "/api/today"):
        for who in ("coach", "athlete"):
            assert client.get(path, headers=tokens[who]).status_code == 401, (path, who)


def _walk_dep(dep):
    from fastapi.dependencies.utils import get_dependant

    yield from _walk(get_dependant(path="/", call=dep.dependency))


def _walk(dependant):
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk(sub)


def test_bare_require_tool_auth_refuses_coach_tokens(session, tokens):
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient

    from catch.api.deps import get_db, require_tool_auth

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: session

    @app.get("/x")
    def x(_=Depends(require_tool_auth)):
        return {"ok": True}

    c = TestClient(app)
    assert c.get("/x", headers=tokens["coach"]).status_code == 403
    assert c.get("/x", headers=tokens["athlete"]).status_code == 200
    assert c.get("/x").status_code == 401


def test_token_management_accepts_a_role_and_hides_nothing_secret(client, session):
    client.post("/api/login", json={"password": TEST_PASSWORD})
    made = client.post("/api/coach/tokens", json={"name": "sam", "role": "coach", "display_name": " Coach Sam "}).json()
    assert made["role"] == "coach" and made["display_name"] == "Coach Sam" and made["token"]
    listed = client.get("/api/coach/tokens").json()
    assert listed[0]["role"] == "coach" and "token" not in listed[0] and "token_hash" not in listed[0]
    assert client.post("/api/coach/tokens", json={"name": "x", "role": "admin"}).status_code == 422
    plain = client.post("/api/coach/tokens", json={"name": "laptop"}).json()
    assert plain["role"] == "athlete"
    assert client.post("/api/coach/tools/get_technique_notes", json={"args": {}}, headers={"Authorization": f"Bearer {made['token']}"}).status_code == 200
