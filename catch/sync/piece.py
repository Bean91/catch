from __future__ import annotations

"""Session 17 (see PLAN.md — the task called itself "session 13"): the DB-facing half of
pieces. A piece is a segment of a canonical activity (task Part A.1); this module creates/
edits/aligns/deletes them, overlays their power onto the activity's zones/strain pipeline
(Part D.2/D.3, called from catch/sync/canonical.py), and — once a Concept2 result for the
same effort syncs later — absorbs its real stroke data in place of the typed/photo fallback
(Part D.4, called from catch/sync/matching.py's run_matching)."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.erg_test import actual_splits
from catch.analytics.piece import aggregate_from_splits, find_best_window, standard_distance_m, validate_splits
from catch.analytics.samples_codec import unpack_series
from catch.analytics.technique import interval_summary
from catch.analytics.zones_samples import drop_dropouts, hr_recovery_drop, smooth, time_in_zone_seconds
from catch.core.models import Activity, ActivitySamples, CanonicalActivity, MergeLog, Piece, PieceInterval, PiecePhoto, Stroke
from catch.core.settings_store import get_settings

logger = logging.getLogger("catch.piece")

# A piece's local-day + distance/duration signature must agree this closely with a Concept2
# result's own for Part D.4 to treat them as "the same effort" — tight on purpose (standard
# test distances are exact numbers; a coincidentally similar but different piece should never
# silently absorb the wrong result).
_ABSORB_DISTANCE_TOLERANCE_PCT = 0.01
_ABSORB_DURATION_TOLERANCE_S = 2.0


def _unpack(session: Session, activity_id: int) -> Optional[dict]:
    row = session.get(ActivitySamples, activity_id)
    if row is None:
        return None
    return {
        "hr": unpack_series(row.hr_blob, row.n_samples),
        "power": unpack_series(row.power_blob, row.n_samples),
        "cadence": unpack_series(row.cadence_blob, row.n_samples),
    }


def _resolve_and_rescore(session: Session, canonical_id: int) -> None:
    from catch.sync.canonical import resolve_canonical
    from catch.sync.scoring import recompute_scores

    resolve_canonical(session, canonical_id)
    recompute_scores(session)


def piece_dict(piece: Piece, has_photo: bool = False) -> dict:
    return {
        "id": piece.id,
        "canonical_id": piece.canonical_id,
        "piece_type": piece.piece_type,
        "distance_m": piece.distance_m,
        "duration_s": piece.duration_s,
        "avg_split_s": piece.avg_split_s,
        "avg_rate": piece.avg_rate,
        "avg_watts": piece.avg_watts,
        "drag_factor": piece.drag_factor,
        "splits": json.loads(piece.splits_json) if piece.splits_json else [],
        "source": piece.source,
        "window_activity_id": piece.window_activity_id,
        "window_start_s": piece.window_start_s,
        "window_end_s": piece.window_end_s,
        "concept2_activity_id": piece.concept2_activity_id,
        "time_in_zone": json.loads(piece.time_in_zone_json) if piece.time_in_zone_json else None,
        "hr_recovery_bpm": piece.hr_recovery_bpm,
        "notes": piece.notes,
        "has_photo": has_photo,
        "created_at": piece.created_at,
    }


def piece_payload(session: Session, piece: Piece, has_photo: bool = False) -> dict:
    """piece_dict plus the piece's intervals/summary — the shape every API and coach read
    returns. A lazy import because piece_intervals imports _resolve_and_rescore from here."""
    from catch.sync.piece_intervals import intervals_payload

    out = piece_dict(piece, has_photo=has_photo)
    out["has_intervals"] = bool(piece.has_intervals)
    out.update(intervals_payload(session, piece) if piece.has_intervals else {"intervals": [], "interval_summary": None, "interval_signature": None})
    return out


def list_pieces_for_canonical(session: Session, canonical_id: int) -> list[Piece]:
    return session.exec(select(Piece).where(Piece.canonical_id == canonical_id).order_by(Piece.created_at)).all()


def list_pieces_payload(session: Session, canonical_id: int) -> list[dict]:
    pieces = list_pieces_for_canonical(session, canonical_id)
    photo_ids = set(session.exec(select(PiecePhoto.piece_id).where(PiecePhoto.piece_id.in_([p.id for p in pieces]))).all()) if pieces else set()
    return [piece_payload(session, p, has_photo=p.id in photo_ids) for p in pieces]


def get_piece(session: Session, piece_id: int) -> Optional[Piece]:
    return session.get(Piece, piece_id)


def _pick_window_activity(session: Session, canonical_id: int, min_duration_s: float) -> Optional[Activity]:
    """The first member with a sample stream at least as long as the piece — Part D's window
    always lives inside one member's own recording, never spliced across two."""
    members = session.exec(select(Activity).where(Activity.canonical_id == canonical_id)).all()
    for m in members:
        if m.id is None:
            continue
        row = session.get(ActivitySamples, m.id)
        if row is not None and row.n_samples >= min_duration_s:
            return m
    return None


def _mark_typed_hr(splits: list[dict]) -> list[dict]:
    """Tags every row that already carries an HR value (typed or read off a PM5 photo) as
    `"hr_source": "typed"` so `_apply_alignment` (Part D.2) knows never to overwrite it — only
    a row with no athlete-supplied HR gets one derived from the sample stream, and a later
    re-align always refreshes (never leaves stale) the derived ones. A no-op on a row that
    already has `hr_source` set (e.g. one coming back from a previous align)."""
    for row in splits:
        if row.get("hr") is not None and row.get("hr_source") is None:
            row["hr_source"] = "typed"
    return splits


def create_piece(
    session: Session,
    canonical_id: int,
    piece_type: str,
    splits: list[dict],
    *,
    distance_m: Optional[float] = None,
    duration_s: Optional[float] = None,
    drag_factor: Optional[int] = None,
    source: str = "manual",
    notes: Optional[str] = None,
    force: bool = False,
) -> tuple[Optional[Piece], dict]:
    """Returns (piece_or_None, validation). `piece` is None (nothing saved) when validation
    fails and `force` isn't set — task Part B.3's "highlight, don't silently correct": the
    athlete sees exactly which rows disagree and either fixes them or explicitly saves anyway."""
    splits = _mark_typed_hr(splits)
    agg = aggregate_from_splits(splits)
    total_distance = distance_m if distance_m is not None else agg["distance_m"]
    total_duration = duration_s if duration_s is not None else agg["duration_s"]
    validation = validate_splits(splits, total_distance, total_duration)
    # A standard-type piece whose splits carry no distance at all (e.g. a pure paste with no
    # per-row distance) still has a real, known total distance — falling back to None here
    # would silently drop the piece out of every distance-keyed reader (PBs, predict, the
    # Part D.4 absorb match). Applied *after* validation, which already has nothing to check
    # a missing distance against anyway.
    if total_distance is None:
        total_distance = standard_distance_m(piece_type)
    if not validation["ok"] and not force:
        return None, validation

    piece = Piece(
        canonical_id=canonical_id,
        piece_type=piece_type,
        distance_m=total_distance,
        duration_s=total_duration,
        avg_split_s=agg["avg_split_s"],
        avg_rate=agg["avg_rate"],
        avg_watts=agg["avg_watts"],
        drag_factor=drag_factor,
        splits_json=json.dumps(splits),
        source=source,
        notes=notes,
    )
    session.add(piece)
    session.commit()
    session.refresh(piece)

    # Auto-suggest a window immediately (task Part D.1) — best-effort; a piece with nowhere
    # to align (no member has samples long enough yet) just stays unaligned until one does.
    _auto_align(session, piece)
    _resolve_and_rescore(session, canonical_id)
    return piece, validation


def update_piece(
    session: Session,
    piece_id: int,
    *,
    splits: Optional[list[dict]] = None,
    distance_m: Optional[float] = None,
    duration_s: Optional[float] = None,
    notes: Optional[str] = None,
    force: bool = False,
) -> tuple[Optional[Piece], dict]:
    """`distance_m`/`duration_s` are the *independent* "total" the athlete entered or the
    screen showed (task Part C.1's "enter the total and splits and it checks they match") —
    when omitted, validation checks the new splits against the piece's existing total rather
    than re-deriving that total from the very splits being checked, which would make the
    total-time/distance check pass trivially on every edit after the first (a real bug an
    advisor review caught: aggregate_from_splits always makes the sum match itself)."""
    piece = session.get(Piece, piece_id)
    if piece is None:
        raise ValueError(f"No piece with id {piece_id}")
    validation = {"ok": True, "issues": []}
    if splits is not None:
        splits = _mark_typed_hr(splits)
        target_distance = distance_m if distance_m is not None else piece.distance_m
        target_duration = duration_s if duration_s is not None else piece.duration_s
        validation = validate_splits(splits, target_distance, target_duration)
        if not validation["ok"] and not force:
            return None, validation
        piece.splits_json = json.dumps(splits)
        agg = aggregate_from_splits(splits)
        piece.distance_m = target_distance if target_distance is not None else agg["distance_m"]
        piece.duration_s = target_duration if target_duration is not None else agg["duration_s"]
        piece.avg_split_s = agg["avg_split_s"]
        piece.avg_rate = agg["avg_rate"]
        piece.avg_watts = agg["avg_watts"]
    elif distance_m is not None or duration_s is not None:
        # The athlete corrected the total alone, splits unchanged — re-validate the existing
        # splits against the new target rather than silently accepting an untested total.
        existing_splits = json.loads(piece.splits_json) if piece.splits_json else []
        target_distance = distance_m if distance_m is not None else piece.distance_m
        target_duration = duration_s if duration_s is not None else piece.duration_s
        validation = validate_splits(existing_splits, target_distance, target_duration)
        if not validation["ok"] and not force:
            return None, validation
        piece.distance_m = target_distance
        piece.duration_s = target_duration
    if notes is not None:
        piece.notes = notes
    piece.updated_at = datetime.now(timezone.utc)
    session.add(piece)
    session.commit()
    session.refresh(piece)
    if piece.window_activity_id is not None:
        _apply_alignment(session, piece, piece.window_activity_id, piece.window_start_s)
    _resolve_and_rescore(session, piece.canonical_id)
    return piece, validation


def delete_piece(session: Session, piece_id: int) -> bool:
    piece = session.get(Piece, piece_id)
    if piece is None:
        return False
    canonical_id = piece.canonical_id
    photo = session.get(PiecePhoto, piece_id)
    if photo is not None:
        session.delete(photo)
    for interval in session.exec(select(PieceInterval).where(PieceInterval.piece_id == piece_id)).all():
        session.delete(interval)
    session.delete(piece)
    session.commit()
    _resolve_and_rescore(session, canonical_id)
    return True


def attach_photo(session: Session, piece_id: int, image: bytes, content_type: str) -> PiecePhoto:
    existing = session.get(PiecePhoto, piece_id)
    if existing is not None:
        session.delete(existing)
        session.flush()
    photo = PiecePhoto(piece_id=piece_id, image=image, content_type=content_type)
    session.add(photo)
    session.commit()
    return photo


def get_photo(session: Session, piece_id: int) -> Optional[PiecePhoto]:
    return session.get(PiecePhoto, piece_id)


def delete_photo(session: Session, piece_id: int) -> bool:
    photo = session.get(PiecePhoto, piece_id)
    if photo is None:
        return False
    session.delete(photo)
    session.commit()
    return True


def _apply_alignment(session: Session, piece: Piece, activity_id: int, start_s: int) -> None:
    """Sets the window, then derives per-split HR (where not already typed/photographed —
    Part D.2 never overwrites a real reading the athlete already has), time-in-zone, and
    post-piece HR recovery from the member's own sample stream. Pure window bookkeeping — the
    actual zones/strain refinement (Part D.3) happens later, in resolve_canonical."""
    duration = int(round(piece.duration_s)) if piece.duration_s else 0
    end_s = start_s + duration
    piece.window_activity_id = activity_id
    piece.window_start_s = start_s
    piece.window_end_s = end_s

    samples = _unpack(session, activity_id)
    if samples is None:
        session.add(piece)
        session.commit()
        return

    settings = get_settings(session)
    max_hr = settings.get("max_hr")
    hr_full = samples["hr"]
    window_hr = hr_full[start_s:end_s]

    splits = json.loads(piece.splits_json) if piece.splits_json else []
    cum = 0.0
    for row in splits:
        split_s = row.get("split_s")
        if split_s is None:
            continue
        lo, hi = int(cum), int(cum + split_s)
        # Never touch a typed/photo HR or a real Concept2-stroke HR (task Part D.2) — but a
        # *derived* one must be refreshed on every align, including a drag to a different
        # window, or it would keep showing the previous window's HR (a real bug an advisor
        # review caught: the original version only filled a row whose hr was still None, so
        # the first auto-align's values survived every later re-align untouched).
        if row.get("hr_source") not in ("typed", "concept2"):
            segment = [v for v in window_hr[lo:hi] if v is not None]
            if segment:
                row["hr"] = sum(segment) / len(segment)
                row["hr_source"] = "derived"
            else:
                row["hr"] = None
                row["hr_source"] = None
        cum += split_s
    piece.splits_json = json.dumps(splits)

    cleaned = drop_dropouts([v for v in window_hr])
    tiz = time_in_zone_seconds(smooth(cleaned), max_hr, settings) if any(v is not None for v in cleaned) else None
    piece.time_in_zone_json = json.dumps(tiz) if tiz else None
    piece.hr_recovery_bpm = hr_recovery_drop(hr_full, end_s - 1, 60)

    session.add(piece)
    session.commit()


def _auto_align(session: Session, piece: Piece) -> bool:
    if not piece.duration_s:
        return False
    member = _pick_window_activity(session, piece.canonical_id, piece.duration_s)
    if member is None or member.id is None:
        return False
    samples = _unpack(session, member.id)
    if samples is None:
        return False
    start = find_best_window(samples["hr"], int(round(piece.duration_s)))
    if start is None:
        return False
    _apply_alignment(session, piece, member.id, start)
    return True


def align_piece(session: Session, piece_id: int, *, activity_id: Optional[int] = None, start_s: Optional[int] = None) -> Piece:
    """Auto-suggests when called with neither arg; a manual drag on the HR graph (task
    Part D.1) passes both, since the athlete has already picked which recording and where."""
    piece = session.get(Piece, piece_id)
    if piece is None:
        raise ValueError(f"No piece with id {piece_id}")
    if activity_id is not None and start_s is not None:
        _apply_alignment(session, piece, activity_id, start_s)
    elif not _auto_align(session, piece):
        raise ValueError("No sample-bearing recording long enough to align this piece against yet.")
    session.refresh(piece)
    _resolve_and_rescore(session, piece.canonical_id)
    return piece


# --- Part D.3: refine the activity's own zones/strain for the piece's window --------------


def power_member_and_samples(
    session: Session, canonical_id: int, members: list[Activity], power_member: Optional[Activity], power_samples: Optional[dict]
) -> tuple[Optional[Activity], Optional[dict]]:
    """Called from catch/sync/canonical.py's _resolve_zones. Overlays each aligned piece's
    own per-split watts onto its window — never a flat average over the whole window, and
    only where the real recording has no power there already (task Part D.3: "refines ...
    never double counts"). If no member has power at all, the first piece's window activity
    is used purely as a vessel so the overlay still reaches the zones pipeline — this never
    changes canonical.avg_power or any field-priority display value, only the power array
    this one resolve pass computes zones/strain from."""
    pieces = [p for p in list_pieces_for_canonical(session, canonical_id) if p.window_activity_id is not None and p.window_start_s is not None]
    if not pieces:
        return power_member, power_samples

    if power_member is None:
        target_id = pieces[0].window_activity_id
        power_member = next((m for m in members if m.id == target_id), None)
        if power_member is None or power_member.id is None:
            return None, None
        power_samples = _unpack(session, power_member.id)
        if power_samples is None:
            return power_member, None

    arr = list(power_samples["power"]) if power_samples and power_samples.get("power") else []
    needed = max((p.window_end_s or 0) for p in pieces if p.window_activity_id == power_member.id) if pieces else 0
    if len(arr) < needed:
        arr = arr + [None] * (needed - len(arr))

    for p in pieces:
        if p.window_activity_id != power_member.id or p.window_start_s is None:
            continue
        splits = json.loads(p.splits_json) if p.splits_json else []
        cum = 0.0
        for row in splits:
            split_s, watts = row.get("split_s"), row.get("watts")
            if split_s is None:
                continue
            if watts is not None:
                lo, hi = int(p.window_start_s + cum), int(p.window_start_s + cum + split_s)
                for i in range(lo, min(hi, len(arr))):
                    if arr[i] is None:
                        arr[i] = watts
            cum += split_s

    power_samples = dict(power_samples or {"hr": [], "cadence": []})
    power_samples["power"] = arr
    return power_member, power_samples


# --- Part D.4: a later Concept2 sync links real stroke data in place of the fallback -------


def _piece_matches_activity(piece: Piece, activity: Activity) -> bool:
    if piece.distance_m is None or piece.duration_s is None or activity.distance is None or activity.duration is None:
        return False
    tolerance_d = max(1.0, piece.distance_m * _ABSORB_DISTANCE_TOLERANCE_PCT)
    return abs(activity.distance - piece.distance_m) <= tolerance_d and abs(activity.duration - piece.duration_s) <= _ABSORB_DURATION_TOLERANCE_S


def _splits_from_concept2(session: Session, activity_id: int, interval_index: Optional[int] = None) -> list[dict]:
    """Real per-split rate/watts/hr averages, not just real split times — bucketing each
    stroke by its own cumulative time against the split boundaries `actual_splits` already
    computed (valid because `t` is cumulative *within* whichever one group this reads: either
    a single `interval_index`, or a whole activity that is itself effectively one piece — see
    this function's two call sites). Without this, an absorbed piece's splits carry real
    times but lose rate/watts/hr entirely, which (via power_member_and_samples, Part D.3)
    silently drops the power-zone-label refinement the moment a piece gets absorbed —
    the second advisor review's finding."""
    stmt = select(Stroke).where(Stroke.activity_id == activity_id)
    if interval_index is not None:
        stmt = stmt.where(Stroke.interval_index == interval_index)
    strokes = sorted(session.exec(stmt).all(), key=lambda s: s.seq)
    pieces_in = [{"t": s.t, "distance": s.distance, "watts": s.watts, "stroke_rate": s.stroke_rate, "pace_500m": s.pace_500m, "hr": s.hr} for s in strokes]
    total_distance = interval_summary(pieces_in)["distance_m"] or 0.0
    # actual_splits (catch/analytics/erg_test.py) wants {"distance_cum", "t_cum"} points, not
    # technique.py's {"distance", "t"} shape interval_summary just used above — within one
    # interval_index group (or a whole activity that's effectively one), a stroke's own
    # distance/t *is* already cumulative, so this is a rename, not a recomputation.
    cum_points = [{"distance_cum": s.distance, "t_cum": s.t} for s in strokes]
    rows = actual_splits(cum_points, total_distance)

    def _mean(bucket: list, attr: str) -> Optional[float]:
        values = [getattr(s, attr) for s in bucket if getattr(s, attr) is not None]
        return sum(values) / len(values) if values else None

    out = []
    prev_cum_s = 0.0
    for r in rows:
        hi = r["actual_cum_s"] if r["actual_cum_s"] is not None else prev_cum_s
        bucket = [s for s in strokes if s.t is not None and prev_cum_s - 1e-6 <= s.t <= hi + 1e-6]
        out.append(
            {
                "split_index": r["split_index"],
                "distance_m": r["distance_m"],
                "split_s": r["actual_split_s"],
                "rate": _mean(bucket, "stroke_rate"),
                "watts": _mean(bucket, "watts"),
                "hr": _mean(bucket, "hr"),
                # "concept2", not "typed" — real sensor data, but the same "never let a window
                # re-align overwrite this" protection applies (see _apply_alignment).
                "hr_source": "concept2" if _mean(bucket, "hr") is not None else None,
            }
        )
        prev_cum_s = hi
    return out


def _absorb(session: Session, piece: Piece, concept2_activity: Activity, interval_index: Optional[int] = None) -> None:
    piece.splits_json_fallback = piece.splits_json
    new_splits = _splits_from_concept2(session, concept2_activity.id, interval_index)
    if new_splits:
        piece.splits_json = json.dumps(new_splits)
        agg = aggregate_from_splits(new_splits)
        piece.distance_m = agg["distance_m"] or piece.distance_m
        piece.duration_s = agg["duration_s"] or piece.duration_s
        piece.avg_split_s = agg["avg_split_s"]
        piece.avg_rate = agg["avg_rate"] or piece.avg_rate
        piece.avg_watts = agg["avg_watts"] or piece.avg_watts
    piece.source = "concept2"
    piece.concept2_activity_id = concept2_activity.id
    piece.concept2_interval_index = interval_index
    session.add(piece)
    session.commit()
    logger.info("piece %s absorbed real Concept2 data from activity %s (interval=%s)", piece.id, concept2_activity.id, interval_index)


def absorb_concept2_piece_results(session: Session) -> int:
    """Run after every sync's matching pass (catch/sync/matching.py's run_matching), task Part
    D.4: "Concept2 stroke data wins, my typed or photo values are kept as a fallback, and
    nothing is counted twice." Two real shapes this covers:

    1. The PM5 result *is* the piece, synced as its own small activity — its duration ratio
       against the parent (much longer) session fails run_matching's [0.8, 1.25] candidate
       gate, so it never merges. **Never reassign its `canonical_id` onto the parent** — an
       earlier version of this function did, and a second advisor review caught that it
       silently corrupts the parent: resolve_canonical's field priority puts Concept2 first
       for start/duration/distance and prefers it for HR too (pick_hr), so a 90-minute
       session's own resolved fields would get overwritten by the absorbed 6-minute piece's.
       Instead, the short result's own (otherwise-orphan) canonical is marked
       `absorbed_into_piece_id` and `exclude_from_totals` and left exactly where it is — its
       Activity row, and the real strokes on it, are untouched, so power_member_and_samples
       can still read them via `piece.concept2_activity_id` without this canonical ever being
       read as "an activity" anywhere else (see that column's docstring in models.py).
    2. The PM5 ran the whole session and the piece is one of its own interval splits — the
       whole Concept2 result *did* merge normally (same canonical as the piece already), and
       this just finds which Stroke.interval_index group matches the piece's own signature.
    """
    absorbed = 0
    unlinked = session.exec(select(Piece).where(Piece.concept2_activity_id.is_(None), Piece.has_intervals.is_(False))).all()
    for piece in unlinked:
        canonical = session.get(CanonicalActivity, piece.canonical_id)
        if canonical is None or piece.distance_m is None or piece.duration_s is None:
            continue

        # Case 2: a Concept2 member already lives on this same canonical (whole-session
        # record) — look for a matching interval group inside its own strokes.
        same_canonical_concept2 = session.exec(
            select(Activity).where(Activity.canonical_id == piece.canonical_id, Activity.source == "concept2")
        ).first()
        if same_canonical_concept2 is not None and same_canonical_concept2.id is not None:
            indices = session.exec(
                select(Stroke.interval_index).where(Stroke.activity_id == same_canonical_concept2.id).distinct()
            ).all()
            matched_index = None
            for idx in indices:
                rows = session.exec(
                    select(Stroke).where(Stroke.activity_id == same_canonical_concept2.id, Stroke.interval_index == idx)
                ).all()
                summary = interval_summary(
                    [{"t": s.t, "distance": s.distance, "watts": s.watts, "stroke_rate": s.stroke_rate, "pace_500m": s.pace_500m, "hr": s.hr} for s in rows]
                )
                if summary["distance_m"] and summary["duration_s"] and abs(summary["distance_m"] - piece.distance_m) <= max(
                    1.0, piece.distance_m * _ABSORB_DISTANCE_TOLERANCE_PCT
                ) and abs(summary["duration_s"] - piece.duration_s) <= _ABSORB_DURATION_TOLERANCE_S:
                    matched_index = idx
                    break
            if matched_index is not None:
                _absorb(session, piece, same_canonical_concept2, matched_index)
                _resolve_and_rescore(session, piece.canonical_id)
                absorbed += 1
                continue

        # Case 1: search every *other* canonical's lone Concept2 member for the same local
        # day + distance/duration signature — skipping one already absorbed into some other
        # piece, or that already has company (not the lone-PM5-result shape this case is for).
        day = canonical.start.astimezone().date() if canonical.start else None
        if day is None:
            continue
        candidates = session.exec(
            select(Activity).where(Activity.source == "concept2", Activity.canonical_id != piece.canonical_id)
        ).all()
        for candidate in candidates:
            if candidate.start is None or candidate.start.astimezone().date() != day:
                continue
            candidate_canonical = session.get(CanonicalActivity, candidate.canonical_id)
            if candidate_canonical is None or candidate_canonical.absorbed_into_piece_id is not None:
                continue
            if not _piece_matches_activity(piece, candidate):
                continue

            # Leave candidate.canonical_id untouched (see the docstring above) — just flag its
            # own canonical as absorbed so it drops out of totals and every "an activity"
            # listing, without ever letting its short recording merge into the parent's.
            overrides = json.loads(candidate_canonical.overrides_json) if candidate_canonical.overrides_json else {}
            overrides["exclude_from_totals"] = True
            candidate_canonical.overrides_json = json.dumps(overrides)
            candidate_canonical.absorbed_into_piece_id = piece.id
            session.add(candidate_canonical)
            session.add(
                MergeLog(
                    canonical_id=piece.canonical_id,
                    source=candidate.source,
                    external_id=candidate.external_id,
                    action="absorbed_into_piece",
                    reason=f"piece {piece.id}",
                )
            )
            session.commit()
            _absorb(session, piece, candidate)
            _resolve_and_rescore(session, piece.canonical_id)
            absorbed += 1
            break
    return absorbed


# --- Feeds the rowing-watts-2k threshold and predicted-2k ensemble (task Part D.2's power-
# zone label needs a real watts_2k number, which this real account's history otherwise has no
# Concept2 data to produce at all — see catch/sync/rowing_predict.py) -----------------------


def piece_pb_candidates(session: Session) -> list[dict]:
    """Every confirmed piece, as a PB candidate alongside Concept2 Activity rows (task Part
    A.1: "pieces count in the test center like Concept2 results" — this is the PB half of
    that). Excludes any piece Part D.4 already absorbed into a real Concept2 result, whose
    own Activity row is already a PB candidate via the normal path."""
    pieces = session.exec(select(Piece).where(Piece.concept2_activity_id.is_(None), Piece.has_intervals.is_(False))).all()
    out = []
    for p in pieces:
        if not p.distance_m or not p.duration_s:
            continue
        canonical = session.get(CanonicalActivity, p.canonical_id)
        out.append(
            {
                "distance": p.distance_m,
                "duration": p.duration_s,
                "date": canonical.start.date().isoformat() if canonical and canonical.start else None,
                "canonical_id": p.canonical_id,
                "piece_id": p.id,
            }
        )
    return out


def confirmed_piece_pace_candidates(session: Session, cutoff: datetime) -> list[dict]:
    """Distance/duration pairs from confirmed pieces, in the same bucket shape
    catch/sync/rowing_predict.py's recent_rower_pieces builds from real Concept2 results.
    Excludes any piece already absorbed into a real Concept2 result (Part D.4) — that result
    is already counted via the normal Concept2 path, so including the piece too would count
    the same effort twice. Filtered (and labelled) by the *containing activity's* own date,
    not `Piece.created_at` — a piece added well after the fact (reviewing an old photo, say)
    must be judged by when the effort happened, not when it was typed in, exactly like every
    other "recent" window in this app (predict_lookback_days elsewhere always means the
    activity's date)."""
    pieces = session.exec(select(Piece).where(Piece.concept2_activity_id.is_(None), Piece.has_intervals.is_(False), Piece.distance_m >= 1000)).all()
    out = []
    for p in pieces:
        if not p.duration_s:
            continue
        canonical = session.get(CanonicalActivity, p.canonical_id)
        if canonical is None or canonical.start is None or canonical.start < cutoff:
            continue
        out.append({"distance_m": p.distance_m, "duration_s": p.duration_s, "label": canonical.start.date().isoformat()})
    return out
