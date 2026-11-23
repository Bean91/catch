"""Session 36: goal progress. Pure, no I/O (catch/sync/goals.py gathers the data).

A goal is free text (`text`, the coach-memory goal since session 5) or measurable. Progress is always computed from completed
workouts and records when read — never stored — so it can't drift from the training history.

  * `distance_total`  — metres in the window (optionally one sport).
  * `workout_count`   — sessions in the window.
  * `weekly_volume`   — minutes per week; each whole or current week inside the window is compared with the target.
  * `frequency`       — sessions per week, the same way.
  * `target_split`    — a /500 m split (or /1000 m on a bike) over a standard distance, reached by any qualifying effort in the window.
  * `target_power`    — average watts held over an effort of at least `min_duration_s`, in the window.

Deliberately absent: streaks, "days in a row", and any prompt to make up a shortfall. Progress is capped at 100 %; a weekly goal
reports how many weeks reached the target, never a running debt.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

GOAL_KINDS = ("text", "distance_total", "workout_count", "weekly_volume", "frequency", "target_split", "target_power")
SPORTS = ("rowing", "cycling", "running", "strength", "other")
UNITS = {
    "distance_total": "m", "workout_count": "sessions", "weekly_volume": "min/week", "frequency": "sessions/week",
    "target_split": "s", "target_power": "W",
}
MEASURABLE = tuple(k for k in GOAL_KINDS if k != "text")


def validate(fields: dict) -> None:
    kind = fields.get("kind") or "text"
    if kind not in GOAL_KINDS:
        raise ValueError(f"kind must be one of {list(GOAL_KINDS)}")
    text = fields.get("text")
    if text is not None and (not isinstance(text, str) or not text.strip() or len(text) > 500):
        raise ValueError("text must be a short description (up to 500 characters)")
    sport = fields.get("sport")
    if sport is not None and sport not in SPORTS:
        raise ValueError(f"sport must be one of {list(SPORTS)}")
    start, end = fields.get("start_date"), fields.get("end_date")
    if start and end and end < start:
        raise ValueError("end_date can't be before start_date")
    if kind in MEASURABLE:
        tv = fields.get("target_value")
        if tv is None or isinstance(tv, bool) or not isinstance(tv, (int, float)) or tv <= 0:
            raise ValueError("A measurable goal needs a positive target_value")
        if not start or not end:
            raise ValueError("A measurable goal needs a start_date and an end_date")
        if kind == "target_split":
            if not (30 <= tv <= 600):
                raise ValueError("A split target is seconds per 500 m (or per 1000 m on a bike), e.g. 105 for 1:45.0")
            dist = (fields.get("params") or {}).get("distance_m")
            if not isinstance(dist, (int, float)) or dist <= 0:
                raise ValueError("A split goal names the distance it is over (params.distance_m)")
        if kind == "target_power":
            if tv > 2000:
                raise ValueError("A power target is in watts (up to 2000)")
            secs = (fields.get("params") or {}).get("min_duration_s")
            if not isinstance(secs, (int, float)) or secs <= 0:
                raise ValueError("A power goal names how long the effort lasts (params.min_duration_s)")
        if kind in ("weekly_volume", "frequency") and (end - start).days < 6:
            raise ValueError("A weekly goal needs a window of at least a week")


def _weeks(start: date, end: date, today: date) -> list[date]:
    first = start - timedelta(days=start.weekday())
    last = min(end, today)
    out = []
    w = first
    while w <= last:
        out.append(w)
        w += timedelta(days=7)
    return out


def progress(goal: dict, workouts: list[dict], efforts: list[dict], today: date) -> dict:
    """`goal`: the row's fields. `workouts`: completed workouts in the window `{date, minutes, distance_m, sport_family, ref}` (already
    filtered to the goal's sport and with excluded workouts left out). `efforts`: record candidates in the window
    `{date, distance_m, duration_s, pace_s, avg_watts, ref}`. Returns a dict the screen renders as is."""
    kind = goal.get("kind") or "text"
    start, end = goal.get("start_date"), goal.get("end_date") or goal.get("target_date")
    state = "active"
    if goal.get("status") in ("done", "abandoned"):
        state = goal["status"]
    elif end is not None and end < today:
        state = "ended"
    base = {
        "kind": kind, "unit": UNITS.get(kind), "target": goal.get("target_value"), "state": state,
        "days_left": (end - today).days if end is not None and end >= today else None,
    }
    if kind == "text" or start is None or end is None:
        return {**base, "measurable": False}

    target = float(goal["target_value"])
    in_window = [w for w in workouts if start <= w["date"] <= end]
    if kind in ("distance_total", "workout_count"):
        current = sum(w["distance_m"] or 0.0 for w in in_window) if kind == "distance_total" else float(len(in_window))
        return {**base, "measurable": True, "current": current, "pct": min(current / target * 100.0, 100.0),
                "achieved": current >= target, "contributors": [w["ref"] for w in in_window][-10:]}

    if kind in ("weekly_volume", "frequency"):
        weeks = []
        for w in _weeks(start, end, today):
            wk = [x for x in in_window if w <= x["date"] <= w + timedelta(days=6)]
            value = sum(x["minutes"] or 0.0 for x in wk) if kind == "weekly_volume" else float(len(wk))
            weeks.append({"week_start": w, "value": value, "met": value >= target, "current": w <= today <= w + timedelta(days=6)})
        finished = [w for w in weeks if not w["current"]]
        met = sum(1 for w in finished if w["met"])
        this_week = next((w for w in weeks if w["current"]), None)
        return {**base, "measurable": True, "weeks": weeks, "weeks_met": met, "weeks_finished": len(finished),
                "current": this_week["value"] if this_week else None,
                "pct": min((this_week["value"] / target * 100.0) if this_week else 0.0, 100.0),
                "achieved": bool(finished) and met == len(finished) and state != "active"}

    params = goal.get("params") or {}
    if kind == "target_split":
        dist = float(params["distance_m"])
        tol = max(25.0, dist * 0.02)
        cands = [e for e in efforts if start <= e["date"] <= end and e.get("pace_s") and abs(e["distance_m"] - dist) <= tol]
        best = min(cands, key=lambda e: e["pace_s"]) if cands else None
        reached = next((e for e in sorted(cands, key=lambda e: e["date"]) if e["pace_s"] <= target), None)
        return {**base, "measurable": True, "current": best["pace_s"] if best else None, "best_ref": best["ref"] if best else None,
                "gap": (best["pace_s"] - target) if best else None, "achieved": reached is not None,
                "achieved_on": reached["date"] if reached else None, "achieved_ref": reached["ref"] if reached else None,
                "pct": 100.0 if reached else None, "efforts": len(cands)}

    secs = float(params["min_duration_s"])
    cands = [e for e in efforts if start <= e["date"] <= end and e.get("avg_watts") and e["duration_s"] >= secs - 1]
    best = max(cands, key=lambda e: e["avg_watts"]) if cands else None
    reached = next((e for e in sorted(cands, key=lambda e: e["date"]) if e["avg_watts"] >= target), None)
    return {**base, "measurable": True, "current": best["avg_watts"] if best else None, "best_ref": best["ref"] if best else None,
            "gap": (target - best["avg_watts"]) if best else None, "achieved": reached is not None,
            "achieved_on": reached["date"] if reached else None, "achieved_ref": reached["ref"] if reached else None,
            "pct": min(best["avg_watts"] / target * 100.0, 100.0) if best else None, "efforts": len(cands)}


def describe(goal: dict) -> Optional[str]:
    """A plain sentence for a measurable goal, used as its text when none was typed."""
    kind, tv, p = goal.get("kind"), goal.get("target_value"), goal.get("params") or {}
    if kind == "distance_total":
        return f"{tv / 1000:g} km"
    if kind == "workout_count":
        return f"{tv:g} sessions"
    if kind == "weekly_volume":
        return f"{tv:g} minutes a week"
    if kind == "frequency":
        return f"{tv:g} sessions a week"
    if kind == "target_split":
        m, s = divmod(float(tv), 60)
        return f"{int(p.get('distance_m', 0)):,} m at {int(m)}:{s:04.1f} split"
    if kind == "target_power":
        return f"{tv:g} W for {int(p.get('min_duration_s', 0)) // 60} min"
    return None
