from __future__ import annotations

from catch.analytics.defaults import DEFAULT_SETTINGS


def ewma(daily_totals: list[float], window_days: int) -> float:
    """daily_totals: chronological, oldest -> newest, one entry per calendar day with rest
    days zero-filled (gaps would otherwise understate how detrained a rest stretch made you).
    lambda = 2/(N+1) (Williams 2017); series seeded with its first value."""
    if not daily_totals:
        return 0.0
    lam = 2 / (window_days + 1)
    value = daily_totals[0]
    for x in daily_totals[1:]:
        value = lam * x + (1 - lam) * value
    return value


def _acr_band(acr: float, bands: dict) -> str:
    if acr < bands["undertraining"]:
        return "undertraining"
    if acr <= bands["optimal_high"]:
        return "optimal"
    if acr <= bands["caution_high"]:
        return "caution"
    return "high_risk"


def training_load(daily_totals: list[float], settings: dict | None = None) -> dict:
    settings = settings or DEFAULT_SETTINGS
    if not daily_totals:
        return {
            "value": None,
            "band": "insufficient_data",
            "components": [],
            "explanation": "No training-load history yet.",
        }
    acute = ewma(daily_totals, settings["load_acute_days"])
    chronic = ewma(daily_totals, settings["load_chronic_days"])
    form = chronic - acute
    acr = (acute / chronic) if chronic > 0 else None
    band = _acr_band(acr, settings["acr_bands"]) if acr is not None else "insufficient_data"
    return {
        "value": acr,
        "band": band,
        "components": [{"acute_7d": acute, "chronic_42d": chronic, "form": form}],
        "explanation": (
            f"Acute (7d EWMA)={acute:.1f}, chronic (42d EWMA)={chronic:.1f}, "
            f"form=chronic-acute={form:.1f}, acute:chronic={'n/a' if acr is None else f'{acr:.2f}'}."
        ),
    }
