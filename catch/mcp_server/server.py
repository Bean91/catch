from __future__ import annotations

from typing import Literal, Optional

from mcp.server.mcpserver import MCPServer

from catch.mcp_server.backend import ToolBackend

# ISO dates/datetimes are passed through as plain strings — the backend (catch/coach/
# tools.py's call_tool) parses them, so the schema here doesn't need to model date/datetime
# itself, which keeps every tool's signature a flat set of JSON-primitive parameters.


def build_server(backend: ToolBackend) -> MCPServer:
    mcp = MCPServer(
        "catch",
        instructions=(
            "Tools for Catch, a personal rowing training app: read-only access to recovery/"
            "strain/sleep/HRV, workouts, trends, body composition, training load, 2k "
            "prediction, zones, nutrition (intake vs. expenditure, under-fuelling), and erg "
            "tests (pacing analysis, pacing-plan generation), plus food/strength logging and "
            "a small shared memory of events/goals/athlete facts that the in-app coach also "
            "reads and writes. get_today also carries today's morning check-in and the "
            "illness early-warning level."
        ),
    )

    async def _call(name: str, **kwargs) -> dict:
        args = {k: v for k, v in kwargs.items() if v is not None}
        return await backend.call_tool(name, args)

    @mcp.tool()
    async def get_today() -> dict:
        """Today's recovery, strain, sleep, HRV/resting-HR trend, latest erg piece, predicted
        2k, the next A-priority race with days-to-go and a taper flag, today's subjective
        check-in and niggle flag, and the illness early-warning level (none/watch/likely)."""
        return await _call("get_today")

    @mcp.tool()
    async def get_wellness(from_: Optional[str] = None, to: Optional[str] = None) -> dict:
        """Daily wellness history (resting HR, HRV rMSSD, sleep, stress, body battery, SpO2,
        respiration) over an ISO date range. Capped to 180 days."""
        return await _call("get_wellness", **{"from": from_, "to": to})

    @mcp.tool()
    async def list_workouts(
        from_: Optional[str] = None, to: Optional[str] = None, type: Optional[Literal["erg", "on_water", "strength", "other"]] = None
    ) -> dict:
        """Recent workouts (Garmin + Concept2, deduped), newest first, up to 50."""
        return await _call("list_workouts", **{"from": from_, "to": to, "type": type})

    @mcp.tool()
    async def get_workout(id: int) -> dict:
        """One workout's full detail. For a Concept2 erg piece, also stroke data (downsampled
        to at most 100 points) plus the per-interval table."""
        return await _call("get_workout", id=id)

    @mcp.tool()
    async def get_trends(
        metric: Literal[
            "recovery", "hrv_rmssd", "resting_hr", "sleep_score", "stress", "body_battery",
            "spo2", "respiration", "strain", "load_acr", "weight", "w_per_kg", "predicted_2k",
            "checkin_soreness", "checkin_stress", "checkin_mood", "checkin_sleep_quality",
        ],
        from_: Optional[str] = None,
        to: Optional[str] = None,
    ) -> dict:
        """A daily time series for one metric over an ISO date range. Capped to 180 points."""
        return await _call("get_trends", metric=metric, **{"from": from_, "to": to})

    @mcp.tool()
    async def get_body_comp(from_: Optional[str] = None, to: Optional[str] = None) -> dict:
        """Resolved daily body-composition readings (weight, fat_pct, muscle_kg — Withings
        and/or a Garmin scale, or a manual entry; never averaged) over an ISO date range.
        Capped to 180 days."""
        return await _call("get_body_comp", **{"from": from_, "to": to})

    @mcp.tool()
    async def get_load() -> dict:
        """Most recent acute:chronic training-load figure (7d/42d EWMA, form, band)."""
        return await _call("get_load")

    @mcp.tool()
    async def predict_2k() -> dict:
        """Predicted 2k time, extrapolated via Paul's law from recent qualifying erg pieces."""
        return await _call("predict_2k")

    @mcp.tool()
    async def get_zones() -> dict:
        """Current HR and power training-zone boundaries, plus the default zone-mode view."""
        return await _call("get_zones")

    @mcp.tool()
    async def get_nutrition(from_: Optional[str] = None, to: Optional[str] = None) -> dict:
        """Daily intake (kcal/protein) vs. Garmin expenditure over an ISO date range (default:
        trailing 7 days), plus a calm under-fuelling flag when several recent logged days ran
        well below expenditure. Unlogged days are never treated as zero intake."""
        return await _call("get_nutrition", **{"from": from_, "to": to})

    @mcp.tool()
    async def log_food(
        quantity: float,
        meal: Literal["breakfast", "lunch", "dinner", "snack", "pre_workout", "post_workout"],
        description: Optional[str] = None,
        barcode: Optional[str] = None,
        food_id: Optional[int] = None,
        unit: Optional[Literal["g", "serving"]] = None,
    ) -> dict:
        """Log a food to the nutrition diary. Identify the food by exactly one of description
        (free text, searched against the local cache + USDA), barcode, or food_id (from a prior
        ambiguous response's candidates). A description match that isn't a single confident hit
        returns candidates instead of guessing — call again with the right food_id. Always
        confirm in chat what was logged (food, quantity, kcal/protein/carbs/fat)."""
        return await _call(
            "log_food", description=description, barcode=barcode, food_id=food_id,
            quantity=quantity, unit=unit, meal=meal,
        )

    @mcp.tool()
    async def add_note(date: str, text: str, rpe: Optional[int] = None) -> dict:
        """Save a training note and/or RPE (0-10) for an ISO date. Overwrites any existing
        note for that date."""
        return await _call("add_note", date=date, text=text, rpe=rpe)

    @mcp.tool()
    async def rename_activity(id: int, title: str) -> dict:
        """Rename a canonical workout (overrides any source/auto title, survives re-sync)."""
        return await _call("rename_activity", id=id, title=title)

    @mcp.tool()
    async def tag_activity(id: int, tags: list[str]) -> dict:
        """Set a canonical workout's tags (e.g. race, test, technique, cross-training) —
        replaces any existing tags."""
        return await _call("tag_activity", id=id, tags=tags)

    @mcp.tool()
    async def merge_activities(canonical_id_a: int, canonical_id_b: int, confirm: Optional[bool] = None) -> dict:
        """Merge two canonical workouts (e.g. a watch recording and a Peloton-pushed
        duplicate of the same ride) into one. Call once without confirm to preview, tell
        the athlete what will merge, and only call again with confirm=true once they agree."""
        return await _call("merge_activities", canonical_id_a=canonical_id_a, canonical_id_b=canonical_id_b, confirm=confirm)

    @mcp.tool()
    async def log_strength(
        text: Optional[str] = None,
        sets: Optional[list[dict]] = None,
        confirm: Optional[bool] = None,
    ) -> dict:
        """Log a lifting set, from free text (one exercise per call, e.g. '3x8 cable row
        stack 12 on station 2') or a structured sets list. Always call once without
        confirm=true first — this returns a preview of the parsed exercise/reps/load for the
        athlete to check. Only call again with the same sets and confirm=true once the
        athlete has confirmed it's right."""
        return await _call("log_strength", text=text, sets=sets, confirm=confirm)

    @mcp.tool()
    async def get_strength(
        from_: Optional[str] = None, to: Optional[str] = None, exercise_id: Optional[int] = None, exercise_name: Optional[str] = None
    ) -> dict:
        """Logged strength sets over an ISO date range (default: last 28 days), optionally
        filtered to one exercise. Capped to 180 rows."""
        return await _call("get_strength", **{"from": from_, "to": to}, exercise_id=exercise_id, exercise_name=exercise_name)

    @mcp.tool()
    async def get_muscle_readiness() -> dict:
        """Raw muscular load (AU) per muscle group over the trailing 72 hours — which muscle
        groups are still loaded from recent lifting."""
        return await _call("get_muscle_readiness")

    @mcp.tool()
    async def get_tests(
        type: Optional[Literal["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"]] = None,
    ) -> dict:
        """List confirmed erg tests, newest first, optionally filtered to one type."""
        return await _call("get_tests", type=type)

    @mcp.tool()
    async def get_test(id: int) -> dict:
        """One erg test's full detail: pacing analysis vs. any saved plan, comparison to the
        athlete's earlier test of the same type, and W/kg."""
        return await _call("get_test", id=id)

    @mcp.tool()
    async def make_pacing_plan(
        test_type: Literal["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"],
        goal_time_s: float,
        style: Literal["even", "fast_start_settle", "negative_split"],
        distance_m: Optional[float] = None,
        save_to_next_event: Optional[bool] = None,
    ) -> dict:
        """Generate a pacing plan for a test type/goal time/style. Saves it to the athlete's
        next upcoming event by default."""
        return await _call(
            "make_pacing_plan", test_type=test_type, goal_time_s=goal_time_s, style=style,
            distance_m=distance_m, save_to_next_event=save_to_next_event,
        )

    @mcp.tool()
    async def remember(
        category: Literal["injury", "schedule", "equipment", "preference", "other"],
        text: str,
        valid_until: Optional[str] = None,
    ) -> dict:
        """Save a durable fact about the athlete. Only call this for something the athlete
        actually said — never infer or guess a fact."""
        return await _call("remember", category=category, text=text, valid_until=valid_until)

    @mcp.tool()
    async def add_event(
        name: str,
        date: str,
        type: Literal["race", "2k_test", "camp", "selection"],
        distance: Optional[str] = None,
        boat_class: Optional[str] = None,
        priority: Optional[Literal["A", "B", "C"]] = None,
        goal_time: Optional[str] = None,
        result: Optional[str] = None,
    ) -> dict:
        """Record a race, test, camp, or selection event. Ask for a concrete date first if the
        athlete was vague about timing."""
        return await _call(
            "add_event", name=name, date=date, type=type, distance=distance, boat_class=boat_class,
            priority=priority, goal_time=goal_time, result=result,
        )

    @mcp.tool()
    async def update_event(
        id: int,
        name: Optional[str] = None,
        date: Optional[str] = None,
        type: Optional[Literal["race", "2k_test", "camp", "selection"]] = None,
        distance: Optional[str] = None,
        boat_class: Optional[str] = None,
        priority: Optional[Literal["A", "B", "C"]] = None,
        goal_time: Optional[str] = None,
        result: Optional[str] = None,
    ) -> dict:
        """Update fields on an existing event (e.g. record a result after it happened)."""
        return await _call(
            "update_event", id=id, name=name, date=date, type=type, distance=distance, boat_class=boat_class,
            priority=priority, goal_time=goal_time, result=result,
        )

    @mcp.tool()
    async def set_goal(
        text: str,
        id: Optional[int] = None,
        target_date: Optional[str] = None,
        status: Optional[Literal["active", "done", "abandoned"]] = None,
    ) -> dict:
        """Create a new goal, or pass id to update an existing one's text/target_date/status."""
        return await _call("set_goal", text=text, id=id, target_date=target_date, status=status)

    @mcp.tool()
    async def forget(ref: str) -> dict:
        """Delete a memory item by its prefixed ref (e.g. 'fact:12', 'event:3', 'goal:5'), as
        returned by recall."""
        return await _call("forget", ref=ref)

    @mcp.tool()
    async def recall(query: Optional[str] = None) -> dict:
        """Search stored events, goals, and facts. Omit query to list everything current."""
        return await _call("recall", query=query)

    @mcp.prompt()
    def daily_check_in() -> str:
        """A short daily check-in with the coach."""
        return (
            "Give me my daily check-in: call get_today, then tell me plainly how recovery and "
            "strain look and why (name the components driving each), whether today should be "
            "hard, easy, or rest, and flag anything about an upcoming A race's taper window if "
            "one is close. Keep it to a few sentences."
        )

    @mcp.prompt()
    def weekly_review() -> str:
        """A weekly training review with the coach."""
        return (
            "Give me a weekly review: call get_trends for recovery, strain, and load_acr over "
            "the last 7-14 days, and list_workouts for the same window. Summarize the volume "
            "and intensity pattern, call out whether load is trending toward undertraining, "
            "optimal, caution, or high-risk, and suggest one concrete adjustment for next week."
        )

    return mcp
