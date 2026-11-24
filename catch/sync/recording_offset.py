"""Session 36 follow-up: the DB half of lining up a PM5's strokes with another device's heart-rate chart (rules in
catch/analytics/recording_offset.py).

The confirmed offset lives in the workout's overrides as `erg_alignment = {erg, watch, offset_s}`, keyed by the two recording
ids so that a merge, split or re-pick of the heart-rate recording quietly retires it instead of applying it to another pair.
Nothing here links charts by itself: `suggest` proposes, the athlete confirms (`set_offset`) or clears it."""

from __future__ import annotations

import json
from typing import Optional

from sqlmodel import Session, select

from catch.analytics import recording_offset as ro
from catch.analytics.samples_codec import unpack_series
from catch.core.models import Activity, ActivitySamples, CanonicalActivity, Stroke
from catch.sync.canonical import pick_hr
from catch.sync.piece_intervals import _concept2_interval_defs

MAX_OFFSET_S = 6 * 3600


class AlignmentError(ValueError):
    pass


def _pair(session: Session, canonical: CanonicalActivity) -> tuple[Optional[Activity], Optional[Activity]]:
    """(the Concept2 recording whose strokes the erg chart draws, the recording the heart-rate chart draws) — the same picks the
    workout page and `/samples` make."""
    members = list(session.exec(select(Activity).where(Activity.canonical_id == canonical.id).order_by(Activity.id)).all())
    erg = next((m for m in members if m.source == "concept2"), None)
    _, _, hr = pick_hr(members)
    return erg, (hr or (members[0] if members else None))


def erg_wall_times(erg: Activity, strokes: list[dict]) -> Optional[list[float]]:
    """`analytics.recording_offset.wall_times` with this result's own intervals, splits and workout type."""
    try:
        workout = json.loads(erg.intervals_json) if erg.intervals_json else {}
    except ValueError:
        workout = {}
    splits = workout.get("splits") if isinstance(workout, dict) and isinstance(workout.get("splits"), list) else None
    return ro.wall_times(strokes, _concept2_interval_defs(erg), split_defs=splits, interval_workout="interval" in (erg.workout_type or "").lower())


def _overrides(canonical: CanonicalActivity) -> dict:
    try:
        return json.loads(canonical.overrides_json or "{}")
    except ValueError:
        return {}


def _strokes(session: Session, erg_id: int) -> list[dict]:
    rows = session.exec(
        select(Stroke.interval_index, Stroke.t, Stroke.hr, Stroke.stroke_rate).where(Stroke.activity_id == erg_id).order_by(Stroke.seq)
    ).all()
    return [{"interval_index": r[0], "t": r[1], "hr": r[2], "stroke_rate": r[3]} for r in rows]


def state(session: Session, canonical: CanonicalActivity) -> dict:
    erg, watch = _pair(session, canonical)
    base = {"erg_activity_id": erg.id if erg else None, "watch_activity_id": watch.id if watch else None, "offset_s": None}
    if erg is None or watch is None:
        return {**base, "state": "no_pair"}
    if canonical.merge_mode == "combined":
        return {**base, "state": "combined"}
    if erg.id == watch.id:
        return {**base, "state": "same_recording", "offset_s": 0}
    saved = _overrides(canonical).get("erg_alignment") or {}
    indices = session.exec(select(Stroke.interval_index).where(Stroke.activity_id == erg.id).distinct()).all()
    wall_known = erg_wall_times(erg, [{"t": 0.0, "interval_index": i} for i in indices] or [{"t": 0.0}]) is not None
    if saved.get("erg") == erg.id and saved.get("watch") == watch.id and isinstance(saved.get("offset_s"), int):
        return {**base, "state": "confirmed", "offset_s": saved["offset_s"], "wall_time_known": wall_known}
    return {**base, "state": "not_linked", "wall_time_known": wall_known}


def suggest(session: Session, canonical: CanonicalActivity) -> dict:
    erg, watch = _pair(session, canonical)
    if erg is None or watch is None or erg.id == watch.id or canonical.merge_mode == "combined":
        return {"offset_s": None, "reason": "There is no second recording to line up."}
    strokes = _strokes(session, erg.id)
    walls = erg_wall_times(erg, strokes) if strokes else None
    if not walls:
        return {"offset_s": None, "reason": "The erg recording's rests aren't known, so its strokes can't be placed in time."}
    samples = session.get(ActivitySamples, watch.id)
    if samples is None:
        return {"offset_s": None, "reason": "The other recording has no second-by-second data."}
    n = samples.n_samples
    length = int(walls[-1]) + 1
    centre = int((erg.start - watch.start).total_seconds()) if erg.start and watch.start else 0
    attempts = []
    watch_hr = unpack_series(samples.hr_blob, n)
    if any(s["hr"] for s in strokes) and any(v is not None for v in watch_hr):
        erg_hr = ro.resample(walls, [s["hr"] or None for s in strokes], length)
        attempts.append(ro.suggest_offset(watch_hr, erg_hr, centre_s=centre, signal="heart_rate"))
    watch_cad = unpack_series(samples.cadence_blob, n)
    if any(s["stroke_rate"] for s in strokes) and any(v is not None for v in watch_cad):
        erg_rate = ro.resample(walls, [s["stroke_rate"] for s in strokes], length)
        attempts.append(ro.suggest_offset(watch_cad, erg_rate, centre_s=centre, signal="stroke_rate"))
    found = [a for a in attempts if a.get("offset_s") is not None]
    if found:
        return max(found, key=lambda a: a["r"])
    if attempts:
        return attempts[0]
    return {"offset_s": None, "reason": "The two recordings share neither heart rate nor stroke rate."}


def set_offset(session: Session, canonical: CanonicalActivity, offset_s: int) -> dict:
    current = state(session, canonical)
    if current["state"] not in ("not_linked", "confirmed"):
        raise AlignmentError("These charts don't need an offset.")
    if not current.get("wall_time_known"):
        raise AlignmentError("The erg recording's rests aren't known, so its strokes can't be placed in time.")
    if abs(offset_s) > MAX_OFFSET_S:
        raise AlignmentError("An offset can be at most six hours.")
    ov = _overrides(canonical)
    ov["erg_alignment"] = {"erg": current["erg_activity_id"], "watch": current["watch_activity_id"], "offset_s": int(offset_s)}
    canonical.overrides_json = json.dumps(ov)
    session.add(canonical)
    session.commit()
    return state(session, canonical)


def clear(session: Session, canonical: CanonicalActivity) -> dict:
    ov = _overrides(canonical)
    if ov.pop("erg_alignment", None) is not None:
        canonical.overrides_json = json.dumps(ov)
        session.add(canonical)
        session.commit()
    return state(session, canonical)
