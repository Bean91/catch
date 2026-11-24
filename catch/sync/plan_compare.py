"""Session 36: the DB-facing half of planned-vs-done (pure rules in catch/analytics/plan_compare.py).

Where a linked workout's reps come from, in order of how much they carry:
  1. an interval piece on the workout (typed, read off a PM5 photo, or imported from Concept2);
  2. the Concept2 result's own `workout.intervals`;
  3. the device's laps (time only, plus heart rate/power/cadence averaged from the recording's own samples).
The first source that has reps is used and named on the screen; sources are never mixed."""

from __future__ import annotations

import json
from typing import Optional

from sqlmodel import Session, select

from catch.analytics import plan_compare as pc
from catch.analytics.piece import SPLIT_M_BY_MODALITY
from catch.analytics.piece_intervals import interval_watts_from_pace
from catch.analytics.samples_codec import unpack_series
from catch.core.models import Activity, ActivitySamples, CanonicalActivity, Piece
from catch.sync import planning



def _split_m(canonical: CanonicalActivity) -> float:
    return SPLIT_M_BY_MODALITY["bike"] if canonical.sport_family == "cycling" else SPLIT_M_BY_MODALITY["rowing_erg"]


def _reps_from_piece(session: Session, canonical_id: int) -> Optional[list[dict]]:
    from catch.sync.piece_intervals import intervals_payload

    piece = session.exec(
        select(Piece).where(Piece.canonical_id == canonical_id, Piece.has_intervals.is_(True)).order_by(Piece.id)
    ).first()
    if piece is None:
        return None
    rows = intervals_payload(session, piece)["intervals"]
    if not rows:
        return None
    derives = piece.modality == "rowing_erg"
    out = []
    for r in rows:
        own = "measured" if r.get("source") == "concept2" else "entered"
        out.append(pc.actual_from_values(
            duration_s=r.get("work_duration_s"), distance_m=r.get("work_distance_m"),
            split_s=r.get("avg_split_s") if r.get("avg_split_s") is not None else r.get("split_s"),
            watts=r.get("avg_watts"), rate=r.get("avg_rate"), hr=r.get("avg_hr"),
            split_m=SPLIT_M_BY_MODALITY.get(piece.modality, 500.0),
            basis={
                "duration_s": own, "distance_m": own, "rate": own, "hr": own,
                "split_s": own if r.get("avg_split_s") is not None else "derived",
                "watts": "derived" if derives else own,
            },
        ))
    return out


def _reps_from_concept2(session: Session, members: list[Activity]) -> Optional[list[dict]]:
    from catch.sync.piece_intervals import _rows_from_concept2

    for m in members:
        if m.source != "concept2":
            continue
        rows = _rows_from_concept2(session, m)
        if not rows:
            continue
        modality = "bike" if m.type == "bike" else "rowing_erg"
        split_m = SPLIT_M_BY_MODALITY[modality]
        out = []
        for r in rows:
            watts = interval_watts_from_pace(r, modality)
            out.append(pc.actual_from_values(
                duration_s=r.get("work_duration_s"), distance_m=r.get("work_distance_m"),
                watts=watts, rate=r.get("avg_rate"), hr=r.get("avg_hr"), split_m=split_m,
                basis={"watts": "derived"} if watts is not None else {},
            ))
        return out
    return None


def _mean(vals: list) -> Optional[float]:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def _reps_from_laps(session: Session, members: list[Activity], planned_work: list[dict], all_reps: list[dict]) -> Optional[tuple[list[dict], Optional[str], Optional[str]]]:
    for m in members:
        if not m.laps_json:
            continue
        laps = json.loads(m.laps_json) or []
        if len(laps) < 2:
            continue
        samples = session.get(ActivitySamples, m.id)
        hr = power = cadence = None
        if samples is not None:
            n = samples.n_samples
            hr, power, cadence = unpack_series(samples.hr_blob, n), unpack_series(samples.power_blob, n), unpack_series(samples.cadence_blob, n)
        chosen, method, reason = pc.select_work_laps(laps, planned_work, all_reps)
        out = []
        for lap in chosen:
            a, b = int(lap.get("offset_s") or 0), int((lap.get("offset_s") or 0) + (lap.get("duration_s") or 0))
            out.append(pc.actual_from_values(
                duration_s=lap.get("duration_s"), distance_m=lap.get("distance_m"),
                hr=lap.get("avg_hr") if lap.get("avg_hr") is not None else (_mean(hr[a:b]) if hr else None),
                watts=_mean(power[a:b]) if power else None,
                rate=lap.get("avg_cadence") if lap.get("avg_cadence") is not None else (_mean(cadence[a:b]) if cadence else None),
                split_m=500.0,
            ))
        return out, method, reason
    return None


def comparison(session: Session, owner_id: str, planned_id: int) -> dict:
    row = planning.get_planned(session, owner_id, planned_id)
    planned = planning.planned_dict(row)
    base = {"planned_id": row.id, "planned": planned, "linked": row.linked_canonical_id is not None}
    if row.linked_canonical_id is None:
        return {**base, "comparison": None, "reason": "Link a completed workout to compare it with this plan."}
    canonical = session.get(CanonicalActivity, row.linked_canonical_id)
    if canonical is None:
        return {**base, "linked": False, "comparison": None, "reason": "The linked workout no longer exists."}
    members = list(session.exec(select(Activity).where(Activity.canonical_id == canonical.id).order_by(Activity.id)).all())
    split_m = _split_m(canonical)
    all_reps = pc.expand_planned(planned["structure"])
    work = [r for r in all_reps if r["kind"] == "work"]

    pairing = pairing_reason = None
    reps, source = _reps_from_piece(session, canonical.id), "piece"
    if not reps:
        reps, source = _reps_from_concept2(session, members), "concept2"
    if not reps:
        from_laps = _reps_from_laps(session, members, work, all_reps)
        reps, source = [], "laps"
        if from_laps:
            reps, pairing, pairing_reason = from_laps
    if not reps:
        reps, source = [], None

    whole = pc.actual_from_values(
        duration_s=canonical.duration, distance_m=canonical.distance, watts=canonical.avg_power,
        rate=canonical.avg_cadence, hr=canonical.avg_hr, split_m=split_m,
    )
    result = pc.compare(planned, reps, whole, reps_source=source, pairing=pairing, pairing_reason=pairing_reason)
    return {
        **base,
        "workout": {"id": canonical.id, "ref": f"/workouts/{canonical.id}", "title": canonical.title, "sport_family": canonical.sport_family},
        "split_basis_m": split_m,
        "comparison": result,
        "reason": None,
    }


def comparison_for_workout(session: Session, owner_id: str, canonical_id: int) -> Optional[dict]:
    from catch.core.models import PlannedWorkout

    row = session.exec(select(PlannedWorkout).where(PlannedWorkout.linked_canonical_id == canonical_id)).first()
    if row is None or row.owner_id != owner_id:
        return None
    return comparison(session, owner_id, row.id)
