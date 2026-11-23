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


def weekly_monotony_strain(daily_loads: list[float]) -> dict:
    """Session 36: Foster's (1998) weekly training monotony and strain from seven daily training loads (rest days = 0).

    monotony = mean daily load / standard deviation of daily load; strain = weekly load x monotony. A week where every day carried
    the same load (SD 0) has no defined monotony, so both are None with the reason. Descriptive only: Foster associated high
    monotony with illness in his athletes, but no threshold here is presented as a warning (docs/analytics.md §35)."""
    import statistics

    loads = [max(float(x or 0.0), 0.0) for x in daily_loads]
    total = sum(loads)
    if len(loads) < 2:
        return {"load": total, "monotony": None, "strain": None, "reason": "fewer than two days"}
    mean = statistics.mean(loads)
    sd = statistics.pstdev(loads)
    if total <= 0:
        return {"load": 0.0, "monotony": None, "strain": None, "reason": "no training load this week"}
    if sd == 0:
        return {"load": total, "monotony": None, "strain": None, "reason": "every day carried the same load, so the ratio is undefined"}
    monotony = mean / sd
    return {"load": total, "monotony": monotony, "strain": total * monotony, "reason": None}
