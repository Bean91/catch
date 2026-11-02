from __future__ import annotations

"""The DB-facing half of the matching engine (catch/analytics/matching.py has the pure
scoring). Every new Activity gets its own 1:1 CanonicalActivity at insert time
(catch/sync/upsert.py); this module finds pairs that should actually be the same physical
session and merges their canonicals — run after every sync and as a one-off backfill over
all history (task Part A.4), both idempotent (a pair that already shares a canonical, or one
a human has explicitly marked "not a duplicate", is never reconsidered)."""

import logging
from collections import defaultdict
from datetime import timedelta

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


def _blocked(session: Session, a: Activity, b: Activity) -> bool:
    sa, ea, sb, eb = _decision_key(a, b)
    row = session.exec(
        select(MatchDecision).where(
            MatchDecision.source_a == sa,
            MatchDecision.external_id_a == ea,
            MatchDecision.source_b == sb,
            MatchDecision.external_id_b == eb,
            MatchDecision.decision.in_(["not_duplicate", "split"]),
        )
    ).first()
    return row is not None


def _to_match_input(a: Activity) -> MatchInput:
    return MatchInput(
        source=a.source,
        external_id=a.external_id,
        sport_family=a.sport_family or "other",
        indoor=is_indoor(a.source, a.type),
        start=a.start,
        duration=a.duration,
    )


def find_candidate_pairs(session: Session) -> list[tuple[Activity, Activity, MatchResult]]:
    """All non-blocked candidate pairs across *different* canonicals, highest score first.
    Activities are bucketed by local calendar date (+/- 1 day) before scoring — the matching
    rule's own 3-minute/70%-overlap window means anything further apart always scores 0, so
    this is a cheap prefilter, not a correctness-affecting one, at this app's single-user
    scale (a few hundred activities at most)."""
    rows = session.exec(select(Activity).where(Activity.start.is_not(None))).all()
    by_day: dict = defaultdict(list)
    for a in rows:
        day = a.start.astimezone().date()
        for offset in (-1, 0, 1):
            by_day[day + timedelta(days=offset)].append(a)

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
                if _blocked(session, a, b):
                    continue
                result = match_pair(_to_match_input(a), _to_match_input(b))
                if result.is_candidate and result.score >= 0.0:
                    results.append((a, b, result))
    results.sort(key=lambda r: r[2].score, reverse=True)
    return results


def _merge_canonicals(session: Session, keep: CanonicalActivity, drop: CanonicalActivity, members_of_drop: list[Activity]) -> None:
    for m in members_of_drop:
        m.canonical_id = keep.id
        session.add(m)
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


def run_matching(session: Session) -> dict:
    ensure_canonicals(session)
    pairs = find_candidate_pairs(session)
    result = apply_auto_merges(session, pairs)
    remaining = find_candidate_pairs(session)
    result["flagged"] = sum(1 for _, _, r in remaining if r.flagged and not r.auto_merge)
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
