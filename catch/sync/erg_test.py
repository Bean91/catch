from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy.orm import defer
from sqlmodel import Session, select

from catch.analytics.erg_test import detect_test_type
from catch.core import localtime
from catch.core.models import Activity, CanonicalActivity, Event
from catch.sync.rowing_predict import CONTINUOUS_WORKOUT_TYPES

"""Session 15 (see PLAN.md Part C): the DB-facing half of the erg test center, parallel to
catch/sync/rowing_predict.py's "recent best pieces" gathering — a "test" is just a
CanonicalActivity whose overrides carry {"tags": [..., "test"], "test_type": "2000m"} (the
same free-form overrides_json dict every other edit already uses — see catch/api/
routes_activities.py's TEST_TYPES/ActivityEditRequest.test_type), so confirming or
re-tagging a candidate goes through the existing PATCH /api/activities/{id}, not a bespoke
endpoint."""


def _overrides(canonical: CanonicalActivity) -> dict:
    return json.loads(canonical.overrides_json) if canonical.overrides_json else {}


def _erg_canonicals_with_concept2_member(session: Session, since: datetime | None = None) -> list[tuple[CanonicalActivity, Activity]]:
    # Session 17 (see PLAN.md Part D.4) — excludes a canonical absorbed into a piece
    # (`absorbed_into_piece_id`): its own Concept2 result is already represented as that
    # piece's row elsewhere in the test center, so letting it through here would also show
    # up as its own (duplicate) confirmed-test candidate or confirmed test.
    conditions = [CanonicalActivity.category == "erg", CanonicalActivity.absorbed_into_piece_id.is_(None)]
    if since is not None:
        conditions.append(CanonicalActivity.start >= since)
    rows = session.exec(select(CanonicalActivity).where(*conditions)).all()
    # One query for every member (session 32), not one per canonical: this runs on Today, the 2k estimate and recommendations.
    first_member: dict[int, Activity] = {}
    ids = [c.id for c in rows]
    for i in range(0, len(ids), 500):
        members = session.exec(
            select(Activity).options(defer(Activity.raw_json)).where(Activity.canonical_id.in_(ids[i : i + 500]), Activity.source == "concept2").order_by(Activity.id)
        ).all()
        for m in members:
            first_member.setdefault(m.canonical_id, m)
    return [(c, first_member[c.id]) for c in rows if c.id in first_member]


def _piece_rows(session: Session, test_type: str | None = None, since: datetime | None = None, modality: str = "rowing_erg") -> list[dict]:
    """Session 17 (see PLAN.md Part A.1/A.2): pieces count in the test center exactly like
    confirmed Concept2 results — "kind": "piece" plus a "piece_id" distinguish a row here from
    a confirmed-test row (which uses the canonical id as its own detail id), since a piece's
    canonical is the *containing* activity, not unique to the piece the way a confirmed test's
    canonical is."""
    from catch.core.models import Piece

    # Session 19: an interval piece isn't one continuous effort — it never becomes a test row.
    # Session 33: the test center (and everything that reads list_tests — the 2k estimate, PBs, performance trends) is rowing
    # erg only; bike pieces are listed separately by list_bike_pieces.
    pieces = session.exec(select(Piece).where(Piece.has_intervals.is_(False), Piece.modality == modality)).all()
    ids = sorted({p.canonical_id for p in pieces if p.canonical_id is not None})
    canonicals = {c.id: c for c in session.exec(select(CanonicalActivity).where(CanonicalActivity.id.in_(ids))).all()} if ids else {}
    out = []
    for p in pieces:
        if test_type and p.piece_type != test_type:
            continue
        canonical = canonicals.get(p.canonical_id)
        if since is not None and (canonical is None or canonical.start is None or canonical.start < since):
            continue
        splits = json.loads(p.splits_json) if p.splits_json else []
        hrs = [s["hr"] for s in splits if s.get("hr") is not None]
        out.append(
            {
                "kind": "piece",
                "modality": p.modality,
                "split_unit_m": 1000.0 if p.modality == "bike" else 500.0,
                "piece_id": p.id,
                "canonical_id": p.canonical_id,
                "activity_id": None,
                "test_type": p.piece_type,
                "title": canonical.title if canonical else None,
                "date": localtime.day_of(session, canonical).isoformat() if canonical and canonical.start else None,
                "start": canonical.start if canonical else None,
                "distance_m": p.distance_m,
                "duration_s": p.duration_s,
                "avg_power": p.avg_watts,
                "avg_stroke_rate": p.avg_rate,
                "avg_hr": (sum(hrs) / len(hrs)) if hrs else None,
                "drag_factor": p.drag_factor,
            }
        )
    return out


def list_bike_pieces(session: Session) -> list[dict]:
    """Bike pieces, newest first, for their own section of the test center — never mixed into rowing tests or PBs."""
    out = _piece_rows(session, modality="bike")
    out.sort(key=lambda r: r["start"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def list_tests(session: Session, test_type: str | None = None, since: datetime | None = None) -> list[dict]:
    out = []
    for canonical, member in _erg_canonicals_with_concept2_member(session, since):
        overrides = _overrides(canonical)
        if "test" not in (overrides.get("tags") or []):
            continue
        this_type = overrides.get("test_type")
        if test_type and this_type != test_type:
            continue
        out.append(
            {
                "kind": "test",
                "modality": "rowing_erg",
                "split_unit_m": 500.0,
                "piece_id": None,
                "canonical_id": canonical.id,
                "activity_id": member.id,
                "test_type": this_type,
                "title": canonical.title,
                "date": localtime.day_of(session, canonical).isoformat() if canonical.start else None,
                "start": canonical.start,
                "distance_m": member.distance,
                "duration_s": member.duration,
                "avg_power": member.avg_power,
                "avg_stroke_rate": member.stroke_rate,
                "avg_hr": member.avg_hr,
                # Session 18 (see PLAN.md) — additive field: the performance-trends
                # equivalence comparison annotates drag-factor spread across a bucket rather
                # than re-bucketing on it. Purely additive; no existing reader of this dict
                # breaks by gaining a key it doesn't look at.
                "drag_factor": member.drag_factor,
            }
        )
    out += _piece_rows(session, test_type, since)
    out.sort(key=lambda r: r["start"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def list_candidates(session: Session) -> list[dict]:
    """Untagged erg sessions that look like a standard test (task Part C.1) — a suggestion
    to confirm (via PATCH /api/activities/{id}), never auto-applied."""
    out = []
    for canonical, member in _erg_canonicals_with_concept2_member(session):
        overrides = _overrides(canonical)
        if "test" in (overrides.get("tags") or []):
            continue
        if member.workout_type not in CONTINUOUS_WORKOUT_TYPES:
            continue
        suggested = detect_test_type(member.distance, member.duration, member.stroke_rate)
        if suggested is None:
            continue
        out.append(
            {
                "canonical_id": canonical.id,
                "activity_id": member.id,
                "suggested_test_type": suggested,
                "title": canonical.title,
                "date": localtime.day_of(session, canonical).isoformat() if canonical.start else None,
                "distance_m": member.distance,
                "duration_s": member.duration,
                "avg_stroke_rate": member.stroke_rate,
            }
        )
    out.sort(key=lambda r: r["date"] or "", reverse=True)
    return out


def next_relevant_event(session: Session, today: date | None = None) -> Event | None:
    """"The next event" for a saved pacing plan (task Part C.3) — deliberately broader than
    catch/coach/memory.py's next_a_race (which hard-filters to an A-priority race): a pacing
    plan is just as often for an upcoming 2k_test as a race, and the task says "the next
    event," not "the next A race"."""
    today = today or localtime.today(session)
    return session.exec(select(Event).where(Event.date >= today).order_by(Event.date)).first()


def save_pacing_plan(session: Session, event_id: int, plan: dict) -> Event:
    event = session.get(Event, event_id)
    if event is None:
        raise ValueError(f"No event with id {event_id}")
    event.plan_json = json.dumps(plan)
    session.add(event)
    session.commit()
    session.refresh(event)
    return event
