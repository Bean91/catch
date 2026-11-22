"""Session 34: the one-time upgrade of stored pieces to "watts from split pace" (docs/analytics.md §34).

Before this, a piece's average watts was the plain mean of its split watts (or of per-stroke watts for an absorbed Concept2 piece), and
split rows without typed watts had none. The backfill re-derives every rowing piece's split, interval and average power from the pace it
already stores, through the same pure functions new pieces use. It is repeatable (idempotent) and preserves what people typed:
- a split row whose typed watts disagree with its pace keeps them as `watts_entered` (analytics/piece.with_derived_watts);
- a typed interval watts that disagrees with its pace is left as it is — the athlete sees it flagged on the next edit;
- bike pieces keep their own power (only its average is re-weighted by time); a row with no pace is never given one.
Runs once per owner from scheduler.run_maintenance, marked by a maintenance marker beside the settings."""

from __future__ import annotations

import json
import logging

from sqlmodel import Session, select

from catch.analytics.piece import DEFAULT_MODALITY, PIECE_POWER_MODEL, piece_avg_watts, with_derived_watts
from catch.analytics.piece_intervals import interval_watts_from_pace, summarize_intervals, watts_agree
from catch.core.models import Piece, PieceInterval
from catch.core.settings_store import maintenance_marker, set_maintenance_marker

logger = logging.getLogger("catch.piece_power")
MARKER = "piece_power_model"


def is_current(session: Session) -> bool:
    return maintenance_marker(session, MARKER) >= PIECE_POWER_MODEL


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= 1e-6


def backfill_piece_power(session: Session) -> set[int]:
    """Re-derives stored power; returns the canonical ids whose pieces changed (their power overlay needs re-resolving)."""
    if is_current(session):
        return set()
    changed: set[int] = set()
    for piece in session.exec(select(Piece)).all():
        modality = piece.modality or DEFAULT_MODALITY
        before = piece.avg_watts
        if piece.has_intervals:
            models = session.exec(select(PieceInterval).where(PieceInterval.piece_id == piece.id).order_by(PieceInterval.position)).all()
            rows = []
            for m in models:
                row = {f: getattr(m, f) for f in ("target_type", "work_distance_m", "work_duration_s", "rest_duration_s", "avg_split_s", "avg_watts",
                                                  "avg_rate", "avg_hr", "max_hr", "calories")}
                derived = interval_watts_from_pace(row, modality)
                typed = m.avg_watts
                if derived is not None and (typed is None or watts_agree(typed, derived)):
                    if not _close(m.avg_watts, derived):
                        m.avg_watts = derived
                        session.add(m)
                    row["avg_watts"] = derived
                rows.append(row)
            piece.avg_watts = summarize_intervals(rows, modality)["avg_watts"] if rows else None
        else:
            rows = json.loads(piece.splits_json) if piece.splits_json else []
            derived_rows = with_derived_watts(rows, modality)
            if derived_rows != rows:
                piece.splits_json = json.dumps(derived_rows)
            piece.avg_watts, _ = piece_avg_watts(modality, piece.avg_split_s, derived_rows, entered=piece.avg_watts)
        if not _close(before, piece.avg_watts) or session.is_modified(piece):
            changed.add(piece.canonical_id)
            session.add(piece)
    set_maintenance_marker(session, MARKER, PIECE_POWER_MODEL)
    session.commit()
    if changed:
        logger.info("piece power backfill updated pieces on %d workouts", len(changed))
    return changed
