from __future__ import annotations

"""Session 33: combining several recordings into one workout (docs/analytics.md §31). Pure — no I/O.

Two kinds of "same workout" exist. Duplicates are one session recorded twice (a watch and the erg): every number is picked from
one source, never added — what the automatic matcher and the Duplicates page have always done. A *combined* workout is one
session split across recordings (the watch paused and restarted, the erg reset between pieces): its parts happened one after
another, so durations and distances add up. The athlete's selection can contain both at once — two watch recordings, one of them
also on the erg — so members are grouped by time overlap first: inside a group the duplicate rules pick one value, across groups
the values add. Nothing is ever counted twice and nothing a member recorded is dropped."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence

MAX_ITEMS = 10
MAX_SPAN = timedelta(hours=6)
MAX_GAP = timedelta(hours=2)
STRENGTH = "strength"


@dataclass(frozen=True)
class Span:
    key: int
    start: datetime
    end: datetime


def span_of(key: int, start: Optional[datetime], duration_s: Optional[float]) -> Optional[Span]:
    if start is None:
        return None
    return Span(key, start, start + timedelta(seconds=max(0.0, duration_s or 0.0)))


def overlap_seconds(a: Span, b: Span) -> float:
    return max(0.0, (min(a.end, b.end) - max(a.start, b.start)).total_seconds())


def cluster(spans: Iterable[Span]) -> list[list[Span]]:
    """Groups of spans that overlap in time (transitively), in start order. Touching end-to-start is not an overlap."""
    groups: list[list[Span]] = []
    end: Optional[datetime] = None
    for s in sorted(spans, key=lambda s: (s.start, s.end)):
        if groups and end is not None and s.start < end:
            groups[-1].append(s)
            end = max(end, s.end)
        else:
            groups.append([s])
            end = s.end
    return groups


def weighted_mean(pairs: Iterable[tuple[Optional[float], Optional[float]]]) -> Optional[float]:
    """Mean of values weighted by their durations; pairs with no value or no duration are skipped (never counted as zero). The
    average heart rate of a combined workout is never the plain mean of its parts' averages."""
    num = den = 0.0
    for value, weight in pairs:
        if value is None or not weight:
            continue
        num += value * weight
        den += weight
    return num / den if den else None


def sum_known(values: Sequence[Optional[float]]) -> tuple[Optional[float], bool]:
    """(sum of the values that exist, whether any were missing). None when none exist."""
    known = [v for v in values if v is not None]
    return (sum(known) if known else None), len(known) != len(values)


def overlaps(spans: Sequence[Span]) -> list[dict]:
    out = []
    for i, a in enumerate(spans):
        for b in spans[i + 1:]:
            secs = overlap_seconds(a, b)
            if secs > 0:
                out.append({"a": a.key, "b": b.key, "seconds": round(secs)})
    return out


def check_compatible(items: Sequence[dict]) -> list[str]:
    """Reasons these workouts can't be combined, as sentences (empty = they can). Each item: {id, title, sport_family, category,
    start, duration, test_type, published, has_strength_sets}."""
    reasons: list[str] = []
    if len(items) < 2:
        reasons.append("Choose at least two workouts to merge.")
    if len(items) > MAX_ITEMS:
        reasons.append(f"Merge at most {MAX_ITEMS} workouts at a time.")
    if any(i.get("start") is None for i in items):
        reasons.append("One of these workouts has no start time, so Catch can't place it in order.")
    families = {i.get("sport_family") or "other" for i in items}
    if len(families) > 1:
        reasons.append(f"These are different sports ({', '.join(sorted(families))}). Only workouts of the same sport can be merged — change a workout's type first if it was recorded as the wrong one.")
    if STRENGTH in families or any(i.get("has_strength_sets") for i in items):
        reasons.append("Strength sessions can't be merged: their sets belong to one logged session.")
    categories = {i.get("category") for i in items if i.get("category") in ("erg", "on_water")}
    if len(categories) > 1:
        reasons.append("An erg session and an on-water row can't be merged into one workout.")
    if sum(1 for i in items if i.get("test_type")) > 1:
        reasons.append("More than one of these is a confirmed test. A merged workout can be at most one test — remove the test mark from the others first.")
    if sum(1 for i in items if i.get("published")) > 1:
        reasons.append("More than one of these is published on a leaderboard. Take the others down first.")
    spans = [s for s in (span_of(i["id"], i.get("start"), i.get("duration")) for i in items) if s is not None]
    if len(spans) == len(items) and spans:
        first, last = min(s.start for s in spans), max(s.end for s in spans)
        if last - first > MAX_SPAN:
            reasons.append(f"These span more than {int(MAX_SPAN.total_seconds() // 3600)} hours, which is longer than one session.")
        groups = cluster(spans)
        # Recordings that overlap are the same stretch recorded twice — but only if they all overlap one another. One long
        # recording spanning two shorter ones that don't overlap each other is a session with pieces in it, not duplicates.
        for g in groups:
            if any(overlap_seconds(a, b) <= 0 for i, a in enumerate(g) for b in g[i + 1:]):
                reasons.append("One of these recordings covers several of the others. Those are pieces within one session — add them as pieces of the longer workout instead of merging.")
                break
        for prev, nxt in zip(groups, groups[1:]):
            gap = min(s.start for s in nxt) - max(s.end for s in prev)
            if gap > MAX_GAP:
                reasons.append(f"There's a gap of more than {int(MAX_GAP.total_seconds() // 3600)} hours between two of them — that's two sessions, not one.")
                break
    return reasons
