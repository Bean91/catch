from __future__ import annotations

import math

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.analytics.zones import ZONE_ORDER, zone_for_hr


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


def time_in_zone(samples: list[tuple[float, float]], max_hr: float | None, settings: dict | None = None) -> dict[str, float]:
    """samples: [(seconds_at_this_hr, hr), ...]. Needs per-sample HR — only available for
    strokes with hr data (Concept2); Garmin-only sessions have no sample-level HR without
    parsing the FIT file, so this returns all-zero zone totals for those."""
    totals = {z: 0.0 for z in ZONE_ORDER}
    if not samples or not max_hr:
        return totals
    for duration, hr in samples:
        zone = zone_for_hr(hr, max_hr, settings)
        if zone:
            totals[zone] += duration
    return totals
