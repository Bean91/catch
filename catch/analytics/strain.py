from __future__ import annotations

import math

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.analytics.zones import ZONE_ORDER, HrBasis, hr_zone_bounds, zone_for_hr


def banister_trimp(
    duration_minutes: float | None,
    avg_hr: float | None,
    resting_hr: float | None,
    max_hr: float | None,
    trimp_exponent: float = 1.92,
) -> float | None:
    """Classic Banister TRIMP: duration_min * HRr * 0.64 * e^(b*HRr), HRr = (avg-rest)/(max-rest)."""
    if not duration_minutes or avg_hr is None or resting_hr is None or not max_hr or max_hr <= resting_hr:
        return None
    hrr = (avg_hr - resting_hr) / (max_hr - resting_hr)
    hrr = max(0.0, min(1.0, hrr))
    return duration_minutes * hrr * 0.64 * math.exp(trimp_exponent * hrr)


def srpe_load(rpe: int | None, duration_minutes: float | None, scale: float) -> float | None:
    if rpe is None or not duration_minutes:
        return None
    return rpe * duration_minutes * scale


def strain_band(value: float) -> str:
    if value < 10:
        return "light"
    if value < 14:
        return "moderate"
    if value < 18:
        return "high"
    return "all_out"


def session_strain(
    *,
    duration_minutes: float | None,
    avg_hr: float | None = None,
    resting_hr: float | None = None,
    max_hr: float | None = None,
    rpe: int | None = None,
    settings: dict | None = None,
) -> dict:
    settings = settings or DEFAULT_SETTINGS
    trimp = banister_trimp(duration_minutes, avg_hr, resting_hr, max_hr, settings["trimp_exponent"])
    method = "trimp"
    if trimp is None:
        trimp = srpe_load(rpe, duration_minutes, settings["srpe_to_trimp_scale"])
        method = "srpe"
    if trimp is None:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": [],
            "explanation": "Need HR (avg + resting + max) or an RPE note for that day to compute strain.",
        }
    strain = min(21.0, settings["strain_log_a"] * math.log1p(trimp))
    return {
        "value": strain,
        "band": strain_band(strain),
        "components": [{"method": method, "trimp_like": trimp, "duration_minutes": duration_minutes}],
        "explanation": (
            f"{'Banister TRIMP from heart rate' if method == 'trimp' else 'session-RPE x minutes (no HR available)'}"
            f" -> trimp_like={trimp:.1f}, mapped to 0-21 via 21*ln-saturation (strain_log_a="
            f"{settings['strain_log_a']})."
        ),
    }


def strain_from_load(load: float, settings: dict | None = None) -> float:
    """The one 0-21 mapping: min(21, strain_log_a * ln(1 + load)), load in TRIMP units."""
    settings = settings or DEFAULT_SETTINGS
    return min(21.0, settings["strain_log_a"] * math.log1p(load)) if load > 0 else 0.0


def strength_baseline_au(previous_session_au: list[float], settings: dict | None = None) -> tuple[float, str]:
    """The athlete's own typical strength session (median AU of earlier sessions in the baseline window), or the documented
    default until `strength_baseline_min_sessions` exist. Returns (au, "personal" | "default")."""
    settings = settings or DEFAULT_SETTINGS
    values = sorted(v for v in previous_session_au if v and v > 0)
    if len(values) < settings["strength_baseline_min_sessions"]:
        return float(settings["strength_default_baseline_au"]), "default"
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    return float(median), "personal"


def muscular_trimp_equivalent(session_au: float | None, baseline_au: float, settings: dict | None = None) -> float:
    """A strength session's muscular AU in TRIMP units: (AU / the athlete's typical session AU) x strength_ref_trimp, capped at
    strength_session_cap_ratio typical sessions. Relative to the athlete's own norm, so heavy absolute loads don't outweigh
    rowing and light lifters aren't ignored."""
    settings = settings or DEFAULT_SETTINGS
    if not session_au or session_au <= 0 or baseline_au <= 0:
        return 0.0
    ratio = min(settings["strength_session_cap_ratio"], session_au / baseline_au)
    return ratio * settings["strength_ref_trimp"]


def strength_session_load(hr_trimp: float | None, srpe_trimp: float | None, muscular_eq: float) -> tuple[float, str]:
    """How a lifting session's load is formed, never counting the same effort twice:
    - heart rate recorded: HR TRIMP + the muscular equivalent (HR undersells lifting; the two measure different stress);
    - only a session RPE: max(sRPE TRIMP, muscular equivalent) — a perceived-exertion rating already includes the lifting;
    - neither: the muscular equivalent alone."""
    if hr_trimp is not None:
        return hr_trimp + muscular_eq, "hr_plus_muscular"
    if srpe_trimp is not None:
        return (max(srpe_trimp, muscular_eq), "srpe" if srpe_trimp >= muscular_eq else "muscular")
    return muscular_eq, "muscular"


def daily_activity_trimp(non_exercise_steps: float | None, non_exercise_active_kcal: float | None, settings: dict | None = None) -> dict:
    """Non-exercise movement in TRIMP units: steps / steps_per_min = easy-walking minutes (active kcal / kcal_per_min when
    steps are missing), times Banister's per-minute TRIMP at `daily_activity_hrr`, capped. Any logged workout's own steps
    and kcal are subtracted by the caller first."""
    settings = settings or DEFAULT_SETTINGS
    hrr = settings["daily_activity_hrr"]
    per_min = hrr * 0.64 * math.exp(settings["trimp_exponent"] * hrr)
    minutes, basis = None, None
    if non_exercise_steps is not None:
        minutes, basis = max(0.0, non_exercise_steps) / settings["daily_activity_steps_per_min"], "steps"
    elif non_exercise_active_kcal is not None:
        minutes, basis = max(0.0, non_exercise_active_kcal) / settings["daily_activity_kcal_per_min"], "active_kcal"
    load = min(settings["daily_activity_trimp_cap"], minutes * per_min) if minutes else 0.0
    return {
        "load": load,
        "minutes": minutes,
        "basis": basis,
        "steps": non_exercise_steps,
        "active_kcal": non_exercise_active_kcal,
        "explanation": (
            "No daily step or activity total." if basis is None else
            f"{minutes:.0f} min of easy walking ({basis.replace('_', ' ')}) x {per_min:.2f} TRIMP/min at {hrr:.0%} HRR"
            f" = {load:.1f} (cap {settings['daily_activity_trimp_cap']:.0f})."
        ),
    }


def day_load_strain(sessions: list[dict], daily_activity: dict, settings: dict | None = None) -> dict:
    """Session 32 (docs/analytics.md §4): the day's strain from ONE load sum through ONE curve.

    `sessions` are [{"canonical_id", "title", "kind": "cardio"|"strength", "load", "method", ...}] (load None = not scoreable);
    `daily_activity` is `daily_activity_trimp`'s result. Shares are each part's fraction of the load, so the displayed parts of
    the strain gauge always add up to the headline and nothing is counted twice."""
    settings = settings or DEFAULT_SETTINGS
    scored = [s for s in sessions if s.get("load") is not None]
    cardio = sum(s["load"] for s in scored if s["kind"] == "cardio")
    muscular_parts = [s.get("muscular_load", 0.0) for s in scored if s["kind"] == "strength"]
    strength_total = sum(s["load"] for s in scored if s["kind"] == "strength")
    muscular = sum(muscular_parts)
    strength_other = strength_total - muscular  # the HR/sRPE part of a lifting session
    daily = daily_activity.get("load") or 0.0
    total = cardio + strength_total + daily
    value = strain_from_load(total, settings)
    if sessions and not scored and daily <= 0:
        return {"value": None, "band": "insufficient_data", "load": 0.0, "cardio_load": 0.0, "muscular_load": 0.0,
                "daily_activity_load": 0.0, "shares": {}, "sessions": sessions,
                "explanation": "No session that day had enough data (heart rate, a session RPE or logged sets) to score."}

    def share(x: float) -> float:
        return x / total if total > 0 else 0.0

    for s in sessions:
        s["share"] = share(s["load"]) if s.get("load") is not None else None
    shares = {"cardio": share(cardio + strength_other), "muscular": share(muscular), "daily_activity": share(daily)}
    return {
        "value": value,
        "band": strain_band(value),
        "load": total,
        "cardio_load": cardio + strength_other,
        "muscular_load": muscular,
        "daily_activity_load": daily,
        "shares": shares,
        "sessions": sessions,
        "explanation": (
            f"Day load {total:.1f} TRIMP-equivalent (heart-rate/RPE {cardio + strength_other:.1f}, muscular {muscular:.1f},"
            f" daily movement {daily:.1f}) -> strain {value:.1f} via {settings['strain_log_a']} x ln(1 + load)."
        ),
    }


def hr_sample_durations(ordered_t_hr: list[tuple[float, float | None]]) -> list[tuple[float, float]]:
    """ordered_t_hr: [(t, hr_or_None), ...] for one interval, already in recorded order
    (t resets to 0 at each interval boundary — caller groups by interval first). Each HR
    reading's duration is `t` minus the *previous stroke's* `t` (the first stroke in the
    interval gets its own t) — walks every stroke to track t correctly even when some in
    between have no hr reading. Returns [(duration_s, hr), ...] for samples that have an hr."""
    out = []
    prev_t: float | None = None
    for t, hr in ordered_t_hr:
        duration = t if prev_t is None else max(0.0, t - prev_t)
        if hr is not None:
            out.append((duration, hr))
        prev_t = t
    return out


def time_in_zone(samples: list[tuple[float, float]], basis: HrBasis | None) -> dict[str, float]:
    """samples: [(seconds_at_this_hr, hr), ...]. Needs per-sample HR — only available for
    strokes with hr data (Concept2); Garmin-only sessions have no sample-level HR without
    parsing the FIT file, so this returns all-zero zone totals for those."""
    totals = {z: 0.0 for z in ZONE_ORDER}
    bounds = hr_zone_bounds(basis) if basis is not None else {}
    if not samples or not bounds:
        return totals
    for duration, hr in samples:
        zone = zone_for_hr(hr, basis, bounds)
        if zone:
            totals[zone] += duration
    return totals
