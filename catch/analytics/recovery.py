from __future__ import annotations

import statistics

from catch.analytics.defaults import DEFAULT_SETTINGS


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def recovery_score(
    *,
    today_ln_hrv: float | None = None,
    hrv_history_ln: list[float] | None = None,
    today_resting_hr: float | None = None,
    rhr_history: list[float] | None = None,
    today_sleep_seconds: float | None = None,
    prior_day_strain: float | None = None,
    settings: dict | None = None,
) -> dict:
    """hrv_history_ln / rhr_history: prior nights only, oldest -> newest, up to 60 entries,
    NOT including today — the baseline and spread would otherwise include the value being
    scored against it."""
    settings = settings or DEFAULT_SETTINGS
    hrv_history_ln = hrv_history_ln or []
    rhr_history = rhr_history or []
    min_nights = settings["min_hrv_nights_for_baseline"]

    if len(hrv_history_ln) < min_nights:
        return {
            "value": None,
            "band": "calibrating",
            "components": [],
            "explanation": f"Need {min_nights} nights of HRV history before a baseline exists; have {len(hrv_history_ln)}.",
        }

    weights = settings["recovery_weights"]
    components = []

    hrv_component = None
    if today_ln_hrv is not None:
        baseline = statistics.mean(hrv_history_ln[-7:])
        pool = hrv_history_ln[-60:]
        spread = statistics.pstdev(pool) if len(pool) >= 2 else None
        if spread and spread > 1e-6:
            z = (today_ln_hrv - baseline) / spread
            hrv_component = _clip(50 + z * 25, 0, 100)
        components.append({"metric": "hrv", "baseline_7d_ln": baseline, "spread_60d": spread, "value": hrv_component})

    rhr_component = None
    if today_resting_hr is not None and rhr_history:
        baseline_rhr = statistics.mean(rhr_history[-7:])
        pool = rhr_history[-60:]
        spread = statistics.pstdev(pool) if len(pool) >= 2 else None
        if spread and spread > 1e-6:
            z = (baseline_rhr - today_resting_hr) / spread  # lower RHR than baseline is good
            rhr_component = _clip(50 + z * 25, 0, 100)
        components.append({"metric": "resting_hr", "baseline_7d": baseline_rhr, "spread_60d": spread, "value": rhr_component})

    sleep_component = None
    if today_sleep_seconds is not None:
        need = settings["sleep_need_seconds"]
        sleep_component = _clip(today_sleep_seconds / need * 100, 0, 100)
        components.append({"metric": "sleep", "need_seconds": need, "value": sleep_component})

    strain_component = None
    if prior_day_strain is not None:
        strain_component = _clip(100 - prior_day_strain * (100 / 21), 0, 100)
        components.append({"metric": "prior_strain", "value": strain_component})

    weighted = [
        (weights["hrv"], hrv_component),
        (weights["resting_hr"], rhr_component),
        (weights["sleep"], sleep_component),
        (weights["prior_strain"], strain_component),
    ]
    available = [(w, v) for w, v in weighted if v is not None]
    if not available:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": components,
            "explanation": "No component had enough data to score today.",
        }
    total_weight = sum(w for w, _ in available)
    value = sum(w * v for w, v in available) / total_weight

    if value >= settings["recovery_green"]:
        band = "green"
    elif value >= settings["recovery_yellow"]:
        band = "yellow"
    else:
        band = "red"

    return {
        "value": value,
        "band": band,
        "components": components,
        "explanation": (
            "Weighted blend of HRV-vs-7d-baseline (normalised by 60d spread), resting HR "
            f"deviation, sleep-vs-need, and prior-day strain; weights {weights}. A missing "
            "component is dropped and the rest are renormalised."
        ),
    }
