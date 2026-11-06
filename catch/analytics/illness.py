from __future__ import annotations

"""Session 15 (see PLAN.md Part B): illness early-warning. Pure, no I/O — each signal is a
z-score vs. its own trailing baseline (catch/sync/scoring.py builds the history lists this
takes, excluding today, nights already "likely", and nights dismissed with a confounding
reason). Never diagnoses — the one fixed phrase below ("signs of strain or illness") is the
only wording used, matching the task's explicit instruction not to say "sick" or guess a
cause."""

import statistics

from catch.analytics.defaults import DEFAULT_SETTINGS

_CORE_SIGNALS = ("resting_hr", "hrv", "respiration", "checkin")


def _z(today: float | None, history: list[float] | None, sd_floor: float, min_nights: int) -> tuple[float | None, float | None]:
    if today is None:
        return None, None
    history = history or []
    if len(history) < min_nights:
        return None, None
    baseline = statistics.mean(history)
    spread = max(statistics.pstdev(history) if len(history) >= 2 else 0.0, sd_floor)
    return (today - baseline) / spread, baseline


def illness_score(
    *,
    today_resting_hr: float | None = None,
    resting_hr_history: list[float] | None = None,
    today_ln_hrv: float | None = None,
    hrv_history_ln: list[float] | None = None,
    today_resp: float | None = None,
    resp_history: list[float] | None = None,
    today_checkin_badness: float | None = None,
    checkin_badness_history: list[float] | None = None,
    prev_deviated_count: int = 0,
    acr: float | None = None,
    settings: dict | None = None,
) -> dict:
    """`today_checkin_badness`/`checkin_badness_history`: 0-100, higher = worse (the inverse
    of checkin_recovery_score — mood/soreness only, see catch/sync/scoring.py). `acr` should
    be *yesterday's* acute:chronic ratio, not today's, so this morning's signal doesn't change
    retroactively once today's own workout syncs in and shifts today's ACR (task Part B —
    see PLAN.md's advisor note on this)."""
    settings = settings or DEFAULT_SETTINGS
    threshold = settings["illness_sd_threshold"]
    min_nights = settings["illness_min_baseline_nights"]

    rhr_z, rhr_baseline = _z(today_resting_hr, resting_hr_history, settings["illness_sd_floor_rhr"], min_nights)
    hrv_z, hrv_baseline = _z(today_ln_hrv, hrv_history_ln, settings["illness_sd_floor_hrv_ln"], min_nights)
    resp_z, resp_baseline = _z(today_resp, resp_history, settings["illness_sd_floor_resp"], min_nights)
    checkin_z, checkin_baseline = _z(
        today_checkin_badness, checkin_badness_history, 0.0, settings["illness_min_checkin_baseline"]
    )

    signals = {
        "resting_hr": {"z": rhr_z, "baseline": rhr_baseline, "deviated": rhr_z is not None and rhr_z >= threshold},
        "hrv": {"z": hrv_z, "baseline": hrv_baseline, "deviated": hrv_z is not None and hrv_z <= -threshold},
        "respiration": {"z": resp_z, "baseline": resp_baseline, "deviated": resp_z is not None and resp_z >= threshold},
        "checkin": {"z": checkin_z, "baseline": checkin_baseline, "deviated": checkin_z is not None and checkin_z >= threshold},
    }
    deviated_count = sum(1 for s in signals.values() if s["deviated"])
    deviated_names = [name for name in _CORE_SIGNALS if signals[name]["deviated"]]

    persisted = prev_deviated_count >= 2 and deviated_count >= 2
    # Respiration and the check-in aren't mechanically moved by training load the way resting
    # HR/HRV are — a hard training block elevates RHR and suppresses HRV too, so persistence
    # alone can't tell a training response from illness. Requiring one of these two when ACR
    # is already high is what keeps a training block capped at "watch" (task Part B.2's
    # fixtures: a real illness pattern vs. a hard training block vs. one bad night).
    non_training_signal = signals["respiration"]["deviated"] or signals["checkin"]["deviated"]
    high_load = acr is not None and acr >= settings["illness_acr_high_threshold"]
    would_be_likely = deviated_count >= 2 and persisted
    discounted = would_be_likely and high_load and not non_training_signal

    if would_be_likely and not discounted:
        level = "likely"
    elif deviated_count >= 1:
        level = "watch"
    else:
        level = "none"

    if level == "none":
        explanation = "No signal deviated beyond its own baseline tonight."
    else:
        when = "for 2+ nights running" if level == "likely" else "tonight"
        explanation = (
            f"Your body is showing signs of strain or illness — {deviated_count} signal(s) "
            f"deviated beyond baseline {when} ({', '.join(deviated_names)})."
        )
        if discounted:
            explanation += " Capped at 'watch': training load is already high, which can explain resting HR/HRV alone."

    return {
        "level": level,
        "deviated_count": deviated_count,
        "signals": signals,
        "explanation": explanation,
    }
