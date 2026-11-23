"""Session 36: personal records, computed when read (so an edit, a merge, an exclusion or a deleted piece is reflected at once, and
history is never rewritten by storing a stale best).

What counts (docs/analytics.md §36):
  * A continuous Concept2 result (its own distance and time), or a confirmed single-effort piece. Interval sessions and interval
    pieces don't count: rest sits inside their time. Estimates never count.
  * Distance records use the test center's tolerance (±max(25 m, 2 %)), and the fastest time wins; timed records allow ±30 s and the
    furthest distance wins — the rules `/api/pbs` has always used.
  * Power records: the highest average power held over one whole continuous effort lasting at least N minutes. Rowing-erg power is
    the PM5's own average for a result; for a piece it is worked out from its average pace (labelled). A bike's power is what the
    monitor recorded — never worked out from its pace.
  * A workout excluded from totals is left out. Each workout counts once per record (its best qualifying effort).
  * Each entry says what it is: "test" (you confirmed it as a test), "piece" (a piece you recorded inside a session) or "training"
    (an ordinary continuous result), and whether Concept2 marks the result verified.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from sqlalchemy.orm import defer
from sqlmodel import Session, select

from catch.core import localtime
from catch.core.models import Activity, CanonicalActivity, Piece

CONTINUOUS_WORKOUT_TYPES = {None, "unknown", "JustRow", "FixedDistanceSplits", "FixedTimeSplits"}

ROWING_DISTANCES_M = (500, 1000, 2000, 5000, 6000, 10000)
BIKE_DISTANCES_M = (1000, 5000, 10000, 20000)
DURATIONS_S = {1800: "30min", 3600: "60min"}
POWER_FLOORS_S = (60, 300, 1200, 1800, 3600)
SPLIT_M = {"rowing_erg": 500.0, "bike": 1000.0}
_DURATION_TOLERANCE_S = 30.0


def _distance_tolerance(target: float) -> float:
    return max(25.0, target * 0.02)


def _overrides(c: CanonicalActivity | None) -> dict:
    return json.loads(c.overrides_json) if c is not None and c.overrides_json else {}


def candidates(session: Session, modality: str = "rowing_erg") -> list[dict]:
    """Every effort that can hold a record for one modality, with what it is and where it came from."""
    c2_type = "rower" if modality == "rowing_erg" else "bike"
    acts = session.exec(
        select(Activity).options(defer(Activity.raw_json), defer(Activity.intervals_json)).where(
            Activity.source == "concept2", Activity.type == c2_type, Activity.distance.is_not(None), Activity.duration.is_not(None)
        )
    ).all()
    acts = [a for a in acts if a.workout_type in CONTINUOUS_WORKOUT_TYPES]
    pieces = session.exec(
        select(Piece).where(Piece.concept2_activity_id.is_(None), Piece.has_intervals.is_(False), Piece.modality == modality)
    ).all()
    ids = {a.canonical_id for a in acts if a.canonical_id} | {p.canonical_id for p in pieces}
    canon = {c.id: c for c in session.exec(select(CanonicalActivity).where(CanonicalActivity.id.in_(ids))).all()} if ids else {}

    out: list[dict] = []
    for a in acts:
        c = canon.get(a.canonical_id)
        ov = _overrides(c)
        if ov.get("exclude_from_totals"):
            continue
        # A result not yet matched into a workout (matching runs after every sync, so only briefly) still counts, keyed on itself.
        owner_row = c if c is not None else a
        out.append({
            "distance_m": a.distance, "duration_s": a.duration,
            "date": localtime.day_of(session, owner_row) if owner_row.start else None,
            "canonical_id": c.id if c is not None else None, "activity_id": a.id, "piece_id": None,
            "avg_watts": a.avg_power, "watts_basis": "measured" if a.avg_power is not None else None,
            "label": "test" if "test" in (ov.get("tags") or []) else "training",
            "test_type": ov.get("test_type"),
            "verified": bool(a.c2_verified),
        })
    for p in pieces:
        c = canon.get(p.canonical_id)
        if c is None or _overrides(c).get("exclude_from_totals") or not p.distance_m or not p.duration_s:
            continue
        out.append({
            "distance_m": p.distance_m, "duration_s": p.duration_s,
            "date": localtime.day_of(session, c) if c.start else None,
            "canonical_id": c.id, "piece_id": p.id,
            "avg_watts": p.avg_watts,
            "watts_basis": ("derived" if modality == "rowing_erg" else "entered") if p.avg_watts is not None else None,
            "label": "piece", "test_type": p.piece_type,
            "verified": False,
        })
    return out


def _entry(c: dict, modality: str) -> dict:
    split_m = SPLIT_M[modality]
    pace = c["duration_s"] / c["distance_m"] * split_m if c["distance_m"] else None
    ref = f"/tests/piece/{c['piece_id']}" if c.get("piece_id") else f"/workouts/{c['canonical_id']}" if c["canonical_id"] is not None else None
    return {
        "distance_m": c["distance_m"], "duration_s": c["duration_s"], "pace_s": pace, "split_m": split_m,
        "avg_watts": c["avg_watts"], "watts_basis": c["watts_basis"],
        "date": c["date"], "canonical_id": c["canonical_id"], "piece_id": c.get("piece_id"), "ref": ref,
        "label": c["label"], "verified": c["verified"],
    }


def _in_range(c: dict, start: Optional[date], end: Optional[date]) -> bool:
    d = c.get("date")
    return d is not None and (start is None or d >= start) and (end is None or d <= end)


def _one_per_workout(cands: list[dict], better) -> list[dict]:
    best: dict = {}
    for c in cands:
        k = c["canonical_id"] if c["canonical_id"] is not None else ("activity", c.get("activity_id"))
        if k not in best or better(c, best[k]):
            best[k] = c
    return list(best.values())


def _history(cands: list[dict], better) -> list[dict]:
    """Each time the record improved, in date order (ties on a day keep the better one)."""
    out: list[dict] = []
    current = None
    for c in sorted(cands, key=lambda c: (c["date"], c["duration_s"])):
        if current is None or better(c, current):
            current = c
            out.append(c)
    return out


def records(session: Session, modality: str = "rowing_erg", start: Optional[date] = None, end: Optional[date] = None) -> dict:
    """Records by distance, by time and by power for one modality. With `start`/`end`, only efforts in that window count
    ("best in this period"); the history then starts inside the window too."""
    pool = [c for c in candidates(session, modality) if _in_range(c, start, end)]
    distances = ROWING_DISTANCES_M if modality == "rowing_erg" else BIKE_DISTANCES_M

    def faster(a, b):
        return a["duration_s"] < b["duration_s"]

    def further(a, b):
        return a["distance_m"] > b["distance_m"]

    def stronger(a, b):
        return (a["avg_watts"] or 0) > (b["avg_watts"] or 0)

    by_distance = []
    for target in distances:
        tol = _distance_tolerance(target)
        cands = _one_per_workout([c for c in pool if abs(c["distance_m"] - target) <= tol], faster)
        hist = _history(cands, faster)
        by_distance.append({
            "key": f"{target}m", "target_m": target, "count": len(cands),
            "best": _entry(hist[-1], modality) if hist else None,
            "history": [_entry(h, modality) for h in hist],
        })
    by_duration = []
    for target, key in DURATIONS_S.items():
        cands = _one_per_workout([c for c in pool if abs(c["duration_s"] - target) <= _DURATION_TOLERANCE_S], further)
        hist = _history(cands, further)
        by_duration.append({
            "key": key, "target_s": target, "count": len(cands),
            "best": _entry(hist[-1], modality) if hist else None,
            "history": [_entry(h, modality) for h in hist],
        })
    by_power = []
    for floor in POWER_FLOORS_S:
        cands = _one_per_workout([c for c in pool if c["avg_watts"] and c["duration_s"] >= floor - 1], stronger)
        hist = _history(cands, stronger)
        by_power.append({
            "key": f"{floor // 60}min_power", "min_duration_s": floor, "count": len(cands),
            "best": _entry(hist[-1], modality) if hist else None,
            "history": [_entry(h, modality) for h in hist],
        })
    return {
        "modality": modality,
        "from": start, "to": end,
        "distance": by_distance, "duration": by_duration, "power": by_power,
    }
