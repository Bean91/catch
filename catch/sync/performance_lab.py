"""Session 36: the DB-facing half of the Performance Lab (rules in catch/analytics/performance_lab.py).

Reads are bounded: the date range is capped, sessions come from the per-day index (`canonical_in_days`), and the per-stroke
comparison is one aggregate query grouped by recording and rounded rate — never every stroke loaded into memory."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from catch.analytics import performance_lab as lab
from catch.analytics import stroke_summary as ss
from catch.core import localtime
from catch.core.models import Activity, CanonicalActivity
from catch.sync import records as rec
from catch.sync import stroke_summary
from catch.sync.activity_days import canonical_in_days

MAX_RANGE_DAYS = 3 * 366


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


def _rower_recordings(session: Session, start: date, end: date) -> dict[int, tuple[date, int]]:
    """`{Concept2 rowing recording id: (its workout's day, canonical id)}` for workouts in range not excluded from totals."""
    canon = {c.id: c for c in canonical_in_days(session, start, end) if not _excluded(c)}
    if not canon:
        return {}
    acts = session.exec(
        select(Activity.id, Activity.canonical_id).where(Activity.canonical_id.in_(list(canon)), Activity.source == "concept2", Activity.type == "rower")
    ).all()
    return {aid: (localtime.day_of(session, canon[cid]), cid) for aid, cid in acts}


def stroke_rate_rows(session: Session, start: date, end: date) -> list[dict]:
    """Per rowing-erg recording and 2-spm rate band: how many strokes and the sum of their splits — from each recording's cached
    stroke summary (catch/sync/stroke_summary.py), so a range read touches one row per recording, not every stroke."""
    recs = _rower_recordings(session, start, end)
    out: list[dict] = []
    for aid, summary in stroke_summary.summaries_for(session, list(recs)).items():
        for band, (n, total) in (summary.get("rate_bands") or {}).items():
            out.append({"session": aid, "date": recs[aid][0], "band": int(band), "strokes": int(n), "pace_sum": float(total)})
    return out


def power_curve(session: Session, start: Optional[date] = None, end: Optional[date] = None) -> dict:
    """The best time-weighted average power over standard durations, from each rowing-erg recording's strokes, for the range and
    each half of it. Watts are derived from each stroke's pace (Concept2's formula), never measured."""
    start, end = clamp_range(session, start, end)
    split = lab.midpoint(start, end)
    recs = _rower_recordings(session, start, end)
    entries = [
        {"curve": s.get("power_curve") or {}, "date": recs[aid][0], "ref": f"/workouts/{recs[aid][1]}"}
        for aid, s in stroke_summary.summaries_for(session, list(recs)).items()
    ]
    return {"from": start, "to": end, "split_date": split, "recordings": len(entries), "watts_basis": "derived_from_pace",
            "max_gap_s": ss.MAX_GAP_S, "durations": ss.curve_halves(entries, split)}


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

