"""Session 36: the DB-facing half of the Performance Lab (rules in catch/analytics/performance_lab.py).

Reads are bounded: the date range is capped, sessions come from the per-day index (`canonical_in_days`), and the per-stroke
comparison is one aggregate query grouped by recording and rounded rate — never every stroke loaded into memory."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from catch.analytics import performance_lab as lab
from catch.core import localtime
from catch.core.models import Activity, CanonicalActivity, Stroke
from catch.sync import records as rec
from catch.sync.activity_days import canonical_in_days

MAX_RANGE_DAYS = 3 * 366
_ID_CHUNK = 500


def clamp_range(session: Session, start: Optional[date], end: Optional[date]) -> tuple[date, date]:
    end = end or localtime.today(session)
    start = start or end - timedelta(days=365)
    if start > end:
        start, end = end, start
    if (end - start).days > MAX_RANGE_DAYS:
        start = end - timedelta(days=MAX_RANGE_DAYS)
    return start, end


def _excluded(c: CanonicalActivity) -> bool:
    return bool(json.loads(c.overrides_json or "{}").get("exclude_from_totals"))


def steady_rowing_sessions(session: Session, start: date, end: date) -> list[dict]:
    """Continuous rowing-erg sessions of at least 10 minutes with both an average power and an average heart rate. A workout whose
    Concept2 result is an interval session is left out: its averages mix work and rest."""
    rows = [c for c in canonical_in_days(session, start, end) if c.category == "erg" and c.sport_family == "rowing" and not _excluded(c)]
    rows = [c for c in rows if c.avg_power and c.avg_hr and (c.duration or 0) >= 600]
    if not rows:
        return []
    ids = [c.id for c in rows]
    c2 = session.exec(
        select(Activity.canonical_id, Activity.type, Activity.workout_type).where(Activity.canonical_id.in_(ids), Activity.source == "concept2")
    ).all()
    skip = {cid for cid, typ, wt in c2 if typ != "rower" or wt not in rec.CONTINUOUS_WORKOUT_TYPES}
    return [
        {"date": localtime.day_of(session, c), "avg_watts": c.avg_power, "avg_hr": c.avg_hr, "ref": f"/workouts/{c.id}"}
        for c in rows if c.id not in skip
    ]


def stroke_rate_rows(session: Session, start: date, end: date) -> list[dict]:
    """Per rowing-erg recording and 2-spm rate band: how many strokes and the sum of their splits."""
    canon = {c.id: c for c in canonical_in_days(session, start, end) if not _excluded(c)}
    if not canon:
        return []
    acts = session.exec(
        select(Activity.id, Activity.canonical_id).where(Activity.canonical_id.in_(list(canon)), Activity.source == "concept2", Activity.type == "rower")
    ).all()
    day_of_act = {aid: localtime.day_of(session, canon[cid]) for aid, cid in acts}
    out: list[dict] = []
    ids = list(day_of_act)
    rate = func.round(Stroke.stroke_rate)
    for i in range(0, len(ids), _ID_CHUNK):
        chunk = ids[i : i + _ID_CHUNK]
        q = (
            select(Stroke.activity_id, rate, func.count(), func.sum(Stroke.pace_500m))
            .where(
                Stroke.activity_id.in_(chunk), Stroke.stroke_rate.is_not(None), Stroke.pace_500m.is_not(None),
                Stroke.stroke_rate >= lab.RATE_RANGE[0], Stroke.stroke_rate <= lab.RATE_RANGE[1],
                Stroke.pace_500m >= 60, Stroke.pace_500m <= 300,
            )
            .group_by(Stroke.activity_id, rate)
        )
        for aid, r, n, total in session.exec(q).all():
            out.append({"session": aid, "date": day_of_act[aid], "band": lab.rate_band(float(r)), "strokes": int(n), "pace_sum": float(total or 0.0)})
    # Several rounded rates fall in one band: merge them per session.
    merged: dict[tuple, dict] = {}
    for r in out:
        k = (r["session"], r["band"])
        if k in merged:
            merged[k]["strokes"] += r["strokes"]
            merged[k]["pace_sum"] += r["pace_sum"]
        else:
            merged[k] = dict(r)
    return list(merged.values())


def hr_at_workload(session: Session, start: Optional[date] = None, end: Optional[date] = None) -> dict:
    start, end = clamp_range(session, start, end)
    split = lab.midpoint(start, end)
    sessions = steady_rowing_sessions(session, start, end)
    return {"from": start, "to": end, "split_date": split, "sessions": len(sessions), "bands": lab.hr_at_workload(sessions, split),
            "min_sessions": lab.MIN_SESSIONS}


def split_by_rate(session: Session, start: Optional[date] = None, end: Optional[date] = None) -> dict:
    start, end = clamp_range(session, start, end)
    split = lab.midpoint(start, end)
    rows = stroke_rate_rows(session, start, end)
    return {"from": start, "to": end, "split_date": split, "bands": lab.split_by_rate(rows, split),
            "min_strokes": lab.MIN_STROKES, "min_sessions": lab.MIN_SESSIONS}


def progression(session: Session, modality: str = "rowing_erg", start: Optional[date] = None, end: Optional[date] = None) -> dict:
    start, end = clamp_range(session, start, end)
    cands = []
    for c in rec.candidates(session, modality):
        if c["date"] is None or not (start <= c["date"] <= end):
            continue
        ref = f"/tests/piece/{c['piece_id']}" if c.get("piece_id") else f"/workouts/{c['canonical_id']}" if c["canonical_id"] is not None else None
        cands.append({**c, "ref": ref})
    distances = rec.ROWING_DISTANCES_M if modality == "rowing_erg" else rec.BIKE_DISTANCES_M
    return {"from": start, "to": end, "modality": modality, "split_m": rec.SPLIT_M[modality],
            "series": lab.progression(cands, distances, rec.DURATIONS_S, rec.SPLIT_M[modality])}

