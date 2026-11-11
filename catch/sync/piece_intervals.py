from __future__ import annotations

"""Session 19 (see PLAN.md): the DB-facing half of intervals within a piece. Every mutation
funnels through `_commit_rows`, which rewrites positions contiguously, re-derives the parent
Piece's totals/weighted averages from `summarize_intervals`, and re-resolves the canonical —
so the parent piece and its intervals can never drift apart, and the piece's displayed
distance/duration are *work only* (rest is reported separately)."""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.piece_intervals import (
    expand_repeat,
    derived_split_s,
    interval_signature,
    summarize_intervals,
    validate_intervals,
)
from catch.core.models import Activity, Piece, PieceInterval, Stroke
from catch.sync.piece import _resolve_and_rescore

INTERVAL_FIELDS = (
    "target_type",
    "work_distance_m",
    "work_duration_s",
    "rest_duration_s",
    "avg_split_s",
    "avg_watts",
    "avg_rate",
    "avg_hr",
    "max_hr",
    "calories",
    "notes",
)


class NoIntervalData(ValueError):
    pass


def interval_row(i: PieceInterval) -> dict:
    return {"id": i.id, "piece_id": i.piece_id, "position": i.position, "source": i.source, **{f: getattr(i, f) for f in INTERVAL_FIELDS}}


def list_interval_rows(session: Session, piece_id: int) -> list[PieceInterval]:
    return session.exec(select(PieceInterval).where(PieceInterval.piece_id == piece_id).order_by(PieceInterval.position)).all()


def intervals_payload(session: Session, piece: Piece) -> dict:
    rows = [interval_row(r) for r in list_interval_rows(session, piece.id)]
    for r in rows:
        r["split_s"] = derived_split_s(r)
    return {"intervals": rows, "interval_summary": summarize_intervals(rows) if rows else None, "interval_signature": interval_signature(rows)}


def _plain(row: dict, position: int) -> dict:
    out = {f: row.get(f) for f in INTERVAL_FIELDS}
    out["position"] = position
    return out


def _commit_rows(session: Session, piece: Piece, plain_rows: list[dict], source_by_row: Optional[list[str]] = None, *, force: bool = False) -> tuple[bool, dict]:
    """Replaces the piece's intervals with `plain_rows` (already in final order). Returns
    (saved, validation). Validation failures block the save unless `force` — the same
    soft-validation contract as splits, so an athlete can save an incomplete interval set and
    return to it later."""
    rows = [_plain(r, i) for i, r in enumerate(plain_rows)]
    validation = validate_intervals(rows)
    if not validation["ok"] and not force:
        return False, validation

    # Update in place by id (never delete-and-recreate): ids stay stable across edits and
    # reorders, and SQLite would otherwise hand a deleted row's id to the next insert, so a
    # client still holding the old id could silently edit a different interval.
    existing = {r.id: r for r in list_interval_rows(session, piece.id)}
    keep = {r.get("id") for r in plain_rows if r.get("id") in existing}
    for iid, row in existing.items():
        if iid not in keep:
            session.delete(row)
    now = datetime.now(timezone.utc)
    for i, (src, row) in enumerate(zip(plain_rows, rows)):
        target = existing.get(src.get("id"))
        if target is None:
            session.add(PieceInterval(piece_id=piece.id, source=(source_by_row[i] if source_by_row else "manual"), updated_at=now, **row))
            continue
        for k, v in row.items():
            setattr(target, k, v)
        target.updated_at = now
        session.add(target)
    _sync_piece_totals(piece, rows)
    session.add(piece)
    session.commit()
    session.refresh(piece)
    _resolve_and_rescore(session, piece.canonical_id)
    return True, validation


def _sync_piece_totals(piece: Piece, rows: list[dict]) -> None:
    piece.has_intervals = bool(rows)
    piece.updated_at = datetime.now(timezone.utc)
    if not rows:
        # Last interval removed: stop reporting stale work totals as if this were a single effort.
        piece.distance_m = piece.duration_s = piece.avg_split_s = piece.avg_rate = piece.avg_watts = None
        return
    s = summarize_intervals(rows)
    piece.distance_m = s["work_distance_m"]
    piece.duration_s = s["work_duration_s"]
    piece.avg_split_s = s["avg_split_s"]
    piece.avg_rate = s["avg_rate"]
    piece.avg_watts = s["avg_watts"]
    # Splits are the single-effort representation; an interval piece never carries them, and an
    # empty list is also what keeps power_member_and_samples from overlaying anything.
    piece.splits_json = "[]"
    piece.window_activity_id = piece.window_start_s = piece.window_end_s = None
    piece.time_in_zone_json = None
    piece.hr_recovery_bpm = None


def _require_piece(session: Session, piece_id: int) -> Piece:
    piece = session.get(Piece, piece_id)
    if piece is None:
        raise LookupError(f"No piece with id {piece_id}")
    return piece


def create_interval_piece(
    session: Session,
    canonical_id: int,
    intervals: list[dict],
    *,
    piece_type: str = "custom",
    notes: Optional[str] = None,
    source: str = "manual",
    concept2_activity_id: Optional[int] = None,
    force: bool = False,
) -> tuple[Optional[Piece], dict]:
    rows = [_plain(r, i) for i, r in enumerate(intervals)]
    validation = validate_intervals(rows)
    if (not validation["ok"] and not force) or not rows:
        if not rows:
            validation = {"ok": False, "issues": [{"index": None, "field": None, "message": "Add at least one interval."}]}
        return None, validation
    piece = Piece(canonical_id=canonical_id, piece_type=piece_type, source=source, notes=notes, concept2_activity_id=concept2_activity_id)
    session.add(piece)
    session.commit()
    session.refresh(piece)
    row_sources = [r.get("source") or ("concept2" if source == "concept2" else "manual") for r in intervals]
    _commit_rows(session, piece, rows, row_sources, force=True)
    return piece, validation


def replace_intervals(session: Session, piece_id: int, intervals: list[dict], *, force: bool = False) -> tuple[bool, dict]:
    piece = _require_piece(session, piece_id)
    return _commit_rows(session, piece, intervals, force=force)


def add_intervals(session: Session, piece_id: int, new_rows: list[dict], *, force: bool = False) -> tuple[bool, dict]:
    piece = _require_piece(session, piece_id)
    current = [interval_row(r) for r in list_interval_rows(session, piece_id)]
    return _commit_rows(session, piece, current + new_rows, [r["source"] for r in current] + ["manual"] * len(new_rows), force=force)


def add_repeats(session: Session, piece_id: int, count: int, *, work_distance_m=None, work_duration_s=None, rest_duration_s=None, force: bool = False):
    piece = _require_piece(session, piece_id)
    current = [interval_row(r) for r in list_interval_rows(session, piece_id)]
    new_rows = expand_repeat(count, work_distance_m=work_distance_m, work_duration_s=work_duration_s, rest_duration_s=rest_duration_s, start_position=len(current))
    # The previous last interval had no trailing rest; extending a set gives it the new block's
    # rest so the sequence stays uniform.
    if current and rest_duration_s and not current[-1].get("rest_duration_s"):
        current[-1]["rest_duration_s"] = rest_duration_s
    return _commit_rows(session, piece, current + new_rows, [r["source"] for r in current] + ["manual"] * len(new_rows), force=force)


def update_interval(session: Session, interval_id: int, patch: dict, *, force: bool = False) -> tuple[Optional[PieceInterval], dict]:
    target = session.get(PieceInterval, interval_id)
    if target is None:
        raise LookupError(f"No interval with id {interval_id}")
    piece = _require_piece(session, target.piece_id)
    current = [interval_row(r) for r in list_interval_rows(session, piece.id)]
    for r in current:
        if r["id"] == interval_id:
            r.update({k: v for k, v in patch.items() if k in INTERVAL_FIELDS})
    saved, validation = _commit_rows(session, piece, current, [r["source"] for r in current], force=force)
    if not saved:
        return None, validation
    return session.get(PieceInterval, interval_id), validation


def delete_interval(session: Session, interval_id: int) -> bool:
    target = session.get(PieceInterval, interval_id)
    if target is None:
        return False
    piece = _require_piece(session, target.piece_id)
    current = [interval_row(r) for r in list_interval_rows(session, piece.id) if r.id != interval_id]
    _commit_rows(session, piece, current, [r["source"] for r in current], force=True)
    return True


def reorder_intervals(session: Session, piece_id: int, ids: list[int]) -> None:
    """`ids` must be an exact permutation of the piece's current interval ids."""
    piece = _require_piece(session, piece_id)
    current = {r.id: interval_row(r) for r in list_interval_rows(session, piece_id)}
    if len(ids) != len(set(ids)) or set(ids) != set(current):
        raise ValueError("ids must list every interval of this piece exactly once")
    ordered = [current[i] for i in ids]
    _commit_rows(session, piece, ordered, [r["source"] for r in ordered], force=True)


def delete_all_for_piece(session: Session, piece_id: int) -> None:
    for r in list_interval_rows(session, piece_id):
        session.delete(r)


# --- Concept2 on-demand import ---------------------------------------------------------------


def _concept2_interval_defs(activity: Activity) -> list[dict]:
    """The result's own `workout.intervals` list, or [] — never inferred from aggregates.
    Times/rest are tenths of a second in Concept2's payload (docs/concept2-endpoints.md)."""
    if not activity.intervals_json:
        return []
    try:
        workout = json.loads(activity.intervals_json)
    except ValueError:
        return []
    intervals = workout.get("intervals") if isinstance(workout, dict) else None
    return [i for i in intervals if isinstance(i, dict)] if isinstance(intervals, list) else []


def has_concept2_intervals(activity: Activity) -> bool:
    return bool(_concept2_interval_defs(activity))


def _mean(vals: list[float]) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _rows_from_concept2(session: Session, activity: Activity) -> list[dict]:
    defs = _concept2_interval_defs(activity)
    strokes = session.exec(select(Stroke).where(Stroke.activity_id == activity.id)).all()
    by_interval: dict[int, list[Stroke]] = {}
    for s in strokes:
        by_interval.setdefault(s.interval_index or 0, []).append(s)
    rows = []
    for idx, d in enumerate(defs):
        dist = d.get("distance")
        dur = d.get("time") / 10.0 if d.get("time") else None
        rest = d.get("rest_time") / 10.0 if d.get("rest_time") else None
        is_time = d.get("type") == "time" or (d.get("type") != "distance" and not dist and bool(dur))
        in_interval = by_interval.get(idx, [])
        hrs = [s.hr for s in in_interval if s.hr]
        row = {
            "target_type": "time" if is_time else "distance",
            "work_distance_m": float(dist) if dist else None,
            "work_duration_s": dur,
            "rest_duration_s": rest,
            "avg_split_s": None,
            "avg_watts": _mean([s.watts for s in in_interval if s.watts]),
            "avg_rate": float(d["stroke_rate"]) if d.get("stroke_rate") else _mean([s.stroke_rate for s in in_interval if s.stroke_rate]),
            "avg_hr": _mean(hrs),
            "max_hr": max(hrs) if hrs else None,
            "calories": None,
            "notes": None,
            "source": "concept2",
        }
        rows.append(row)
    return rows


def build_intervals_from_concept2(session: Session, canonical_id: int, activity_id: int) -> Piece:
    """Creates (or refreshes, idempotently keyed on concept2_activity_id) an interval piece
    from a Concept2 member's real `workout.intervals`. Raises NoIntervalData when the payload
    carries none — interval data is never fabricated from the aggregate distance/time."""
    activity = session.get(Activity, activity_id)
    if activity is None or activity.source != "concept2" or activity.canonical_id != canonical_id:
        raise NoIntervalData("That Concept2 result isn't part of this activity.")
    rows = _rows_from_concept2(session, activity)
    if not rows:
        raise NoIntervalData("This Concept2 result has no interval data.")
    existing = session.exec(select(Piece).where(Piece.concept2_activity_id == activity_id, Piece.has_intervals.is_(True))).first()
    if existing is not None:
        old_ids = [r.id for r in list_interval_rows(session, existing.id)]
        for i, r in enumerate(rows):
            r["id"] = old_ids[i] if i < len(old_ids) else None
        _commit_rows(session, existing, rows, ["concept2"] * len(rows), force=True)
        return existing
    piece, _ = create_interval_piece(session, canonical_id, rows, source="concept2", concept2_activity_id=activity_id, force=True)
    assert piece is not None
    return piece
