from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from catch.analytics.erg_math import w_per_kg
from catch.analytics.erg_test import TEST_SPECS, pacing_analysis, pacing_plan as _pacing_plan, project_time
from catch.api import routes_activities, routes_analytics
from catch.api.deps import get_db, require_auth
from catch.coach.memory import next_a_race
from catch.core.models import CanonicalActivity, Event
from catch.sync import body_comp, erg_test

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/tests/candidates")
def get_candidates(db: Session = Depends(get_db)):
    return {"candidates": erg_test.list_candidates(db)}


@router.get("/api/tests")
def get_tests(test_type: str | None = Query(None, alias="type"), db: Session = Depends(get_db)):
    return {"tests": erg_test.list_tests(db, test_type)}


def _find_plan_for(db: Session, canonical: CanonicalActivity, test_type: str | None) -> dict | None:
    """Best-effort match: the most recently generated plan whose target distance is within
    1% of this test's own distance — standard test distances are fixed numbers (2000m is
    always 2000m), so this is exact for every standard type and simply finds nothing for a
    custom one with no matching saved plan (task Part C.3's "show it on the test detail
    afterwards" doesn't specify how a plan is matched back to the test that fulfilled it, so
    this is a documented simplification, not a literal spec requirement)."""
    if canonical.distance is None:
        return None
    events = db.exec(select(Event).where(Event.plan_json.is_not(None)).order_by(Event.created_at.desc())).all()
    for e in events:
        plan = json.loads(e.plan_json)
        if plan.get("distance_m") and abs(plan["distance_m"] - canonical.distance) <= max(10.0, canonical.distance * 0.01):
            return plan
    return None


class PacingPlanRequest(BaseModel):
    test_type: str
    goal_time_s: float
    style: str
    distance_m: float | None = None  # required for "custom"; for 30min_r20/60min, the
    # *target distance to cover* in that fixed duration — see catch/sync/erg_test.py's
    # module docstring for why that's the natural way to frame those two types' goal.
    save_to_next_event: bool = False


@router.post("/api/tests/pacing-plan")
def make_pacing_plan(body: PacingPlanRequest = Body(...), db: Session = Depends(get_db)):
    if body.test_type not in TEST_SPECS and body.test_type != "custom":
        raise HTTPException(status_code=422, detail=f"test_type must be one of {(*TEST_SPECS, 'custom')}")
    spec = TEST_SPECS.get(body.test_type, {})
    distance_m = spec.get("distance_m") or body.distance_m
    if not distance_m:
        raise HTTPException(status_code=422, detail="distance_m is required for this test_type")
    try:
        plan = _pacing_plan(distance_m, body.goal_time_s, body.style)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    plan["test_type"] = body.test_type

    saved_to_event = None
    if body.save_to_next_event:
        event = erg_test.next_relevant_event(db)
        if event is not None:
            erg_test.save_pacing_plan(db, event.id, plan)
            saved_to_event = {"id": event.id, "name": event.name, "date": event.date}
    return {"plan": plan, "saved_to_event": saved_to_event}


@router.get("/api/tests/projection")
def get_projection(test_type: str = Query(..., alias="type"), db: Session = Depends(get_db)):
    history = [
        (date.fromisoformat(t["date"]), t["duration_s"])
        for t in erg_test.list_tests(db, test_type)
        if t["date"] and t["duration_s"]
    ]
    history.sort(key=lambda h: h[0])
    race = next_a_race(db)
    target_date = race["date"] if race else date.today() + timedelta(days=90)
    result = project_time(history, target_date)
    result["target_date"] = target_date
    result["target_event"] = race
    return result


# Registered *last*, deliberately — Starlette matches routes in registration order on
# (method, path pattern) alone, and `{canonical_id}` (no `:int` converter) structurally
# matches any single path segment, including "candidates"/"projection". A test caught this
# exact bug live: GET /api/tests/projection 422'd with "projection" being parsed as an int.
# Same pitfall, same fix, as GET /api/activities/duplicates (see that router's comment).
@router.get("/api/tests/{canonical_id}")
def get_test_detail(canonical_id: int, db: Session = Depends(get_db)):
    canonical = db.get(CanonicalActivity, canonical_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Test not found")
    overrides = json.loads(canonical.overrides_json) if canonical.overrides_json else {}
    if "test" not in (overrides.get("tags") or []):
        raise HTTPException(status_code=404, detail="This workout isn't tagged as a test")
    test_type = overrides.get("test_type")

    detail = routes_activities.get_activity(canonical_id, db=db)
    member = next((s for s in detail["sources"] if s["source"] == "concept2"), None)
    if member is None:
        raise HTTPException(status_code=404, detail="No Concept2 stroke data for this test")
    strokes_payload = routes_analytics.erg_strokes(member["activity_id"], db=db)

    plan = _find_plan_for(db, canonical, test_type)
    analysis = pacing_analysis(strokes_payload["strokes"], canonical.distance or 0.0, plan) if canonical.distance else None

    this_date = detail["local_date"].isoformat() if detail.get("local_date") else None
    same_type = [t for t in erg_test.list_tests(db, test_type) if t["canonical_id"] != canonical_id] if test_type else []
    earlier = max(
        (t for t in same_type if this_date and t["date"] and t["date"] < this_date), key=lambda t: t["date"], default=None
    )

    weight_kg = body_comp.nearest_resolved_weight_kg(db, canonical.start)
    return {
        "activity": detail,
        "test_type": test_type,
        "plan": plan,
        "pacing_analysis": analysis,
        "compare_to_earlier": earlier,
        "w_per_kg": w_per_kg(canonical.avg_power, weight_kg),
    }
