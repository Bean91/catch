from __future__ import annotations

"""Session 33: merge several workouts into one ("combine") — preview, merge, undo (docs/analytics.md §31).

A combined workout keeps every source record (`Activity`) untouched; only which workout they belong to changes. The resolver
(catch/sync/canonical.py, merge_mode "combined") groups them by time overlap and adds across groups, so nothing is dropped or
counted twice. Everything that pointed at a merged-away workout follows the survivor, and what it was is snapshotted on the
MergeLog row so undo can give each one back. Owner scoping is the ORM tenant filter: another account's ids simply aren't found."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.activity_merge import check_compatible, cluster, overlaps, span_of
from catch.core.models import Activity, CanonicalActivity, MatchDecision, MergeLog, Piece

COMBINED = "combined"


class MergeError(ValueError):
    def __init__(self, message: str, status: int = 422, reasons: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.reasons = reasons or [message]


def _overrides(c: CanonicalActivity) -> dict:
    try:
        return json.loads(c.overrides_json) if c.overrides_json else {}
    except ValueError:
        return {}


def _members(session: Session, canonical_id: int) -> list[Activity]:
    return list(session.exec(select(Activity).where(Activity.canonical_id == canonical_id).order_by(Activity.start)).all())


def _published(session: Session, canonical_id: int) -> bool:
    from catch.core.models import ResultPublication

    return session.exec(select(ResultPublication.id).where(ResultPublication.canonical_id == canonical_id)).first() is not None


def _load(session: Session, ids: list[int]) -> list[CanonicalActivity]:
    ids = list(dict.fromkeys(ids))
    rows = []
    for cid in ids:
        c = session.get(CanonicalActivity, cid)
        if c is None:
            raise MergeError("One of these workouts wasn't found.", status=404)
        rows.append(c)
    return rows


def _item(session: Session, c: CanonicalActivity) -> dict:
    from catch.core.models import ActivitySamples

    members = _members(session, c.id)
    o = _overrides(c)
    split = c.duration / c.distance * 500 if c.sport_family == "rowing" and c.duration and c.distance else None
    return {
        "id": c.id,
        "title": c.title,
        "sport_family": c.sport_family,
        "category": c.category,
        "start": c.start,
        "local_date": c.local_date,
        "local_tz": c.local_tz,
        "duration": c.duration,
        "distance": c.distance,
        "avg_hr": c.avg_hr,
        "max_hr": c.max_hr,
        "avg_power": c.avg_power,
        "avg_split_500m": split,
        "calories": c.calories,
        "strain_trimp": c.strain_trimp,
        "sources": [{"source": m.source, "external_id": m.external_id, "activity_id": m.id} for m in members],
        "has_samples": any(session.get(ActivitySamples, m.id) is not None for m in members),
        "merge_mode": c.merge_mode,
        "test_type": o.get("test_type") if "test" in (o.get("tags") or []) else None,
        "published": _published(session, c.id),
        "absorbed": c.absorbed_into_piece_id is not None,
    }


def _hash(canonicals: list[CanonicalActivity]) -> str:
    raw = "|".join(f"{c.id}:{c.updated_at.isoformat() if c.updated_at else ''}" for c in sorted(canonicals, key=lambda c: c.id))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _merged_overrides(ordered: list[CanonicalActivity]) -> dict:
    """The kept (earliest) workout's edits win; tags are combined, notes joined, a test mark carried over from whichever had one."""
    out = dict(_overrides(ordered[0]))
    tags = list(out.get("tags") or [])
    notes = [out["notes"]] if out.get("notes") else []
    for c in ordered[1:]:
        o = _overrides(c)
        for t in o.get("tags") or []:
            if t not in tags:
                tags.append(t)
        if o.get("notes"):
            notes.append(o["notes"])
        for key in ("test_type", "rpe", "sport_family", "title"):
            if key not in out and key in o:
                out[key] = o[key]
    if tags:
        out["tags"] = tags
    if notes:
        out["notes"] = "\n\n".join(notes)
    return out


def preview(session: Session, canonical_ids: list[int]) -> dict:
    """What merging these would produce — computed by the real resolver on an unsaved workout, so it writes nothing."""
    from catch.sync.canonical import compute_resolution

    rows = _load(session, canonical_ids)
    items = [_item(session, c) for c in rows]
    reasons = check_compatible(items)
    if any(i["absorbed"] for i in items):
        reasons.append("One of these is a Concept2 result already linked to a piece, so it isn't a workout of its own.")
    ordered = sorted(rows, key=lambda c: (c.start or datetime.max.replace(tzinfo=timezone.utc), c.id))
    spans = [s for s in (span_of(i["id"], i["start"], i["duration"]) for i in items) if s is not None]
    out = {
        "compatible": not reasons,
        "reasons": reasons,
        "items": sorted(items, key=lambda i: (i["start"] or datetime.max.replace(tzinfo=timezone.utc), i["id"])),
        "overlaps": overlaps(spans),
        "groups": [[s.key for s in g] for g in cluster(spans)],
        "keep_id": ordered[0].id if ordered else None,
        "preview_hash": _hash(rows),
        "result": None,
        "separate_strain_trimp": sum(i["strain_trimp"] or 0 for i in items),
    }
    if reasons:
        return out
    members = [m for c in rows for m in _members(session, c.id)]
    trial = CanonicalActivity(merge_mode=COMBINED, overrides_json=json.dumps(_merged_overrides(ordered)), sport_family=ordered[0].sport_family)
    info = compute_resolution(session, trial, members)
    zones = json.loads(trial.zones_json) if trial.zones_json else None
    out["result"] = {
        "title": trial.title,
        "sport_family": trial.sport_family,
        "start": trial.start,
        "local_date": trial.local_date,
        "local_tz": trial.local_tz,
        "duration": trial.duration,
        "distance": trial.distance,
        "distance_partial": bool(json.loads(trial.field_sources_json or "{}").get("distance_partial")),
        "avg_hr": trial.avg_hr,
        "max_hr": trial.max_hr,
        "avg_power": trial.avg_power,
        "avg_split_500m": trial.duration / trial.distance * 500 if trial.sport_family == "rowing" and trial.duration and trial.distance else None,
        "calories": trial.calories,
        "strain_trimp": trial.strain_trimp,
        "session_label": trial.session_label,
        "zones": (zones or {}).get("hr"),
        "parts": [{"start": p["start"], "duration": p["duration"], "distance": p["distance"], "recordings": len(p["members"])} for p in info["parts"]],
    }
    return out


def _refs(session: Session, canonical_id: int) -> dict:
    from catch.core.models import CoachFeedback, Event, PlannedWorkout, ResultPublication, TechniqueNote

    def ids(model, column) -> list[int]:
        return list(session.exec(select(model.id).where(column == canonical_id)).all())

    return {
        "pieces": ids(Piece, Piece.canonical_id),
        "planned": ids(PlannedWorkout, PlannedWorkout.linked_canonical_id),
        "notes": ids(TechniqueNote, TechniqueNote.canonical_id),
        "feedback": ids(CoachFeedback, CoachFeedback.canonical_id),
        "publications": ids(ResultPublication, ResultPublication.canonical_id),
        "event_results": ids(Event, Event.result_canonical_id),
    }


def move_references(session: Session, keep_id: int, drop_id: int) -> None:
    """Everything that points at `drop` follows `keep` — pieces and publications as well as plans, notes and feedback (the
    automatic duplicate merge used to leave pieces and publications pointing at a deleted workout)."""
    from catch.core.models import ResultPublication
    from catch.sync.coaching_notes import repoint_canonical
    from catch.sync.planning import relink_after_merge

    relink_after_merge(session, keep_id, drop_id)
    repoint_canonical(session, keep_id, drop_id)
    for piece in session.exec(select(Piece).where(Piece.canonical_id == drop_id)).all():
        piece.canonical_id = keep_id
        session.add(piece)
    for pub in session.exec(select(ResultPublication).where(ResultPublication.canonical_id == drop_id)).all():
        pub.canonical_id = keep_id
        session.add(pub)
    from catch.core.models import Event

    # Session 36: an event's linked result follows the workout it was done in.
    for ev in session.exec(select(Event).where(Event.result_canonical_id == drop_id)).all():
        ev.result_canonical_id = keep_id
        session.add(ev)


def combine(session: Session, canonical_ids: list[int], preview_hash: str) -> CanonicalActivity:
    from catch.sync.canonical import resolve_canonical
    from catch.sync.scoring import recompute_scores

    rows = _load(session, canonical_ids)
    if _hash(rows) != preview_hash:
        raise MergeError("These workouts changed since the preview — review the merge again.", status=409)
    check = preview(session, canonical_ids)
    if not check["compatible"]:
        raise MergeError(check["reasons"][0], reasons=check["reasons"])
    ordered = sorted(rows, key=lambda c: (c.start or datetime.max.replace(tzinfo=timezone.utc), c.id))
    keep, drops = ordered[0], ordered[1:]

    def snap(c: CanonicalActivity) -> dict:
        return {
            "id": c.id,
            "overrides_json": c.overrides_json,
            "merge_mode": c.merge_mode,
            "sport_family": c.sport_family,
            "members": [[m.source, m.external_id] for m in _members(session, c.id)],
            **_refs(session, c.id),
        }

    snapshot = {"keep": snap(keep), "dropped": [snap(c) for c in drops]}
    merged = _merged_overrides(ordered)
    try:
        for drop in drops:
            for m in _members(session, drop.id):
                m.canonical_id = keep.id
                session.add(m)
            move_references(session, keep.id, drop.id)
            session.flush()
            session.delete(drop)
        keep.overrides_json = json.dumps(merged) if merged else None
        keep.merge_mode = COMBINED
        first = snapshot["keep"]["members"][0] if snapshot["keep"]["members"] else ["catch", str(keep.id)]
        session.add(
            MergeLog(canonical_id=keep.id, source=first[0], external_id=first[1], action="combine",
                     reason=f"combined {len(rows)} workouts", snapshot_json=json.dumps(snapshot))
        )
        session.add(keep)
        session.commit()
    except Exception:
        session.rollback()
        raise
    merged_canonical = resolve_canonical(session, keep.id)
    _refresh_piece_zones(session, keep.id)
    recompute_scores(session)
    return merged_canonical


def latest_combine(session: Session, canonical_id: int) -> Optional[MergeLog]:
    return session.exec(
        select(MergeLog).where(MergeLog.canonical_id == canonical_id, MergeLog.action == "combine").order_by(MergeLog.id.desc())
    ).first()


def uncombine(session: Session, canonical_id: int) -> list[int]:
    """Gives each merged-away workout back: its own recordings, edits, pieces, plan link, notes, feedback and publication. Returns
    every resulting workout id (the kept one first). Recordings that joined later (a new duplicate synced afterwards) stay with the
    kept workout. A `split` decision between the groups stops the matcher from ever re-merging them on its own."""
    from catch.core.models import CoachFeedback, PlannedWorkout, ResultPublication, TechniqueNote
    from catch.sync.canonical import resolve_canonical
    from catch.sync.scoring import recompute_scores

    keep = session.get(CanonicalActivity, canonical_id)
    if keep is None:
        raise MergeError("Workout not found.", status=404)
    if keep.merge_mode != COMBINED:
        raise MergeError("This workout wasn't merged from separate workouts, so there's nothing to undo.")
    log = latest_combine(session, canonical_id)
    if log is None or not log.snapshot_json:
        raise MergeError("The record of this merge is missing, so it can't be undone automatically. Split off a recording instead.")
    snapshot = json.loads(log.snapshot_json)
    current = {(m.source, m.external_id): m for m in _members(session, keep.id)}
    restored: list[int] = [keep.id]
    groups: list[list[Activity]] = [[current[k] for k in map(tuple, snapshot["keep"]["members"]) if k in current]]
    from catch.core.models import Event

    moves = ((Piece, "canonical_id", "pieces"), (PlannedWorkout, "linked_canonical_id", "planned"), (TechniqueNote, "canonical_id", "notes"),
             (CoachFeedback, "canonical_id", "feedback"), (ResultPublication, "canonical_id", "publications"),
             (Event, "result_canonical_id", "event_results"))
    try:
        for part in snapshot["dropped"]:
            mine = [current[k] for k in map(tuple, part["members"]) if k in current]
            if not mine:
                continue  # every recording of this one was deleted since — nothing to give back
            c = CanonicalActivity(sport_family=part.get("sport_family"), overrides_json=part.get("overrides_json"), merge_mode=part.get("merge_mode"))
            session.add(c)
            session.flush()
            for m in mine:
                m.canonical_id = c.id
                session.add(m)
            for model, column, key in moves:
                for ref_id in part.get(key) or []:
                    row = session.get(model, ref_id)
                    if row is not None and getattr(row, column) == keep.id:
                        setattr(row, column, c.id)
                        session.add(row)
            groups.append(mine)
            restored.append(c.id)
        keep.overrides_json = snapshot["keep"].get("overrides_json")
        keep.merge_mode = snapshot["keep"].get("merge_mode")
        session.add(keep)
        _record_splits(session, groups)
        session.add(MergeLog(canonical_id=keep.id, source=log.source, external_id=log.external_id, action="uncombine", reason=f"undid merge {log.id}"))
        session.commit()
    except Exception:
        session.rollback()
        raise
    for cid in restored:
        resolve_canonical(session, cid)
        _refresh_piece_zones(session, cid)
    recompute_scores(session)
    return restored


def _record_splits(session: Session, groups: list[list[Activity]]) -> None:
    from catch.sync.matching import _decision_key

    for i, a_group in enumerate(groups):
        for b_group in groups[i + 1:]:
            for a in a_group:
                for b in b_group:
                    sa, ea, sb, eb = _decision_key(a, b)
                    existing = session.exec(
                        select(MatchDecision).where(MatchDecision.source_a == sa, MatchDecision.external_id_a == ea, MatchDecision.source_b == sb, MatchDecision.external_id_b == eb)
                    ).first()
                    if existing is None:
                        session.add(MatchDecision(source_a=sa, external_id_a=ea, source_b=sb, external_id_b=eb, decision="split"))
                    elif existing.decision != "split":
                        existing.decision = "split"
                        session.add(existing)


def _refresh_piece_zones(session: Session, canonical_id: int) -> None:
    from catch.sync.piece import refresh_piece_zones

    for piece in session.exec(select(Piece).where(Piece.canonical_id == canonical_id, Piece.window_activity_id.is_not(None))).all():
        refresh_piece_zones(session, piece)


def merge_summary(session: Session, canonical: CanonicalActivity) -> Optional[dict]:
    """For workout detail: how many recordings a combined workout was built from, and whether it can be undone."""
    if canonical.merge_mode != COMBINED:
        return None
    log = latest_combine(session, canonical.id)
    snapshot = json.loads(log.snapshot_json) if log and log.snapshot_json else None
    return {
        "recordings": len(_members(session, canonical.id)),
        "merged_workouts": 1 + len(snapshot["dropped"]) if snapshot else None,
        "merged_at": log.created_at if log else None,
        "can_undo": snapshot is not None,
    }
