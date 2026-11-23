from __future__ import annotations

"""The DB-facing half of the matching engine (catch/analytics/matching.py has the pure
scoring). Every new Activity gets its own 1:1 CanonicalActivity at insert time
(catch/sync/upsert.py); this module finds pairs that should actually be the same physical
session and merges their canonicals — run after every sync and as a one-off backfill over
all history (task Part A.4), both idempotent (a pair that already shares a canonical, or one
a human has explicitly marked "not a duplicate", is never reconsidered)."""

import json
import logging
from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import defer
from sqlmodel import Session, select

from catch.analytics.matching import MatchInput, MatchResult, is_indoor, match_pair
from catch.analytics.matching import sport_family as _sport_family
from catch.core.models import Activity, CanonicalActivity, MatchDecision, MergeLog
from catch.sync.canonical import resolve_canonical

logger = logging.getLogger("catch.matching")


def ensure_canonicals(session: Session) -> int:
    """Defensive catch-up: `catch.sync.upsert.upsert_activity` always gives a new row its own
    canonical immediately, but a row created any other way (older fixtures, a direct DB
    write, a future migration gap) won't have one — give it a standalone 1:1 canonical so
    every downstream reader can join on `canonical_id` unconditionally. Idempotent; a no-op
    once every row has one."""
    orphans = session.exec(select(Activity).where(Activity.canonical_id.is_(None))).all()
    for row in orphans:
        if row.sport_family is None:
            row.sport_family = _sport_family(row.source, row.type)
        canonical = CanonicalActivity(sport_family=row.sport_family)
        session.add(canonical)
        session.flush()
        row.canonical_id = canonical.id
        session.add(row)
    if orphans:
        session.commit()
        for row in orphans:
            resolve_canonical(session, row.canonical_id)
    return len(orphans)


def _decision_key(a: Activity, b: Activity) -> tuple[str, str, str, str]:
    pair = sorted([(a.source, a.external_id), (b.source, b.external_id)])
    return pair[0][0], pair[0][1], pair[1][0], pair[1][1]


def _to_match_input(a: Activity) -> MatchInput:
    # A Peloton-pushed Garmin activity is always indoor cycling (task Part B.2), regardless
    # of whatever Garmin typed the import as — is_indoor's generic source/type table has no
    # way to know that; only the sync-layer origin flag does.
    indoor = True if a.origin == "peloton" else is_indoor(a.source, a.type)
    return MatchInput(
        source=a.source,
        external_id=a.external_id,
        sport_family=a.sport_family or "other",
        indoor=indoor,
        start=a.start,
        duration=a.duration,
    )


def find_candidate_pairs(session: Session) -> list[tuple[Activity, Activity, MatchResult]]:
    """All non-blocked candidate pairs across *different* canonicals, highest score first.
    Activities are bucketed by local calendar date (+/- 1 day) before scoring — the matching
    rule's own 3-minute/70%-overlap window means anything further apart always scores 0, so
    this is a cheap prefilter, not a correctness-affecting one, at this app's single-user
    scale (a few hundred activities at most)."""
    # raw_json is never read here; deferring it keeps a three-year history's provider payloads out of memory (session 32).
    rows = session.exec(select(Activity).options(defer(Activity.raw_json)).where(Activity.start.is_not(None))).all()
    # Every blocking decision, read once — this used to be one query per candidate pair, twice per recompute (session 32).
    blocked = {
        (d.source_a, d.external_id_a, d.source_b, d.external_id_b)
        for d in session.exec(select(MatchDecision).where(MatchDecision.decision.in_(["not_duplicate", "split"]))).all()
    }
    by_day: dict = defaultdict(list)
    for a in rows:
        # A prefilter only (pairs further apart than minutes always score 0), so any one consistent calendar works: the UTC one.
        day = a.start.date()
        for offset in (-1, 0, 1):
            by_day[day + timedelta(days=offset)].append(a)

    # Session 33: a combined workout's members are parts of one session — compare a new recording with the whole session's span,
    # so one that covers it is flagged for review (never auto-merged: it would overlap several parts at once).
    combined_ids = set(session.exec(select(CanonicalActivity.id).where(CanonicalActivity.merge_mode == "combined")).all())
    combined_spans: dict = {}
    for a in rows:
        if a.canonical_id in combined_ids and a.start is not None:
            end = a.start + timedelta(seconds=a.duration or 0)
            lo, hi = combined_spans.get(a.canonical_id, (a.start, end))
            combined_spans[a.canonical_id] = (min(lo, a.start), max(hi, end))
    combined_spans = {cid: (lo, (hi - lo).total_seconds()) for cid, (lo, hi) in combined_spans.items()}

    seen_pairs: set[tuple[int, int]] = set()
    results: list[tuple[Activity, Activity, MatchResult]] = []
    for day, candidates in by_day.items():
        for i, a in enumerate(candidates):
            for b in candidates[i + 1 :]:
                if a.id == b.id or a.canonical_id == b.canonical_id:
                    continue
                pair_key = (min(a.id, b.id), max(a.id, b.id))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                if _decision_key(a, b) in blocked:
                    continue
                result = match_pair(_to_match_input(a), _to_match_input(b))
                if not result.is_candidate and (a.canonical_id in combined_spans or b.canonical_id in combined_spans):
                    # Not a duplicate of any one part — but it may cover the whole merged session (another device that ran
                    # throughout). Flag that for review; joining it would overlap several parts at once.
                    spanning = match_pair(_span_input(a, combined_spans), _span_input(b, combined_spans))
                    if not spanning.is_candidate:
                        continue
                    result = MatchResult(True, spanning.score, True, [*spanning.reasons, "covers a merged workout — review it, never merged automatically"])
                if result.is_candidate and result.score >= 0.0:
                    results.append((a, b, result))
    results.sort(key=lambda r: r[2].score, reverse=True)
    return results


def _span_input(a: Activity, combined_spans: dict) -> MatchInput:
    base = _to_match_input(a)
    span = combined_spans.get(a.canonical_id)
    if span is None:
        return base
    from dataclasses import replace

    return replace(base, start=span[0], duration=span[1])


def _merge_canonicals(session: Session, keep: CanonicalActivity, drop: CanonicalActivity, members_of_drop: list[Activity]) -> None:
    for m in members_of_drop:
        m.canonical_id = keep.id
        session.add(m)
    # Everything linked to the canonical being deleted follows the survivor: plans, notes, feedback, and (session 33 — they used to
    # be left pointing at the deleted row) pieces and leaderboard publications.
    from catch.sync.activity_merge import move_references

    move_references(session, keep.id, drop.id)
    if drop.overrides_json and drop.overrides_json != "{}" and keep.overrides_json != drop.overrides_json:
        # Both had edits: keep the survivor's, but don't silently lose the dropped side's tags and notes.
        from catch.sync.activity_merge import _merged_overrides

        keep.overrides_json = json.dumps(_merged_overrides([keep, drop]))
        session.add(keep)
    session.flush()
    session.delete(drop)
    session.commit()


def _choose_surviving(session: Session, canonical_a: CanonicalActivity, canonical_b: CanonicalActivity) -> tuple[CanonicalActivity, CanonicalActivity]:
    """Never delete a canonical that carries user overrides if the other one doesn't."""
    a_has_overrides = bool(canonical_a.overrides_json and canonical_a.overrides_json != "{}")
    b_has_overrides = bool(canonical_b.overrides_json and canonical_b.overrides_json != "{}")
    if b_has_overrides and not a_has_overrides:
        return canonical_b, canonical_a
    return canonical_a, canonical_b


def apply_auto_merges(session: Session, pairs: list[tuple[Activity, Activity, MatchResult]]) -> dict:
    auto_merged = 0
    flagged = 0
    merged_canonical_ids: set[int] = set()
    for a, b, result in pairs:
        # Refresh canonical ids — an earlier pair in this same batch may have already merged
        # one of these two activities into a different canonical.
        session.refresh(a)
        session.refresh(b)
        if a.canonical_id == b.canonical_id:
            continue
        if not result.auto_merge:
            if result.flagged:
                flagged += 1
            continue

        canonical_a = session.get(CanonicalActivity, a.canonical_id)
        canonical_b = session.get(CanonicalActivity, b.canonical_id)
        if canonical_a is None or canonical_b is None:
            continue
        keep, drop = _choose_surviving(session, canonical_a, canonical_b)
        drop_members = session.exec(select(Activity).where(Activity.canonical_id == drop.id)).all()
        _merge_canonicals(session, keep, drop, drop_members)

        for member, other in ((a, b), (b, a)):
            session.add(
                MergeLog(
                    canonical_id=keep.id,
                    source=member.source,
                    external_id=member.external_id,
                    action="auto_merge",
                    score=result.score,
                    reason=f"matched {other.source}:{other.external_id}",
                )
            )
        session.commit()
        resolve_canonical(session, keep.id)
        merged_canonical_ids.add(keep.id)
        auto_merged += 1
        logger.info("auto-merged %s:%s with %s:%s (score=%.2f)", a.source, a.external_id, b.source, b.external_id, result.score)

    return {"auto_merged": auto_merged, "flagged": flagged}


def _resolve_blank_canonicals(session: Session) -> int:
    """`_migrate_linked_activities_to_canonical` (catch/core/db.py) creates a canonical for
    every pre-session-12 activity but never resolves it — `ensure_canonicals` only resolves
    *orphans* (no canonical at all) and `apply_auto_merges` only resolves *merged* pairs, so
    a migrated-but-never-merged activity's canonical would otherwise stay permanently blank
    (no start/duration/avg_hr), silently vanishing from every date-filtered reader. Catches
    up any canonical with no `start` at all; idempotent, self-healing on every run."""
    blank = session.exec(select(CanonicalActivity).where(CanonicalActivity.start.is_(None))).all()
    for canonical in blank:
        if session.exec(select(Activity).where(Activity.canonical_id == canonical.id)).first() is not None:
            resolve_canonical(session, canonical.id)
    return len(blank)


def run_matching(session: Session) -> dict:
    ensure_canonicals(session)
    _resolve_blank_canonicals(session)
    pairs = find_candidate_pairs(session)
    result = apply_auto_merges(session, pairs)
    remaining = find_candidate_pairs(session)
    result["flagged"] = sum(1 for _, _, r in remaining if r.flagged and not r.auto_merge)

    # Session 17 (see PLAN.md Part D.4): after the ordinary merge pass above (which a PM5
    # piece's own short Concept2 result almost always fails, on duration ratio alone — see
    # that function's docstring), absorb any piece a Concept2 sync now has real stroke data
    # for.
    from catch.sync.piece import absorb_concept2_piece_results

    result["pieces_absorbed"] = absorb_concept2_piece_results(session)
    return result


def list_flagged_duplicates(session: Session) -> list[dict]:
    pairs = find_candidate_pairs(session)
    out = []
    for a, b, result in pairs:
        if result.flagged and not result.auto_merge:
            out.append(
                {
                    "a": {"activity_id": a.id, "source": a.source, "external_id": a.external_id, "start": a.start, "duration": a.duration},
                    "b": {"activity_id": b.id, "source": b.source, "external_id": b.external_id, "start": b.start, "duration": b.duration},
                    "score": result.score,
                    "hard_block": result.hard_block,
                    "reasons": result.reasons,
                }
            )
    return out


def manual_merge(session: Session, activity_id_a: int, activity_id_b: int) -> CanonicalActivity:
    a = session.get(Activity, activity_id_a)
    b = session.get(Activity, activity_id_b)
    if a is None or b is None:
        raise ValueError("activity not found")
    if a.canonical_id == b.canonical_id:
        canonical = session.get(CanonicalActivity, a.canonical_id)
        return resolve_canonical(session, canonical.id)

    canonical_a = session.get(CanonicalActivity, a.canonical_id)
    canonical_b = session.get(CanonicalActivity, b.canonical_id)
    if "combined" in (canonical_a.merge_mode, canonical_b.merge_mode):
        from catch.sync.activity_merge import MergeError

        raise MergeError("One of these is a merged workout. Undo that merge first, then merge all the workouts together from Workouts → Select.")
    keep, drop = _choose_surviving(session, canonical_a, canonical_b)
    drop_members = session.exec(select(Activity).where(Activity.canonical_id == drop.id)).all()
    _merge_canonicals(session, keep, drop, drop_members)
    for member, other in ((a, b), (b, a)):
        session.add(
            MergeLog(
                canonical_id=keep.id,
                source=member.source,
                external_id=member.external_id,
                action="manual_merge",
                reason=f"manually merged with {other.source}:{other.external_id}",
            )
        )
    session.commit()
    return resolve_canonical(session, keep.id)


def split_activity(session: Session, activity_id: int) -> CanonicalActivity:
    """Gives `activity_id` back its own standalone canonical and records a MatchDecision so
    the matching engine never silently re-merges it with its former canonical-mates on the
    next sync (task Part A.5's "split ... staying split after re-sync")."""
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise ValueError("activity not found")
    old_canonical_id = activity.canonical_id
    siblings = session.exec(
        select(Activity).where(Activity.canonical_id == old_canonical_id, Activity.id != activity_id)
    ).all()

    new_canonical = CanonicalActivity(sport_family=activity.sport_family)
    session.add(new_canonical)
    session.flush()
    activity.canonical_id = new_canonical.id
    session.add(activity)

    for sibling in siblings:
        sa, ea, sb, eb = _decision_key(activity, sibling)
        existing = session.exec(
            select(MatchDecision).where(
                MatchDecision.source_a == sa,
                MatchDecision.external_id_a == ea,
                MatchDecision.source_b == sb,
                MatchDecision.external_id_b == eb,
            )
        ).first()
        if existing is None:
            session.add(MatchDecision(source_a=sa, external_id_a=ea, source_b=sb, external_id_b=eb, decision="split"))

    session.add(
        MergeLog(canonical_id=new_canonical.id, source=activity.source, external_id=activity.external_id, action="split")
    )
    session.commit()

    if old_canonical_id is not None and siblings:
        resolve_canonical(session, old_canonical_id)
    resolve_canonical(session, new_canonical.id)
    return new_canonical


def mark_not_duplicate(session: Session, activity_id_a: int, activity_id_b: int) -> None:
    a = session.get(Activity, activity_id_a)
    b = session.get(Activity, activity_id_b)
    if a is None or b is None:
        raise ValueError("activity not found")
    sa, ea, sb, eb = _decision_key(a, b)
    existing = session.exec(
        select(MatchDecision).where(
            MatchDecision.source_a == sa,
            MatchDecision.external_id_a == ea,
            MatchDecision.source_b == sb,
            MatchDecision.external_id_b == eb,
        )
    ).first()
    if existing is not None:
        existing.decision = "not_duplicate"
        session.add(existing)
    else:
        session.add(MatchDecision(source_a=sa, external_id_a=ea, source_b=sb, external_id_b=eb, decision="not_duplicate"))
    session.commit()


_COMPARE_FIELDS = ("start", "duration", "distance", "avg_hr", "max_hr", "avg_power", "avg_cadence", "calories")


def merge_preview(session: Session, activity_id_a: int, activity_id_b: int) -> dict:
    """Session 36: what merging two possible duplicates would give, before anything is written — each side's own figures, which
    recording each merged figure would come from (the real field-priority resolver, run on an unsaved workout), how much the two
    overlap, the matcher's reasons, and what moves with the merge. Both recordings are kept either way, and either can be split off
    again later."""
    from catch.sync.activity_merge import _merged_overrides, _refs
    from catch.sync.canonical import compute_resolution

    a = session.get(Activity, activity_id_a)
    b = session.get(Activity, activity_id_b)
    if a is None or b is None:
        raise ValueError("activity not found")
    ca, cb = session.get(CanonicalActivity, a.canonical_id), session.get(CanonicalActivity, b.canonical_id)
    if ca is None or cb is None:
        raise ValueError("activity not found")

    def side(x: Activity) -> dict:
        return {
            "activity_id": x.id, "source": x.source, "external_id": x.external_id, "type": x.type, "sport_family": x.sport_family,
            **{f: getattr(x, f) for f in _COMPARE_FIELDS},
        }

    result = match_pair(_to_match_input(a), _to_match_input(b))
    overlap_s = None
    if a.start and b.start and a.duration and b.duration:
        lo = max(a.start, b.start)
        hi = min(a.start + timedelta(seconds=a.duration), b.start + timedelta(seconds=b.duration))
        overlap_s = max((hi - lo).total_seconds(), 0.0)
    same = ca.id == cb.id
    blocked = None
    if "combined" in (ca.merge_mode, cb.merge_mode) and not same:
        blocked = "One of these is a merged workout. Undo that merge first, then merge all the workouts together from Workouts → Select."
    out = {
        "a": side(a), "b": side(b), "score": result.score, "reasons": result.reasons, "hard_block": result.hard_block,
        "overlap_s": overlap_s, "already_merged": same, "blocked_reason": blocked, "merged": None,
    }
    if same or blocked:
        return out
    keep, drop = _choose_surviving(session, ca, cb)
    members = list(session.exec(select(Activity).where(Activity.canonical_id.in_([ca.id, cb.id]))).all())
    trial = CanonicalActivity(overrides_json=json.dumps(_merged_overrides([keep, drop])), sport_family=keep.sport_family)
    compute_resolution(session, trial, members)
    sources = json.loads(trial.field_sources_json or "{}")
    moves = _refs(session, drop.id)
    out["merged"] = {
        "values": {f: getattr(trial, f) for f in _COMPARE_FIELDS},
        "from": {f: sources.get(f) for f in _COMPARE_FIELDS},
        "recordings": len(members),
        "kept_workout_id": keep.id,
        "moves": {k: len(v) for k, v in moves.items() if v},
    }
    return out
