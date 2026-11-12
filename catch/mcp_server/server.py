from __future__ import annotations

from typing import Literal, Optional

from mcp.server.mcpserver import MCPServer

from catch.mcp_server.backend import ToolBackend

# ISO dates/datetimes are passed through as plain strings — the backend (catch/coach/
# tools.py's call_tool) parses them, so the schema here doesn't need to model date/datetime
# itself, which keeps every tool's signature a flat set of JSON-primitive parameters.


WorkoutType = Literal["erg_intervals", "steady_state", "rate_ladder", "distance_piece", "time_piece", "strength", "on_water", "custom"]
Zone = Literal["UT2", "UT1", "AT", "TR", "AN"]
Category = Literal["catch", "drive", "finish", "recovery", "sequencing", "posture", "rate_control", "blade_boat_handling"]
Focus = Literal["catch", "drive", "finish", "recovery", "sequencing", "posture", "rate_control", "blade_boat_handling", "pacing", "fitness", "strength", "racing", "other"]


def build_server(backend: ToolBackend) -> MCPServer:
    mcp = MCPServer(
        "catch",
        instructions=(
            "Tools for Catch, a personal rowing training app: read-only access to recovery/"
            "strain/sleep/HRV, workouts, trends, body composition, training load, 2k "
            "prediction, zones, nutrition (intake vs. expenditure, under-fuelling), and erg "
            "tests (pacing analysis, pacing-plan generation), training intelligence "
            "(a training profile, equivalent-piece performance trends, training "
            "distribution/consistency, insights, and recommendations), plus food/strength "
            "logging and a small shared memory of events/goals/athlete facts that the "
            "in-app coach also reads and writes. get_today also carries today's morning "
            "check-in and the illness early-warning level. For outdoor workouts with GPS: "
            "get_route, get_route_history, get_on_water_metrics and get_workout_weather "
            "(GPS-derived figures are labelled; weather is context, not a correction). The "
            "calendar: get_calendar, get_upcoming_events, get_event (with a race projection that "
            "states its assumptions and uncertainty) and get_training_phase read plans; "
            "create_planned_workout, update_planned_workout, delete_planned_workout, "
            "create_event and update_event write them and always preview first — pass "
            "confirm=true only after the athlete has agreed. A planned session is an intention, "
            "never a completed workout. The workout library: search_workout_library, "
            "get_workout_template, create_workout_template and update_workout_template (templates "
            "are reusable definitions, not workouts or prescriptions; built-in examples are only "
            "illustrations). Technique notes and coach feedback: get_technique_notes, "
            "add_technique_note, get_coach_feedback, add_coach_feedback — written observations only, "
            "Catch can't measure technique quality, and private items are never shared with a coach. "
            "Every write previews first; pass confirm=true only after the athlete has agreed."
        ),
    )

    # Positional-only: a tool with its own `name` parameter (create_event/update_event) would
    # otherwise collide with this function's first argument ("multiple values for 'name'").
    async def _call(tool_name: str, /, **kwargs) -> dict:
        args = {k: v for k, v in kwargs.items() if v is not None}
        return await backend.call_tool(tool_name, args)

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
    async def get_test(id: Optional[int] = None, piece_id: Optional[int] = None) -> dict:
        """One erg test's full detail: pacing analysis vs. any saved plan, comparison to the
        athlete's earlier test of the same type, and W/kg. get_tests' rows carry a "kind" of
        "test" or "piece" — pass that row's id for a test, or piece_id for a piece."""
        return await _call("get_test", id=id, piece_id=piece_id)

    @mcp.tool()
    async def add_piece(
        piece_type: Literal["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"],
        canonical_id: Optional[int] = None,
        text: Optional[str] = None,
        splits: Optional[list[dict]] = None,
        distance_m: Optional[float] = None,
        duration_s: Optional[float] = None,
        repeat: Optional[dict] = None,
        intervals: Optional[list[dict]] = None,
        confirm: Optional[bool] = None,
    ) -> dict:
        """Add a piece (a segment of a workout, e.g. a 2k inside a longer row) from free text
        like 'my 2k was 6:32.4, splits 1:36.8, 1:38.9, 1:39.0, 1:37.7' or a structured splits
        list. Call once without confirm to preview the parsed table for the athlete to check,
        then call again with the same data and confirm=true once they agree. canonical_id
        defaults to the most recent workout. For interval work (e.g. 4 x 500m with 1:00 rest) pass
        piece_type='custom' and repeat={count, distance_m or duration_s, rest_s}, or an explicit
        intervals list for variable structures."""
        return await _call(
            "add_piece", piece_type=piece_type, canonical_id=canonical_id, text=text, splits=splits,
            distance_m=distance_m, duration_s=duration_s, repeat=repeat, intervals=intervals, confirm=confirm,
        )

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
    async def get_calendar(from_: str, to: str) -> dict:
        """The calendar for an ISO date range (at most 100 days): planned sessions (intentions),
        completed workouts (what actually happened), events, training phases, and possible
        plan-to-workout matches. Only completed workouts count as training done."""
        return await _call("get_calendar", **{"from": from_, "to": to})

    @mcp.tool()
    async def get_upcoming_events(limit: Optional[int] = None) -> dict:
        """The next events (races, tests, camps) with days-to-go, priority and a taper flag."""
        return await _call("get_upcoming_events", limit=limit)

    @mcp.tool()
    async def get_event(id: int) -> dict:
        """One event in full: countdown, goals, current phase, test history, pacing plan, and a
        race projection with its data, assumptions and uncertainty (or why none exists)."""
        return await _call("get_event", id=id)

    @mcp.tool()
    async def get_training_phase(date: Optional[str] = None) -> dict:
        """The training phase on a date (default today): weekly targets, this week's planned vs
        completed numbers, whether a coach approved the plan, and review flags for large
        planned workload changes."""
        return await _call("get_training_phase", date=date)

    @mcp.tool()
    async def create_planned_workout(
        date: str,
        session_type: Literal["erg", "on_water", "run", "bike", "strength", "cross", "test", "rest", "other"],
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        duration_min: Optional[float] = None,
        distance_m: Optional[float] = None,
        target_zone: Optional[Literal["UT2", "UT1", "AT", "TR", "AN"]] = None,
        intensity_note: Optional[str] = None,
        description: Optional[str] = None,
        structure: Optional[list[dict]] = None,
        event_id: Optional[int] = None,
        notes: Optional[str] = None,
        coach_feedback: Optional[str] = None,
        repeat: Optional[dict] = None,
        confirm: Optional[bool] = None,
    ) -> dict:
        """Add a planned session (an intention, never a completed workout). Previews unless
        confirm=true — set that only after the athlete confirms the preview. Don't propose
        aggressive volume; respect recovery and any coach guidance."""
        return await _call(
            "create_planned_workout", date=date, session_type=session_type, title=title, start_time=start_time,
            duration_min=duration_min, distance_m=distance_m, target_zone=target_zone, intensity_note=intensity_note,
            description=description, structure=structure, event_id=event_id, notes=notes, coach_feedback=coach_feedback,
            repeat=repeat, confirm=confirm,
        )

    @mcp.tool()
    async def update_planned_workout(
        id: int,
        date: Optional[str] = None,
        session_type: Optional[Literal["erg", "on_water", "run", "bike", "strength", "cross", "test", "rest", "other"]] = None,
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        duration_min: Optional[float] = None,
        distance_m: Optional[float] = None,
        target_zone: Optional[Literal["UT2", "UT1", "AT", "TR", "AN"]] = None,
        intensity_note: Optional[str] = None,
        description: Optional[str] = None,
        structure: Optional[list[dict]] = None,
        event_id: Optional[int] = None,
        notes: Optional[str] = None,
        coach_feedback: Optional[str] = None,
        status: Optional[Literal["planned", "skipped"]] = None,
        scope: Optional[Literal["this", "this_and_following"]] = None,
        confirm: Optional[bool] = None,
    ) -> dict:
        """Change or move (new date) a planned session. Previews the before/after unless
        confirm=true — set that only after the athlete confirms."""
        return await _call(
            "update_planned_workout", id=id, date=date, session_type=session_type, title=title, start_time=start_time,
            duration_min=duration_min, distance_m=distance_m, target_zone=target_zone, intensity_note=intensity_note,
            description=description, structure=structure, event_id=event_id, notes=notes, coach_feedback=coach_feedback,
            status=status, scope=scope, confirm=confirm,
        )

    @mcp.tool()
    async def delete_planned_workout(
        id: int, scope: Optional[Literal["this", "this_and_following"]] = None, confirm: Optional[bool] = None
    ) -> dict:
        """Remove a planned session (never a completed workout). Previews unless confirm=true —
        set that only after the athlete confirms."""
        return await _call("delete_planned_workout", id=id, scope=scope, confirm=confirm)

    @mcp.tool()
    async def create_event(
        name: str,
        date: str,
        type: Literal["race", "2k_test", "camp", "selection"],
        distance: Optional[str] = None,
        distance_m: Optional[float] = None,
        boat_class: Optional[str] = None,
        priority: Optional[Literal["A", "B", "C"]] = None,
        goal_time: Optional[str] = None,
        result: Optional[str] = None,
        location: Optional[str] = None,
        goals: Optional[str] = None,
        notes: Optional[str] = None,
        confirm: Optional[bool] = None,
    ) -> dict:
        """Record a race, test, camp, or selection. Ask for a concrete date first if the athlete
        was vague. Previews unless confirm=true — set that only after the athlete confirms."""
        return await _call(
            "create_event", name=name, date=date, type=type, distance=distance, distance_m=distance_m,
            boat_class=boat_class, priority=priority, goal_time=goal_time, result=result, location=location,
            goals=goals, notes=notes, confirm=confirm,
        )

    @mcp.tool()
    async def update_event(
        id: int,
        name: Optional[str] = None,
        date: Optional[str] = None,
        type: Optional[Literal["race", "2k_test", "camp", "selection"]] = None,
        distance: Optional[str] = None,
        distance_m: Optional[float] = None,
        boat_class: Optional[str] = None,
        priority: Optional[Literal["A", "B", "C"]] = None,
        goal_time: Optional[str] = None,
        result: Optional[str] = None,
        location: Optional[str] = None,
        goals: Optional[str] = None,
        notes: Optional[str] = None,
        confirm: Optional[bool] = None,
    ) -> dict:
        """Update fields on an existing event. Previews the before/after unless confirm=true —
        set that only after the athlete confirms."""
        return await _call(
            "update_event", id=id, name=name, date=date, type=type, distance=distance, distance_m=distance_m,
            boat_class=boat_class, priority=priority, goal_time=goal_time, result=result, location=location,
            goals=goals, notes=notes, confirm=confirm,
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
    async def forget(ref: str, confirm: Optional[bool] = None) -> dict:
        """Delete a memory item by its prefixed ref (e.g. 'fact:12', 'event:3', 'goal:5'), as
        returned by recall. Deleting an event previews unless confirm=true."""
        return await _call("forget", ref=ref, confirm=confirm)

    @mcp.tool()
    async def recall(query: Optional[str] = None) -> dict:
        """Search stored events, goals, and facts. Omit query to list everything current."""
        return await _call("recall", query=query)

    @mcp.tool()
    async def get_training_profile() -> dict:
        """The athlete's current training profile: inferred phase, performance trajectory,
        consistency summary, data-supported strengths/areas to investigate, today's recovery/
        load/illness context, and a confidence level based on data completeness."""
        return await _call("get_training_profile")

    @mcp.tool()
    async def get_performance_trends(
        piece_type: Optional[Literal["500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom"]] = None,
    ) -> dict:
        """Equivalent-piece performance trends per test/piece type: best/typical/recent, a
        trend projection, and whether an apparent improvement might just be a pacing/rate
        change."""
        return await _call("get_performance_trends", piece_type=piece_type)

    @mcp.tool()
    async def get_interval_comparisons() -> dict:
        """Interval-session progress grouped by identical structure (e.g. '4x500m/r60'):
        best/typical/recent weighted-average split across sessions. Interval pieces are kept
        out of single-effort PBs and test trends, so this is where their progress is read."""
        return await _call("get_interval_comparisons")

    @mcp.tool()
    async def get_route(activity_id: int) -> dict:
        """GPS summary of one workout: general area, GPS-derived distance/moving time/average
        speed next to the distance Garmin reported, the filtering report, and the repeated
        route it belongs to (if any). No coordinates are returned. If there is no GPS track
        it says why."""
        return await _call("get_route", activity_id=activity_id)

    @mcp.tool()
    async def get_route_history(route_id: int) -> dict:
        """Sessions on one repeated route: best/typical/recent moving average speed, speed
        distribution, heart-rate context and the weather beside each. Not wind-, current- or
        water-corrected; weather differences are observations, not adjustments."""
        return await _call("get_route_history", route_id=route_id)

    @mcp.tool()
    async def get_on_water_metrics(activity_id: int, split_m: Optional[float] = None) -> dict:
        """GPS-derived metrics for one workout: distance, elapsed vs moving time, average and
        peak speed, pace (s/500m for rowing), a split table over split_m metres, pace
        consistency and a lap breakdown. Each figure is labelled gps_derived or provider; raw
        GPS figures are not corrected for conditions."""
        return await _call("get_on_water_metrics", activity_id=activity_id, split_m=split_m)

    @mcp.tool()
    async def get_workout_weather(activity_id: int) -> dict:
        """Observed weather for a workout's window and area (temperature, wind speed/gusts and
        the direction it blows from, precipitation, humidity, conditions) with a status and
        coverage. Gridded reanalysis for the area, not a measurement at the water; context
        only, never a performance correction."""
        return await _call("get_workout_weather", activity_id=activity_id)

    @mcp.tool()
    async def get_training_distribution(weeks: Optional[int] = None) -> dict:
        """Weekly training volume by HR zone (UT2/UT1/AT/TR/AN) plus strength-session
        minutes, over a trailing window (default 12 weeks)."""
        return await _call("get_training_distribution", weeks=weeks)

    @mcp.tool()
    async def get_training_consistency(weeks: Optional[int] = None) -> dict:
        """Sessions completed vs. the athlete's own weekly target, rest days, whether
        training has been unusually concentrated, and the zone-distribution split."""
        return await _call("get_training_consistency", weeks=weeks)

    @mcp.tool()
    async def get_training_insights() -> dict:
        """A short list of recurring patterns the data supports, each with its own
        confidence and evidence. Worded correlationally, never as proof of cause."""
        return await _call("get_training_insights")

    @mcp.tool()
    async def get_recommendations(
        status: Optional[Literal["active", "dismissed", "all"]] = None,
        type: Optional[Literal["training_suggestion", "recovery_suggestion", "data_quality_warning", "overload_warning", "plan_review"]] = None,
    ) -> dict:
        """Training/recovery/data-quality/overload recommendations, with reasoning and
        evidence. Never prescribes aggressive training or tells the athlete to ignore
        symptoms."""
        return await _call("get_recommendations", status=status, type=type)

    @mcp.tool()
    async def rate_recommendation(id: int, rating: Literal["useful", "not_useful"]) -> dict:
        """Mark a recommendation (by its id from get_recommendations) useful or not useful."""
        return await _call("rate_recommendation", id=id, rating=rating)

    # --- Session 22: workout library, technique notes, coach feedback ----------------------------

    @mcp.tool()
    async def search_workout_library(
        query: Optional[str] = None, workout_type: Optional[WorkoutType] = None, session_type: Optional[str] = None,
        difficulty: Optional[Literal["easy", "moderate", "hard"]] = None, tags: Optional[list[str]] = None,
        include_examples: Optional[bool] = None, include_archived: Optional[bool] = None, limit: Optional[int] = None,
    ) -> dict:
        """Search the athlete's reusable workout templates. Built-in examples are structural
        illustrations, excluded unless include_examples=true; never prescribe from them."""
        return await _call(
            "search_workout_library", query=query, workout_type=workout_type, session_type=session_type, difficulty=difficulty,
            tags=tags, include_examples=include_examples, include_archived=include_archived, limit=limit,
        )

    @mcp.tool()
    async def get_workout_template(id: int) -> dict:
        """One template with its structure and computed totals (duration only when it can be known)."""
        return await _call("get_workout_template", id=id)

    @mcp.tool()
    async def create_workout_template(
        name: str, workout_type: WorkoutType, description: Optional[str] = None, session_type: Optional[str] = None,
        purpose: Optional[str] = None, difficulty: Optional[Literal["easy", "moderate", "hard"]] = None,
        target_zone: Optional[Zone] = None, tags: Optional[list[str]] = None, structure: Optional[dict] = None,
        confirm: Optional[bool] = None,
    ) -> dict:
        """Create a workout template (not a workout, not a prescription). Previews unless
        confirm=true — set that only after the athlete confirms the preview."""
        return await _call(
            "create_workout_template", name=name, workout_type=workout_type, description=description, session_type=session_type,
            purpose=purpose, difficulty=difficulty, target_zone=target_zone, tags=tags, structure=structure, confirm=confirm,
        )

    @mcp.tool()
    async def update_workout_template(
        id: int, name: Optional[str] = None, description: Optional[str] = None, workout_type: Optional[WorkoutType] = None,
        session_type: Optional[str] = None, purpose: Optional[str] = None, difficulty: Optional[Literal["easy", "moderate", "hard"]] = None,
        target_zone: Optional[Zone] = None, tags: Optional[list[str]] = None, structure: Optional[dict] = None,
        archived: Optional[bool] = None, confirm: Optional[bool] = None,
    ) -> dict:
        """Change or archive a template (built-in examples are read-only). Previews each change
        unless confirm=true. Sessions already scheduled from it are unaffected."""
        return await _call(
            "update_workout_template", id=id, name=name, description=description, workout_type=workout_type, session_type=session_type,
            purpose=purpose, difficulty=difficulty, target_zone=target_zone, tags=tags, structure=structure, archived=archived, confirm=confirm,
        )

    @mcp.tool()
    async def get_technique_notes(
        workout_id: Optional[int] = None, piece_id: Optional[int] = None, date: Optional[str] = None,
        category: Optional[Category] = None, from_: Optional[str] = None, to: Optional[str] = None, limit: Optional[int] = None,
    ) -> dict:
        """Technique notes (the athlete's own words). Private notes are returned only to the
        athlete's own assistant, never to a coach. Catch can't measure technique quality, so
        don't score or rate technique from these notes or from stroke data."""
        return await _call(
            "get_technique_notes", workout_id=workout_id, piece_id=piece_id, date=date, category=category,
            **{"from": from_, "to": to}, limit=limit,
        )

    @mcp.tool()
    async def add_technique_note(
        category: Category, text: str, workout_id: Optional[int] = None, piece_id: Optional[int] = None,
        date: Optional[str] = None, visibility: Optional[Literal["private", "coach"]] = None,
        media: Optional[list[dict]] = None, confirm: Optional[bool] = None,
    ) -> dict:
        """Save a technique note in the athlete's own words (private by default). Previews unless
        confirm=true. Never add a quality judgement the athlete didn't state."""
        return await _call(
            "add_technique_note", category=category, text=text, workout_id=workout_id, piece_id=piece_id, date=date,
            visibility=visibility, media=media, confirm=confirm,
        )

    @mcp.tool()
    async def get_coach_feedback(
        coach: Optional[str] = None, category: Optional[Focus] = None, from_: Optional[str] = None, to: Optional[str] = None,
        workout_id: Optional[int] = None, event_id: Optional[int] = None, limit: Optional[int] = None,
    ) -> dict:
        """Coach feedback entries, newest first, with author, edit status and the athlete's
        response. Private entries never reach a coach."""
        return await _call(
            "get_coach_feedback", coach=coach, category=category, **{"from": from_, "to": to},
            workout_id=workout_id, event_id=event_id, limit=limit,
        )

    @mcp.tool()
    async def add_coach_feedback(
        text: str, date: Optional[str] = None, workout_id: Optional[int] = None, workout_date: Optional[str] = None,
        event_id: Optional[int] = None, planned_id: Optional[int] = None, focus_areas: Optional[list[Focus]] = None,
        visibility: Optional[Literal["private", "shared"]] = None, coach_name: Optional[str] = None, confirm: Optional[bool] = None,
    ) -> dict:
        """Record feedback. With a coach token it is saved, shared, under that coach's name; the
        athlete uses it to log feedback they received (coach_name). Previews unless confirm=true."""
        return await _call(
            "add_coach_feedback", text=text, date=date, workout_id=workout_id, workout_date=workout_date, event_id=event_id,
            planned_id=planned_id, focus_areas=focus_areas, visibility=visibility, coach_name=coach_name, confirm=confirm,
        )

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

    @mcp.prompt()
    def training_review() -> str:
        """A training-intelligence review with the coach."""
        return (
            "Give me a training review: call get_training_profile, then "
            "get_performance_trends, get_training_distribution, get_training_consistency, "
            "get_training_insights, and get_recommendations in that order. Summarize current "
            "phase, trajectory, consistency, one strength and one area to investigate, and "
            "any active recommendation — naming the confidence level and what data it rests "
            "on, never stating more certainty than the data supports."
        )

    return mcp
