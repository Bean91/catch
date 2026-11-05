from __future__ import annotations

"""Strength-training math: estimated 1RM, PR detection, and muscular load (session 14 — see
PLAN.md Part C.1). Pure functions, no I/O, per CLAUDE.md's analytics convention; the DB-facing
counterpart is catch/sync/gym.py.

Muscle names are whatever catch/seed/exercises.json's `primary_muscles`/
`secondary_muscles` use (free-exercise-db's own 17-muscle vocabulary — abdominals, abductors,
adductors, biceps, calves, chest, forearms, glutes, hamstrings, lats, lower back, middle
back, neck, quadriceps, shoulders, traps, triceps) plus whatever a user-added custom exercise
names; there's no separate canonical muscle list to keep in sync.
"""

import math
from dataclasses import dataclass
from typing import Optional

MAX_E1RM_REPS = 10  # Epley's own accuracy degrades past ~10 reps — task Part A.6's explicit cap.

PRIMARY_MUSCLE_WEIGHT = 1.0
SECONDARY_MUSCLE_WEIGHT = 0.5

# A set this many reps-from-failure or more is "far enough from failure" that, combined with
# the intensity-factor curve below, it contributes only a small fraction of a near-max set's
# muscular load — not a separate cutoff, just where the curve already lands by construction.
DEFAULT_RIR_WHEN_UNKNOWN = 2


def epley_e1rm(weight_kg: float, reps: int) -> float:
    """weight_kg * (1 + reps/30), reps capped at MAX_E1RM_REPS (task Part A.6: "estimated 1RM
    (Epley, capped at 10 reps for estimates)"). A 1-rep set returns the weight itself —
    Epley's own formula already reduces to that at reps=1 (1 + 1/30 ~= 1.03x), close enough
    that no special case is needed, but reps<=0 would be nonsensical so it's guarded."""
    if reps <= 0 or weight_kg <= 0:
        return 0.0
    capped_reps = min(reps, MAX_E1RM_REPS)
    return weight_kg * (1.0 + capped_reps / 30.0)


@dataclass(frozen=True)
class WorkingSet:
    exercise_id: int
    date: str  # ISO date, for PR/baseline grouping — the caller's local calendar day
    reps: int
    effective_load_kg: Optional[float]
    set_type: str = "working"  # "warmup" | "working" | "drop" | "failure" | "amrap"
    rir: Optional[float] = None
    rpe: Optional[float] = None
    side: Optional[str] = None  # "left" | "right" | None (bilateral)


def reps_to_failure(reps: int, rir: Optional[float], rpe: Optional[float]) -> float:
    """How many more reps the lifter estimates they had left, converted to one number
    regardless of which of RIR/RPE (or neither) was logged — RPE 10 = 0 RIR, RPE 9 = ~1 RIR,
    etc. (RPE scale's own standard mapping). Falls back to DEFAULT_RIR_WHEN_UNKNOWN (a
    moderately-hard assumption, not "to failure") when neither is given, so an unlogged set
    doesn't silently count as maximal."""
    if rir is not None:
        return max(0.0, rir)
    if rpe is not None:
        return max(0.0, 10.0 - rpe)
    return float(DEFAULT_RIR_WHEN_UNKNOWN)


def intensity_factor(total_reps_to_failure: float) -> float:
    """Reuses Epley's own reps<->%1RM relationship (1 / (1 + reps/30)) as the "how close to
    failure was this set" weighting, so sets far from failure count less (task Part C.1)
    without introducing a second, unrelated constant. total_reps_to_failure is reps actually
    performed plus the estimated reps left (reps_to_failure above) — capped the same way
    epley_e1rm caps its own input, for the same reason."""
    capped = min(max(0.0, total_reps_to_failure), 30.0)
    return 1.0 / (1.0 + capped / 30.0)


def set_muscular_au(working_set: WorkingSet) -> float:
    """Arbitrary units (AU), not a 0-21 scale — catch/sync/gym.py sums these per muscle per
    day and catch/analytics/strain.py's day-level curve maps the *normalized* total onto
    0-21. Only "working" sets count (task Part C.1's "sum over working sets") — warm-ups are
    still logged and shown, just contribute 0 here."""
    if working_set.set_type == "warmup" or not working_set.effective_load_kg or working_set.reps <= 0:
        return 0.0
    total_reps_to_failure = working_set.reps + reps_to_failure(working_set.reps, working_set.rir, working_set.rpe)
    return working_set.reps * working_set.effective_load_kg * intensity_factor(total_reps_to_failure)


def distribute_to_muscles(au: float, primary_muscles: list[str], secondary_muscles: list[str]) -> dict[str, float]:
    """Each primary muscle gets full credit, each secondary muscle gets half — not divided
    across how many muscles are listed, since a 3-primary-muscle compound lift genuinely
    loads all three, not one-third of each."""
    out: dict[str, float] = {}
    for m in primary_muscles:
        out[m] = out.get(m, 0.0) + au * PRIMARY_MUSCLE_WEIGHT
    for m in secondary_muscles:
        out[m] = out.get(m, 0.0) + au * SECONDARY_MUSCLE_WEIGHT
    return out


def normalize_muscle_au(today_au: float, baseline_daily_au: list[float], clamp_low: float = 0.4, clamp_high: float = 2.0) -> float:
    """Normalizes one muscle's today-AU against its own rolling 28-day daily-average baseline
    (task Part C.1: "normalised per muscle group against my rolling 28-day baseline") — a
    lifter who already trains a muscle hard every week isn't penalized for being at their own
    normal heavy level, and a sudden jump well past normal is clamped rather than blowing the
    day's strain out on one outlier session. Cold start (no baseline history at all, e.g. the
    very first logged session) uses today's own raw value — there's nothing to normalize
    against yet, and treating it as "0x baseline" would wrongly zero out a real first
    session's contribution."""
    if not baseline_daily_au:
        return today_au
    baseline_avg = sum(baseline_daily_au) / len(baseline_daily_au)
    if baseline_avg <= 0:
        return today_au
    ratio = today_au / baseline_avg
    ratio = max(clamp_low, min(clamp_high, ratio))
    return baseline_avg * ratio


def cardio_muscular_au(seconds_above_threshold: float, threshold_power_watts: float, scale: float = 0.01) -> float:
    """A small muscular contribution from erg/bike time spent above ~110% of threshold power
    (sprints, starts — task Part C.1.2), "default low" per the task: `scale` keeps this well
    below what a real strength session produces for the same AU formula's units (power x
    seconds), so an all-out erg piece doesn't masquerade as a leg day."""
    if seconds_above_threshold <= 0 or threshold_power_watts <= 0:
        return 0.0
    return seconds_above_threshold * threshold_power_watts * scale


# -- PRs (task Part A.6) -------------------------------------------------------------------


@dataclass(frozen=True)
class PrResult:
    is_rep_pr: bool  # heaviest effective_load_kg ever logged at this exact rep count
    is_e1rm_pr: bool  # highest epley_e1rm ever logged for this exercise


def detect_pr(
    new_set: WorkingSet,
    history: list[WorkingSet],
) -> PrResult:
    """`history` is every prior working set for the same exercise (any gym/equipment — a PR is
    about the lifter's own strength, not one station's numbers), excluding `new_set` itself.
    Warm-ups never count as a PR candidate, matching set_muscular_au's own working-sets-only
    rule."""
    if new_set.set_type == "warmup" or not new_set.effective_load_kg:
        return PrResult(False, False)

    same_rep_loads = [
        h.effective_load_kg
        for h in history
        if h.set_type != "warmup" and h.reps == new_set.reps and h.effective_load_kg is not None
    ]
    is_rep_pr = not same_rep_loads or new_set.effective_load_kg > max(same_rep_loads)

    new_e1rm = epley_e1rm(new_set.effective_load_kg, new_set.reps)
    prior_e1rms = [
        epley_e1rm(h.effective_load_kg, h.reps) for h in history if h.set_type != "warmup" and h.effective_load_kg is not None
    ]
    is_e1rm_pr = not prior_e1rms or new_e1rm > max(prior_e1rms)

    return PrResult(is_rep_pr, is_e1rm_pr)
