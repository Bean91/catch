"""Session 36: goals — the one service for the Goals page, the REST routes and the coach's goal tools (rules in
catch/analytics/goals.py). Every function is scoped to the signed-in owner by the tenant hooks; another owner's goal is not found."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from catch.analytics import goals as g
from catch.core import localtime
from catch.core.models import DailyScore, Goal
from catch.sync import records as rec
from catch.sync.activity_days import canonical_in_days

FIELDS = ("text", "kind", "sport", "target_value", "unit", "start_date", "end_date", "target_date", "status", "params")
STATUSES = ("active", "done", "abandoned")


class GoalError(ValueError):
    pass


class NotFound(LookupError):
    pass


def _coerce(fields: dict) -> dict:
    out = {k: v for k, v in fields.items() if k in FIELDS}
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise GoalError(f"Unknown goal field(s): {sorted(unknown)}")
    for k in ("start_date", "end_date", "target_date"):
        if isinstance(out.get(k), str):
            try:
                out[k] = date.fromisoformat(out[k])
            except ValueError as exc:
                raise GoalError(f"{k} must be a date (YYYY-MM-DD)") from exc
    if "status" in out and out["status"] not in STATUSES:
        raise GoalError(f"status must be one of {list(STATUSES)}")
    if "params" in out and out["params"] is not None and not isinstance(out["params"], dict):
        raise GoalError("params must be an object")
    return out


def _row_fields(row: Goal) -> dict:
    return {
        "text": row.text, "kind": row.kind or "text", "sport": row.sport, "target_value": row.target_value, "unit": row.unit,
        "start_date": row.start_date, "end_date": row.end_date, "target_date": row.target_date, "status": row.status,
        "params": json.loads(row.params_json) if row.params_json else None,
    }


def _get(session: Session, goal_id: int) -> Goal:
    row = session.get(Goal, goal_id)
    if row is None:
        raise NotFound(f"No goal with id {goal_id}")
    return row


def _apply(row: Goal, merged: dict) -> None:
    row.text = merged["text"]
    row.kind = None if merged.get("kind") in (None, "text") else merged["kind"]
    row.sport = merged.get("sport")
    row.target_value = merged.get("target_value")
    row.unit = g.UNITS.get(merged.get("kind") or "text") if merged.get("kind") not in (None, "text") else None
    row.start_date = merged.get("start_date")
    row.end_date = merged.get("end_date")
    row.target_date = merged.get("target_date") or merged.get("end_date")
    row.params_json = json.dumps(merged["params"]) if merged.get("params") else None
    new_status = merged.get("status") or "active"
    if new_status == "done" and row.status != "done":
        row.completed_at = datetime.now(timezone.utc)
    elif new_status != "done":
        row.completed_at = None
    row.status = new_status


def _validated(merged: dict) -> dict:
    if not merged.get("text"):
        merged["text"] = g.describe(merged) or ""
    try:
        g.validate(merged)
    except ValueError as exc:
        raise GoalError(str(exc)) from exc
    return merged


def preview(session: Session, fields: dict, goal_id: Optional[int] = None) -> dict:
    """Exactly the validation the write runs, writing nothing — for the coach's preview step."""
    clean = _coerce(fields)
    if goal_id is not None:
        current = _row_fields(_get(session, goal_id))
        merged = _validated({**current, **clean})
        return {"goal_id": goal_id, "changes": {k: {"from": _ser(current.get(k)), "to": _ser(v)} for k, v in clean.items() if current.get(k) != v}}
    merged = _validated({"status": "active", **clean})
    return {"goal": {k: _ser(v) for k, v in merged.items() if v is not None}}


def _ser(v: Any) -> Any:
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def create(session: Session, fields: dict) -> Goal:
    merged = _validated({"status": "active", **_coerce(fields)})
    row = Goal(text=merged["text"])
    _apply(row, merged)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update(session: Session, goal_id: int, fields: dict) -> Goal:
    """A partial update: only the fields given change (session 36 — the coach's `set_goal` used to reset the others)."""
    row = _get(session, goal_id)
    merged = _validated({**_row_fields(row), **_coerce(fields)})
    _apply(row, merged)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete(session: Session, goal_id: int) -> None:
    row = _get(session, goal_id)
    session.delete(row)
    session.commit()


def _workouts(session: Session, start: date, end: date, sport: Optional[str]) -> list[dict]:
    out = []
    for c in canonical_in_days(session, start, end):
        if c.start is None or json.loads(c.overrides_json or "{}").get("exclude_from_totals"):
            continue
        if sport and c.sport_family != sport:
            continue
        out.append({"date": localtime.day_of(session, c), "minutes": (c.duration or 0.0) / 60.0, "distance_m": c.distance,
                    "sport_family": c.sport_family, "ref": f"/workouts/{c.id}"})
    return out


def _efforts(session: Session, sport: Optional[str]) -> list[dict]:
    modality = "bike" if sport == "cycling" else "rowing_erg"
    out = []
    for c in rec.candidates(session, modality):
        if c["date"] is None:
            continue
        ref = f"/tests/piece/{c['piece_id']}" if c.get("piece_id") else f"/workouts/{c['canonical_id']}" if c["canonical_id"] else None
        pace = c["duration_s"] / c["distance_m"] * rec.SPLIT_M[modality] if c["distance_m"] else None
        out.append({**c, "pace_s": pace, "ref": ref})
    return out


def goal_dict(session: Session, row: Goal, today: date, *, efforts_cache: dict | None = None, recovery_band: Optional[str] = None) -> dict:
    fields = _row_fields(row)
    out = {"id": row.id, "ref": f"goal:{row.id}", **{k: _ser(v) for k, v in fields.items()}, "created_at": row.created_at,
           "completed_at": row.completed_at}
    kind = fields["kind"]
    start, end = fields["start_date"], fields["end_date"] or fields["target_date"]
    workouts: list[dict] = []
    efforts: list[dict] = []
    if kind in ("distance_total", "workout_count", "weekly_volume", "frequency") and start and end:
        workouts = _workouts(session, start, min(end, today), fields["sport"])
    if kind in ("target_split", "target_power"):
        key = fields["sport"] or "rowing"
        if efforts_cache is not None and key in efforts_cache:
            efforts = efforts_cache[key]
        else:
            efforts = _efforts(session, fields["sport"])
            if efforts_cache is not None:
                efforts_cache[key] = efforts
    out["progress"] = g.progress(fields, workouts, efforts, today)
    if kind in ("weekly_volume", "frequency"):
        # Context, never a nudge: a weekly target is a week's total, and today's recovery is shown beside it.
        out["recovery_today"] = recovery_band
    return out


def _recovery_band(session: Session, today: date) -> Optional[str]:
    row = session.exec(select(DailyScore).where(DailyScore.date == today)).first()
    if row is None or not row.recovery_json:
        return None
    try:
        return (json.loads(row.recovery_json) or {}).get("band")
    except ValueError:
        return None


def list_goals(session: Session, view: Optional[str] = None) -> list[dict]:
    """`view`: "active" (still running), "history" (done, set aside, or its window has passed) or everything."""
    today = localtime.today(session)
    rows = session.exec(select(Goal).order_by(Goal.created_at.desc())).all()
    cache: dict = {}
    band = _recovery_band(session, today)
    out = [goal_dict(session, r, today, efforts_cache=cache, recovery_band=band) for r in rows]
    if view == "active":
        return [x for x in out if x["progress"]["state"] == "active"]
    if view == "history":
        return [x for x in out if x["progress"]["state"] != "active"]
    return out
