from __future__ import annotations

"""Cross-source activity matching (session 8/12 — see PLAN.md). Pure functions, no I/O, per
CLAUDE.md's analytics convention; catch/sync/matching.py does the DB work (building
MatchInput from real Activity rows, writing CanonicalActivity/MergeLog/MatchDecision rows).

One ride can arrive as a Garmin watch activity, a Peloton-pushed Garmin activity (same
source, different external_id — the old session-2 linker only ever considered *cross*-source
pairs), or a Concept2 PM5 result. The matching rule below is intentionally source-agnostic:
it only looks at sport family, timing, and duration, never at `source` itself.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

SPORT_FAMILIES = ("cycling", "rowing", "running", "strength", "other")

# Garmin activityType typeKeys this account has actually produced or that are documented in
# docs/garmin-openapi.json's activityTypes enum — grouped into the broad families the task
# asks for. Unlisted typeKeys fall through to "other" rather than guessing.
_GARMIN_FAMILY = {
    "rowing_v2": "rowing",
    "indoor_rowing": "rowing",
    "cycling": "cycling",
    "indoor_cycling": "cycling",
    "road_biking": "cycling",
    "mountain_biking": "cycling",
    "gravel_cycling": "cycling",
    "virtual_ride": "cycling",
    "running": "running",
    "treadmill_running": "running",
    "trail_running": "running",
    "track_running": "running",
    "strength_training": "strength",
}
# Of the Garmin families above, which typeKeys are indoor (trainer/ergometer/treadmill) vs.
# outdoor — only meaningful within a family; "strength"/"other" have no indoor/outdoor rule.
_GARMIN_INDOOR = {
    "rowing_v2": False,
    "indoor_rowing": True,
    "cycling": False,
    "indoor_cycling": True,
    "road_biking": False,
    "mountain_biking": False,
    "gravel_cycling": False,
    "virtual_ride": True,
    "running": False,
    "treadmill_running": True,
    "trail_running": False,
    "track_running": False,
}

# Concept2 result `type` (docs/concept2-endpoints.md): rower/skierg/bike/dynamic/slides/
# multierg are indoor ergometers; water/paddle are on-water; snow/rollerski are outdoor.
_CONCEPT2_FAMILY = {
    "rower": "rowing",
    "dynamic": "rowing",
    "slides": "rowing",
    "water": "rowing",
    "paddle": "rowing",
    "bike": "cycling",
    "skierg": "other",
    "multierg": "other",
    "snow": "other",
    "rollerski": "other",
}
_CONCEPT2_INDOOR = {
    "rower": True,
    "dynamic": True,
    "slides": True,
    "bike": True,
    "skierg": True,
    "multierg": True,
    "water": False,
    "paddle": False,
    "snow": False,
    "rollerski": False,
}


def sport_family(source: str | None, type_: str | None) -> str:
    """One of SPORT_FAMILIES. Mirrors catch/analytics/classify.py's workout_category in
    spirit (documented heuristics, not invented API fields) but groups by broad sport rather
    than erg/on_water/other, since matching must treat a Garmin road ride and a Peloton ride
    as the same family even though classify.py's categories would call one "on_water"-adjacent
    and the other indoor."""
    if source == "catch_strength":
        # Session 14 (see PLAN.md) — a Catch-logged lifting session is always "strength",
        # regardless of `type_` (always "catch_strength" itself, carrying no useful info here).
        return "strength"
    if source == "garmin":
        return _GARMIN_FAMILY.get(type_ or "", "other")
    if source == "concept2":
        return _CONCEPT2_FAMILY.get(type_ or "", "other")
    if source == "whoop":
        from catch.analytics.whoop import sport_family as _whoop_family

        return _whoop_family(type_)
    return "other"


def category_for_canonical(sport_family_: str, indoor: Optional[bool]) -> str:
    """erg/on_water/strength/other for the Workouts-list filter, generalizing
    catch/analytics/classify.py's workout_category (kept as-is for raw per-source rows) to a
    canonical activity — rowing is "erg" indoors, "on_water" outdoors; strength (session 14)
    gets its own category rather than falling into "other" alongside cycling/running, since
    the gym logger makes it common enough to want its own Workouts filter tab; everything
    else (cycling, running, unclassified) is "other", same as the original scheme."""
    if sport_family_ == "rowing":
        return "erg" if indoor is not False else "on_water"
    if sport_family_ == "strength":
        return "strength"
    return "other"


def is_indoor(source: str | None, type_: str | None) -> Optional[bool]:
    """True/False where the source/type tells us, else None (unknown — e.g. "other")."""
    if source == "catch_strength":
        return True  # a gym session is always indoor.
    if source == "garmin":
        return _GARMIN_INDOOR.get(type_ or "")
    if source == "concept2":
        return _CONCEPT2_INDOOR.get(type_ or "")
    if source == "whoop":
        from catch.analytics.whoop import is_indoor as _whoop_indoor

        return _whoop_indoor(type_)
    return None


# -- matching rule (task Part A.2) -------------------------------------------------------

MATCH_START_WINDOW_S = 180.0  # 3 minutes
MATCH_MIN_OVERLAP_FRACTION = 0.70
MATCH_DURATION_RATIO_MIN = 0.8  # and its reciprocal, 1.25, by symmetry
AUTO_MERGE_THRESHOLD = 0.82
FLAG_THRESHOLD = 0.45


@dataclass(frozen=True)
class MatchInput:
    source: str
    external_id: str
    sport_family: str
    indoor: Optional[bool]
    start: Optional[datetime]
    duration: Optional[float]  # seconds


@dataclass(frozen=True)
class MatchResult:
    is_candidate: bool
    score: float
    hard_block: bool  # True = never auto-merge even if score clears the threshold
    reasons: list[str]

    @property
    def auto_merge(self) -> bool:
        return self.is_candidate and not self.hard_block and self.score >= AUTO_MERGE_THRESHOLD

    @property
    def flagged(self) -> bool:
        return self.is_candidate and self.score >= FLAG_THRESHOLD


def _overlap_fraction(a: MatchInput, b: MatchInput) -> float:
    a_end = a.start + _td(a.duration)
    b_end = b.start + _td(b.duration)
    overlap_start = max(a.start, b.start)
    overlap_end = min(a_end, b_end)
    overlap_s = max(0.0, (overlap_end - overlap_start).total_seconds())
    shorter = min(a.duration, b.duration)
    return overlap_s / shorter if shorter else 0.0


def _td(seconds: float):
    from datetime import timedelta

    return timedelta(seconds=seconds)


def _match_strength_pair(a: MatchInput, b: MatchInput) -> MatchResult:
    """Session 14 (see PLAN.md Part B.1): a Catch lifting session's window is deliberately
    padded (first set -10min, last set +5min — catch/sync/gym.py) and has nothing to do with
    how long a Garmin watch happened to record a "strength_training" activity for, so the
    generic rule's 3-minute-start/0.8-1.25-duration-ratio checks would wrongly reject a real
    match whenever the watch was started a few minutes early or stopped a few minutes late.
    Any overlap at all between the two windows is enough to flag/auto-merge — there's no
    "two different strength sessions happening at once" scenario to guard against the way
    "two different rides" is for cycling."""
    overlap = _overlap_fraction(a, b)
    if overlap <= 0:
        return MatchResult(False, 0.0, False, ["no time overlap"])
    # Scored purely on overlap fraction (of the shorter window) — a near-total overlap is a
    # near-certain match; a sliver of overlap (e.g. the watch running into the next exercise's
    # warm-up) is flagged for review rather than silently merged.
    return MatchResult(True, overlap, False, [f"{overlap:.0%} time overlap"])


def match_pair(a: MatchInput, b: MatchInput) -> MatchResult:
    """No I/O; both inputs are small dataclasses the caller (catch/sync/matching.py) builds
    from real Activity rows."""
    if a.sport_family != b.sport_family or a.sport_family == "other":
        # "other" is a catch-all for unclassified types, not a real shared family — never
        # auto-match two sessions just because neither was recognized.
        return MatchResult(False, 0.0, False, ["different or unclassified sport family"])
    if a.start is None or b.start is None or not a.duration or not b.duration:
        return MatchResult(False, 0.0, False, ["missing start/duration"])

    if a.sport_family == "strength":
        return _match_strength_pair(a, b)

    start_diff_s = abs((a.start - b.start).total_seconds())
    overlap = _overlap_fraction(a, b)
    time_ok = start_diff_s <= MATCH_START_WINDOW_S or overlap >= MATCH_MIN_OVERLAP_FRACTION

    ratio = min(a.duration, b.duration) / max(a.duration, b.duration)
    duration_ok = ratio >= MATCH_DURATION_RATIO_MIN

    reasons = []
    if not time_ok:
        reasons.append(f"start {start_diff_s:.0f}s apart, only {overlap:.0%} overlap")
    if not duration_ok:
        reasons.append(f"duration ratio {ratio:.2f} outside [0.8, 1.25]")
    if not (time_ok and duration_ok):
        return MatchResult(False, 0.0, False, reasons)

    time_component = max(overlap, 1.0 - start_diff_s / MATCH_START_WINDOW_S)
    time_component = max(0.0, min(1.0, time_component))
    score = 0.6 * time_component + 0.4 * ratio

    hard_block = False
    if a.indoor is not None and b.indoor is not None and a.indoor != b.indoor:
        hard_block = True
        reasons.append("indoor/outdoor mismatch — never auto-merged")

    return MatchResult(True, score, hard_block, reasons or ["same sport family, within time/duration window"])
