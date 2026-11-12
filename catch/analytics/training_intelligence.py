from __future__ import annotations

"""Session 18 (see PLAN.md): training intelligence & recommendations. Pure, no I/O — mirrors
every other analytics/*.py module's contract. The governing rule for this whole module: never
re-derive what already exists. Equivalent-piece trend comparison reuses catch.analytics.
erg_test's TEST_SPECS/project_time directly rather than inventing a new tolerance/bucketing
scheme — callers pass rows already grouped by a confirmed test_type/piece_type (from
catch.sync.erg_test.list_tests), so there is no fuzzy re-classification to get wrong here.

Every recommendation body is built from a wording template selected by confidence tier
(`_apply_hedge`), not free text, plus a narrow banned-phrase backstop (`_BANNED_PHRASES`) a
test checks directly — the structural guarantee (confidence never exceeds the weakest input,
low/medium always hedged) is what actually keeps this honest; the phrase list is a backstop,
not the mechanism."""

import statistics
from datetime import date

from catch.analytics.erg_test import TEST_SPECS, project_time

# Phrases that would overclaim certainty or contradict "never tell the athlete to ignore
# symptoms" if they ever slipped into a template. A backstop, not the honesty mechanism itself
# (see module docstring) — every real guarantee comes from the confidence-tier/suppression
# logic below, which a test exercises directly.
_BANNED_PHRASES = ("push through", "definitely", "guaranteed", "will improve")

_HEDGE_PREFIX = "Based on the data so far (not certain): "


def _apply_hedge(confidence: str, body: str) -> str:
    return (_HEDGE_PREFIX + body) if confidence in ("insufficient_data", "low", "medium") else body


def _check_banned_phrases(text: str) -> None:
    lowered = text.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lowered:
            raise AssertionError(f"banned phrase '{phrase}' in recommendation text: {text!r}")


# --- Confidence ----------------------------------------------------------------------------


def confidence_level(n_history_days: int, n_points: int, settings: dict) -> str:
    """insufficient_data / low / medium / high, gated by data completeness. The weaker of
    "how much wellness history exists" and "how many equivalent data points support this
    specific claim" caps the result — e.g. 90 days of wellness history but only 2 pieces of
    one test type never exceeds "low" for anything about that test type specifically."""
    ti = settings["training_intelligence"]
    if n_history_days < ti["data_quality_min_history_days"]:
        return "insufficient_data"
    if n_history_days >= ti["confidence_days_high"]:
        days_level = "high"
    elif n_history_days >= ti["confidence_days_medium"]:
        days_level = "medium"
    else:
        days_level = "low"
    if n_points >= ti["confidence_pieces_high"]:
        points_level = "high"
    elif n_points >= ti["data_quality_min_pieces_for_trend"]:
        points_level = "medium"
    else:
        points_level = "low"
    order = {"low": 0, "medium": 1, "high": 2}
    return days_level if order[days_level] <= order[points_level] else points_level


def _history_confidence(n_history_days: int, settings: dict) -> str:
    """The days-only half of `confidence_level`'s ladder, for a claim (e.g. a training
    suggestion) whose evidence is "how much wellness/load history backs today's reading," not
    a count of independent pieces/sessions — using `confidence_level`'s two-factor minimum
    here would conflate two unrelated kinds of evidence."""
    ti = settings["training_intelligence"]
    if n_history_days < ti["data_quality_min_history_days"]:
        return "insufficient_data"
    if n_history_days >= ti["confidence_days_high"]:
        return "high"
    if n_history_days >= ti["confidence_days_medium"]:
        return "medium"
    return "low"


# --- Performance trends: equivalent-piece comparison ----------------------------------------


def _lower_is_better(test_type: str) -> bool:
    return "distance_m" in TEST_SPECS.get(test_type, {})


def _metric_for_row(test_type: str, row: dict) -> float | None:
    """The one number compared across a bucket. Distance-based types (500m..6000m) compare
    pace (s/500m, lower is better) so pieces of slightly different exact distance within the
    same standard type are still on one scale. Duration-based types (30min_r20, 60min) have a
    fixed duration by definition, so the comparable number is distance covered (higher is
    better)."""
    spec = TEST_SPECS.get(test_type)
    if spec is None:
        return None
    if "distance_m" in spec:
        if not row.get("duration_s") or not row.get("distance_m"):
            return None
        return row["duration_s"] / row["distance_m"] * 500.0
    if not row.get("duration_s") or not row.get("distance_m"):
        return None
    return row["distance_m"]


def compare_equivalent_pieces(test_type: str, rows: list[dict], settings: dict) -> dict:
    """`rows`: one equivalence bucket's rows, all sharing this `test_type`, shaped like
    catch.sync.erg_test.list_tests' output (already confirmed/tagged — no re-classification
    happens here, so a row that matches no standard TEST_SPECS entry, e.g. a "custom" piece,
    is simply excluded by `_metric_for_row` returning None rather than guessed at). Returns
    best/typical(median)/recent, a trend (erg_test.project_time, called directly — never
    reimplemented), a rate-vs-pace note, and a drag-factor note when relevant."""
    ti = settings["training_intelligence"]
    lower_better = _lower_is_better(test_type)
    points = []
    for r in rows:
        metric = _metric_for_row(test_type, r)
        if metric is None or not r.get("date"):
            continue
        points.append({"date": date.fromisoformat(r["date"]), "value": metric, "row": r})
    points.sort(key=lambda p: p["date"])

    kind = "distance" if lower_better else "duration"
    if not points:
        return {
            "bucket_label": test_type,
            "kind": kind,
            "best": None,
            "typical": None,
            "recent": None,
            "trend": {"value": None, "range": None, "explanation": "No usable pieces of this type yet.", "inputs": []},
            "rate_note": None,
            "drag_note": None,
            "n_points": 0,
        }

    values = [p["value"] for p in points]
    best_value = min(values) if lower_better else max(values)
    best_point = next(p for p in points if p["value"] == best_value)
    typical_value = statistics.median(values)
    recent_point = points[-1]

    min_pieces = ti["data_quality_min_pieces_for_trend"]
    if len(points) < min_pieces:
        trend = {
            "value": None,
            "range": None,
            "explanation": f"Need at least {min_pieces} {test_type} pieces to project a trend; have {len(points)}.",
            "inputs": [{"date": p["date"].isoformat(), "value": p["value"]} for p in points],
        }
    else:
        trend = project_time([(p["date"], p["value"]) for p in points], recent_point["date"])

    recent_better = (recent_point["value"] < typical_value) if lower_better else (recent_point["value"] > typical_value)
    rate_note = None
    if recent_better:
        rates = [p["row"].get("avg_stroke_rate") for p in points if p["row"].get("avg_stroke_rate")]
        recent_rate = recent_point["row"].get("avg_stroke_rate")
        if rates and recent_rate:
            typical_rate = statistics.median(rates)
            rate_delta_pct = (recent_rate - typical_rate) / typical_rate if typical_rate else 0.0
            if rate_delta_pct > ti["rate_delta_material_pct"]:
                rate_note = (
                    "possible pacing/rate change — the recent result came at a materially "
                    "higher stroke rate than typical for this type, so it may not reflect a "
                    "fitness change alone."
                )
            else:
                rate_note = (
                    "likely real improvement — the recent result is faster/further at an "
                    "equal-or-lower stroke rate than typical for this type."
                )

    drag_note = None
    drags = [p["row"].get("drag_factor") for p in points if p["row"].get("drag_factor")]
    if len(set(drags)) > 1 and (max(drags) - min(drags)) >= 3:
        drag_note = (
            f"Drag factor varied across these pieces ({min(drags)}-{max(drags)}) — a higher "
            "setting makes the same effort look slower, annotated here rather than treated as "
            "a separate equivalence bucket."
        )

    def _point_out(p: dict) -> dict:
        return {"date": p["date"].isoformat(), "value": p["value"], "avg_stroke_rate": p["row"].get("avg_stroke_rate")}

    return {
        "bucket_label": test_type,
        "kind": kind,
        "best": _point_out(best_point),
        "typical": {"value": typical_value},
        "recent": _point_out(recent_point),
        "trend": trend,
        "rate_note": rate_note,
        "drag_note": drag_note,
        "n_points": len(points),
    }


# --- Training profile ------------------------------------------------------------------------


def compare_equivalent_intervals(signature: str, sessions: list[dict], n_history_days: int, settings: dict) -> dict:
    """Session 19: one equivalence bucket of interval pieces sharing a prescription signature
    (piece_intervals.interval_signature, e.g. "4x500m/r60"). Each session is
    {date: ISO str, summary: summarize_intervals' output}. The metric is the weighted average
    split (lower is faster) — comparable across distance- and time-prescribed work alike.
    Deliberately no project_time trend: that's built for standard test distances, and a handful
    of interval sessions doesn't support a projection. Confidence reuses the same ladder."""
    points = sorted(
        (
            {"date": s["date"], "value": s["summary"]["avg_split_s"], "avg_watts": s["summary"].get("avg_watts"), "avg_rate": s["summary"].get("avg_rate"), "avg_hr": s["summary"].get("avg_hr")}
            for s in sessions
            if s.get("summary") and s["summary"].get("avg_split_s")
        ),
        key=lambda p: p["date"],
    )
    base = {"bucket_label": signature, "n_points": len(points), "best": None, "typical": None, "recent": None, "delta_vs_typical_pct": None}
    if not points:
        return {**base, "confidence": "insufficient_data", "note": "No sessions with both distance and time recorded yet."}
    values = [p["value"] for p in points]
    best = min(points, key=lambda p: p["value"])
    typical = statistics.median(values)
    recent = points[-1]
    delta = (recent["value"] - typical) / typical * 100.0 if typical and len(points) > 1 else None
    return {
        **base,
        "best": best,
        "typical": {"value": typical},
        "recent": recent,
        "delta_vs_typical_pct": delta,
        "confidence": confidence_level(n_history_days, len(points), settings),
        "note": None if len(points) > 1 else "Only one session of this structure so far — nothing to compare against yet.",
    }


def _infer_phase(load: dict, next_event: dict | None) -> dict:
    # Taper only means something ahead of a genuinely important event — a training camp (no
    # priority set) or a C-priority race 10 days out isn't a reason to call this a taper
    # phase, matching catch/coach/memory.py's own next_a_race precedent of hard-filtering to
    # A-priority (loosened to A/B here, since a B race still reasonably earns a taper label).
    if (
        next_event
        and next_event.get("priority") in ("A", "B")
        and next_event.get("days_to_go") is not None
        and 0 <= next_event["days_to_go"] <= 14
    ):
        return {"value": "taper", "inferred": True, "explanation": f"{next_event['name']} is {next_event['days_to_go']} days away."}
    if load.get("value") is None:
        return {"value": None, "inferred": True, "explanation": "Not enough training-load history to infer a phase."}
    band = load["band"]
    if band == "undertraining":
        return {"value": "base", "inferred": True, "explanation": "Acute:chronic load is below the optimal range (undertraining band)."}
    return {
        "value": "build",
        "inferred": True,
        "explanation": f"Acute:chronic load is in the {band} band, read as a build phase (no other data distinguishes build from maintenance).",
    }


def training_profile(components: dict, settings: dict) -> dict:
    """Pure synthesis over pre-gathered dicts: `load`/`recovery`/`illness` (each in the exact
    shape catch.sync.scoring.recompute_scores already caches in DailyScore), `next_event`
    (catch.sync.erg_test.next_relevant_event's dict or None), `history_days`, `trend_buckets`
    (catch.sync.training_intelligence.gather_performance_trends' "buckets" list). Conflicting
    signals (e.g. load says undertraining while illness says "likely") are both named in the
    output, never collapsed into one invented verdict."""
    load = components.get("load") or {"value": None, "band": "insufficient_data"}
    recovery = components.get("recovery") or {"value": None, "band": "calibrating"}
    illness = components.get("illness") or {"level": "none", "explanation": ""}
    next_event = components.get("next_event")
    history_days = components.get("history_days", 0)
    trend_buckets = components.get("trend_buckets") or []

    max_points = max((b["n_points"] for b in trend_buckets), default=0)
    confidence = confidence_level(history_days, max_points, settings)

    phase = _infer_phase(load, next_event)

    strengths, weaknesses = [], []
    for b in trend_buckets:
        trend = b.get("trend") or {}
        if trend.get("value") is None or trend.get("slope_s_per_day") is None:
            continue
        lower_better = b["kind"] == "distance"
        improving = (trend["slope_s_per_day"] < 0) if lower_better else (trend["slope_s_per_day"] > 0)
        entry = {
            "text": f"{b['bucket_label']} is trending {'faster' if improving else 'slower'} over time.",
            "evidence": [{"label": "trend", "value": trend.get("explanation"), "source": b["bucket_label"]}],
        }
        (strengths if improving else weaknesses).append(entry)

    conflicts = []
    if load.get("band") == "undertraining" and illness.get("level") == "likely":
        conflicts.append(
            "Training load alone looks like undertraining, but the illness signal is 'likely' — "
            "these point in different directions and aren't collapsed into one verdict here."
        )

    trajectory = {
        "value": None,
        "range": None,
        "explanation": "No equivalent-piece trend data available yet." if not trend_buckets else "See performance trends for per-type trajectories.",
        "inputs": [],
    }
    best_trend = next((b["trend"] for b in trend_buckets if b.get("trend", {}).get("value") is not None), None)
    if best_trend is not None:
        trajectory = best_trend

    explanation_bits = [f"Confidence: {confidence}."]
    if conflicts:
        explanation_bits.extend(conflicts)
    if not strengths and not weaknesses and confidence == "insufficient_data":
        explanation_bits.append("Not enough history yet to identify strengths or areas to investigate.")

    return {
        "phase": phase,
        "performance_trajectory": trajectory,
        "consistency_summary": components.get("consistency_summary"),
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recovery_context": {"recovery": recovery, "load": load, "illness": illness},
        "confidence": confidence,
        "explanation": " ".join(explanation_bits),
        # "When available" (task's own phrase) — present as context, never factored into
        # phase/strengths/confidence above; {"logged": False} rather than silently absent
        # when the athlete hasn't logged anything, per the task's own data-honesty bar.
        "nutrition": components.get("nutrition", {"logged": False}),
        "daily_activity": components.get("daily_activity", {"logged": False}),
        "recent_note": components.get("recent_note"),
    }


# --- Recommendation evaluators ----------------------------------------------------------------
# Each returns None or {"rule_key","title","body","confidence","evidence":[{"label","value",
# "source"}]}. `context` is a plain dict assembled once per day by catch.sync.
# training_intelligence.generate_recommendations — see that function's docstring for the exact
# keys. None of these functions touch a Session; they only read the dict they're given.


def evaluate_data_quality_warning(context: dict, settings: dict) -> dict | None:
    ti = settings["training_intelligence"]
    history_days = context.get("history_days", 0)
    if history_days < ti["data_quality_min_history_days"]:
        body = _apply_hedge(
            "insufficient_data",
            f"Only {history_days} day(s) of wellness history exist — most analysis here needs "
            f"{ti['data_quality_min_history_days']}+ to establish a baseline. Treat anything "
            "else from this feature right now as provisional.",
        )
        return {
            "rule_key": "data_quality:insufficient_history",
            "title": "Not enough history yet",
            "body": body,
            "confidence": "insufficient_data",
            "evidence": [{"label": "history_days", "value": history_days, "source": "daily_wellness"}],
        }
    missing_hr_pct = context.get("missing_hr_pct")
    if missing_hr_pct is not None and missing_hr_pct >= ti["data_quality_missing_hr_pct_threshold"]:
        n = context.get("missing_hr_lookback_n", ti["data_quality_lookback_sessions"])
        body = _apply_hedge(
            "low",
            f"{missing_hr_pct:.0%} of the last {n} sessions had no usable heart-rate data — "
            "strain/load numbers for those sessions rest on a rougher estimate than usual.",
        )
        return {
            "rule_key": "data_quality:missing_hr",
            "title": "Heart-rate data is patchy",
            "body": body,
            "confidence": "low",
            "evidence": [{"label": "missing_hr_pct", "value": missing_hr_pct, "source": "canonical_activities"}],
        }
    return None


_PHYSIOLOGICAL_RECOVERY_METRICS = {"hrv", "resting_hr", "sleep"}


def _physiological_metrics_present(recovery: dict) -> set[str]:
    """Metric *names alone* aren't enough — recovery.py's own spread/baseline guards can leave
    a component in the list with `value: None` (e.g. a zero-spread 60d baseline), meaning it
    didn't actually contribute to the score despite being present. Only a component with a
    real, non-null value counts as genuine physiological evidence."""
    return {
        c.get("metric")
        for c in recovery.get("components", [])
        if c.get("metric") in _PHYSIOLOGICAL_RECOVERY_METRICS and c.get("value") is not None
    }


def _training_suggestion_suppressed(context: dict, settings: dict) -> str | None:
    ti = settings["training_intelligence"]
    illness_level = (context.get("illness") or {}).get("level", "none")
    if illness_level in ("watch", "likely"):
        return f"illness early-warning is '{illness_level}'"
    recovery = context.get("recovery") or {}
    # Requires an actual "green" reading, not merely "not red" — a yellow-band day (e.g. at
    # exactly recovery_suggestion_recovery_max) must never fire this alongside
    # evaluate_recovery_suggestion, which is itself suppressed below if it already fired this
    # run. See the suppression-matrix tests and the "insufficient confidence" test for why
    # "not red" alone let a real contradiction through.
    if recovery.get("band") != "green" or recovery.get("value") is None:
        return "recovery isn't a confirmed green reading"
    if not _physiological_metrics_present(recovery):
        return "recovery's green reading has no physiological component (hrv/resting_hr/sleep) behind it"
    niggle_days = context.get("niggle_streak_days", 0)
    if niggle_days >= settings.get("niggle_flag_min_days", 3):
        return f"a niggle has been logged for {niggle_days} days running"
    load = context.get("load") or {}
    if load.get("band") not in ("optimal", "undertraining"):
        return f"acute:chronic load band is '{load.get('band')}'"
    history_days = context.get("history_days", 0)
    if history_days < ti["data_quality_min_history_days"]:
        return f"only {history_days} day(s) of history — not enough to say load/recovery are genuinely fine"
    next_event = context.get("next_event")
    if next_event and next_event.get("days_to_go") is not None and 0 <= next_event["days_to_go"] <= ti["overload_suppress_near_event_days"]:
        return f"{next_event['name']} is only {next_event['days_to_go']} day(s) away"
    return None


def evaluate_training_suggestion(context: dict, settings: dict) -> dict | None:
    """Fires only the one safe, data-grounded case this session implements: this week's
    session count is below the athlete's own configured weekly target, AND there is positive
    evidence (not merely the absence of a red flag) that today's recovery/load genuinely
    support it — see `_training_suggestion_suppressed`. The caller (`generate_recommendations`)
    additionally never calls this in the same run as a fired `recovery_suggestion` or
    `overload_warning` — those two are the more specific, more urgent signals when they fire,
    and a training suggestion alongside either would be a direct contradiction."""
    suppress_reason = _training_suggestion_suppressed(context, settings)
    if suppress_reason is not None:
        return None
    sessions_this_week = context.get("sessions_this_week")
    target = settings["training_intelligence"]["target_sessions_per_week"]
    if sessions_this_week is None or sessions_this_week >= target:
        return None
    confidence = _history_confidence(context.get("history_days", 0), settings)
    if confidence == "insufficient_data":
        return None
    body = _apply_hedge(
        confidence,
        f"You're at {sessions_this_week} of your {target}-session weekly target, and today's "
        "recovery (a confirmed green reading) and training load don't show a reason to hold "
        "back — a reasonable day to add a session if you have the time.",
    )
    return {
        "rule_key": "training:add_session",
        "title": "Room for another session this week",
        "body": body,
        "confidence": confidence,
        "evidence": [
            {"label": "sessions_this_week", "value": sessions_this_week, "source": "canonical_activities"},
            {"label": "target_sessions_per_week", "value": target, "source": "settings"},
        ],
    }


def evaluate_recovery_suggestion(context: dict, settings: dict) -> dict | None:
    """Unlike `evaluate_training_suggestion`, this still fires at low confidence when the
    "green"/physiological-component bar isn't met — suggesting caution/rest is the safe
    direction regardless of evidence quality (the task's own "never encourage ignoring
    symptoms" cuts the other way: understating a plausible recovery concern is the risk here,
    not overstating one), so confidence only affects the wording hedge, never whether this
    fires at all."""
    recovery = context.get("recovery") or {}
    value = recovery.get("value")
    if value is None:
        return None
    ti = settings["training_intelligence"]
    if value > ti["recovery_suggestion_recovery_max"]:
        return None
    confidence = "high" if _physiological_metrics_present(recovery) else "low"
    body = _apply_hedge(
        confidence,
        f"Today's recovery score is {value:.0f} ({recovery.get('band')}) — a lighter session, "
        "extra sleep, or a rest day would be reasonable today. This isn't a diagnosis, just "
        "what today's recovery inputs show; don't ignore new or worsening symptoms regardless "
        "of what this score says.",
    )
    return {
        "rule_key": "recovery:low_score",
        "title": "Recovery is low today",
        "body": body,
        "confidence": confidence,
        "evidence": [{"label": "recovery", "value": value, "source": "daily_scores"}],
    }


def evaluate_overload_warning(context: dict, settings: dict) -> dict | None:
    """Independent of illness/recovery state — this is meant to fire exactly when load is
    already too high, not suppressed by the same conditions evaluate_training_suggestion
    checks. Requires sustained high ACR (overload_min_consecutive_days in a row), not one
    noisy day. Like evaluate_recovery_suggestion, this is a caution-direction recommendation
    (easing off), so it still fires at reduced confidence on short history rather than being
    suppressed outright — understating a real sustained-high-load reading would be the wrong
    kind of mistake here. Confidence caps at "high" only once the account has at least
    `load_chronic_days` of history, since the ACR figure itself (a 42-day EWMA by default)
    hasn't really converged before that."""
    ti = settings["training_intelligence"]
    acr_recent = context.get("acr_recent") or []
    n = ti["overload_min_consecutive_days"]
    if len(acr_recent) < n:
        return None
    window = acr_recent[-n:]
    if not all(v is not None and v >= ti["overload_acr_threshold"] for v in window):
        return None
    history_days = context.get("history_days", 0)
    confidence = "high" if history_days >= settings["load_chronic_days"] else "medium"
    body = _apply_hedge(
        confidence,
        f"Acute:chronic load has been at or above {ti['overload_acr_threshold']} for the last "
        f"{n} days (today {window[-1]:.2f}) — in the higher-injury-risk range by the usual "
        "acute:chronic framing. Consider easing volume or intensity for a few days.",
    )
    return {
        "rule_key": "overload:acr_sustained",
        "title": "Sustained high training load",
        "body": body,
        "confidence": confidence,
        "evidence": [{"label": f"acr_last_{n}_days", "value": window, "source": "daily_scores"}],
    }


def evaluate_planned_load_change(context: dict, settings: dict) -> dict | None:
    """Session 21 (see PLAN.md, docs/calendar.md): a caution-direction recommendation (type `plan_review`, deliberately not
    `overload_warning`: it says nothing about completed load), so like
    evaluate_overload_warning it is not suppressed by recovery/illness state — those make a
    big planned jump *more* worth a look. It only asks the athlete to review; the body text is
    already built (and hedged, or deferring to a coach on an approved phase) by
    catch.analytics.planning.workload_change_flags, from review flags the DB layer computed
    and passed in. Never reads a planned row itself."""
    flags = (context.get("planned_load") or {}).get("flags") or []
    increases = [f for f in flags if f["kind"] == "increase"]
    if not increases:
        return None
    flag = min(increases, key=lambda f: f["week_start"])
    return {
        "rule_key": "plan:load_change",
        "title": "A planned week is a big step up",
        "body": flag["message"],
        "confidence": _history_confidence(context.get("history_days", 0), settings),
        "evidence": [
            {"label": "week_start", "value": flag["week_start"].isoformat(), "source": "planned_workouts"},
            {"label": "planned_minutes", "value": round(flag["planned_minutes"]), "source": "planned_workouts"},
            {"label": flag["reference"], "value": round(flag["reference_minutes"]), "source": "canonical_activities"},
        ],
    }


# --- Insights --------------------------------------------------------------------------------


def training_insights(context: dict, settings: dict) -> list[dict]:
    """A fixed, enumerated set of pattern checks — never an open-ended search for "any
    correlation." Each has its own minimum-sample gate and is worded correlationally
    ("tends to", "has been"), never causally."""
    insights: list[dict] = []

    weekday_counts: dict[int, int] = context.get("weekday_counts") or {}
    total_sessions = sum(weekday_counts.values())
    if total_sessions >= 6:
        top_two = sorted(weekday_counts.values(), reverse=True)[:2]
        if sum(top_two) / total_sessions >= 0.6:
            names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            top_days = sorted(weekday_counts, key=lambda d: weekday_counts[d], reverse=True)[:2]
            insights.append(
                {
                    "id": "weekday_concentration",
                    "title": "Training is concentrated on a couple of weekdays",
                    "body": f"{sum(top_two)} of the last {total_sessions} sessions fall on {' and '.join(names[d] for d in top_days)}.",
                    "confidence": "medium",
                    "evidence": [{"label": "weekday_counts", "value": weekday_counts, "source": "canonical_activities"}],
                    "category": "consistency",
                }
            )

    recovery_pairs = context.get("recovery_after_high_strain") or []
    after = [p["after"] for p in recovery_pairs if p.get("after") is not None]
    # Gated on non-null after-values specifically, not total pairs — a pair with
    # after=None (no DailyScore the next day) carries no evidence at all; three pairs where
    # only one has a real value is one data point, not three.
    if len(after) >= 3:
        baseline = context.get("recovery_baseline_avg")
        if baseline is not None:
            avg_after = sum(after) / len(after)
            if avg_after < baseline - 5:
                insights.append(
                    {
                        "id": "recovery_after_high_strain",
                        "title": "Recovery tends to dip after high-strain days",
                        "body": f"The day after a high-strain session, recovery has averaged {avg_after:.0f} vs. a typical {baseline:.0f}.",
                        "confidence": "low",
                        "evidence": [{"label": "pairs", "value": recovery_pairs, "source": "daily_scores"}],
                        "category": "recovery",
                    }
                )

    fast_start_flags = context.get("fast_start_flags") or []
    if len(fast_start_flags) >= 3 and sum(fast_start_flags) / len(fast_start_flags) >= 0.6:
        insights.append(
            {
                "id": "recurring_fast_start",
                "title": "A recurring fast-start pacing pattern",
                "body": f"{sum(fast_start_flags)} of the last {len(fast_start_flags)} pieces started faster than even split and lost time later.",
                "confidence": "medium",
                "evidence": [{"label": "fast_start_flags", "value": fast_start_flags, "source": "pacing_analysis"}],
                "category": "pacing",
            }
        )

    zone_recent = context.get("zone_pct_recent") or {}
    zone_baseline = context.get("zone_pct_baseline") or {}
    if zone_recent and zone_baseline:
        hard_recent = zone_recent.get("AT", 0) + zone_recent.get("TR", 0) + zone_recent.get("AN", 0)
        hard_baseline = zone_baseline.get("AT", 0) + zone_baseline.get("TR", 0) + zone_baseline.get("AN", 0)
        # hard_baseline is already a fraction of total volume (0-1) — `max(hard_baseline, 1.0)`
        # was always 1.0 in practice, silently turning "≥30% relative drift" (what this
        # insight's own title/docs/analytics.md §26 claim) into "≥30 absolute percentage
        # points," a much harder bar that almost never fires. A small floor (not 1.0) restores
        # genuine relative-drift semantics without blowing up on a near-zero baseline.
        if hard_baseline and abs(hard_recent - hard_baseline) / max(hard_baseline, 0.05) >= 0.3:
            direction = "more" if hard_recent > hard_baseline else "less"
            insights.append(
                {
                    "id": "zone_polarization",
                    "title": f"Recent training skews toward {direction} high-intensity work",
                    "body": f"AT/TR/AN time is {hard_recent:.0%} of recent volume vs. a usual {hard_baseline:.0%}.",
                    "confidence": "low",
                    "evidence": [
                        {"label": "zone_pct_recent", "value": zone_recent, "source": "canonical_activities"},
                        {"label": "zone_pct_baseline", "value": zone_baseline, "source": "canonical_activities"},
                    ],
                    "category": "distribution",
                }
            )

    max_gap_days = context.get("max_gap_days")
    if max_gap_days is not None and max_gap_days >= 10:
        insights.append(
            {
                "id": "consistency_gap",
                "title": "An unusually long gap in training",
                "body": f"There was a {max_gap_days}-day stretch with no logged session in the lookback window.",
                "confidence": "high",
                "evidence": [{"label": "max_gap_days", "value": max_gap_days, "source": "canonical_activities"}],
                "category": "consistency",
            }
        )

    return insights
