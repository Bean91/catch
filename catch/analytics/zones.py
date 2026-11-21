from __future__ import annotations

"""Training zones — the one authority for heart-rate and power zone boundaries (docs/analytics.md §3).

Session 33: heart-rate zones are heart-rate-reserve (Karvonen) zones by default:

    HRR       = max HR − resting HR
    target HR = resting HR + HRR × intensity%

A zone's lower bound is that target at the zone's percentage. "% of max HR" remains as a method the athlete can choose, and is the
stated fallback when no reliable resting heart rate exists. Nothing here invents a max HR: without one there are no HR zones.
Pure functions; the resting heart rate a workout uses is chosen by catch/analytics/hr_basis.py and catch/sync/hr_basis.py."""

from dataclasses import asdict, dataclass, field
from typing import Optional

from catch.analytics.defaults import DEFAULT_SETTINGS

ZONE_ORDER = ["UT2", "UT1", "AT", "TR", "AN"]
ZONE_NOTE = "Zone boundaries are defaults — confirm with your coach before training off them."
HR_METHODS = ("hrr", "max_pct")
# Bumped when the meaning of stored zone seconds changes, so run_maintenance re-resolves history once (2 = HRR zones, session 33).
ZONES_MODEL = 2
# A max HR within this of the resting HR leaves no usable reserve to divide — treated as not reliable.
MIN_RESERVE_BPM = 40.0

FALLBACK_NO_RHR = "No resting heart rate measured or entered yet, so zones use % of your max heart rate."
FALLBACK_BAD_RESERVE = "Your max and resting heart rates are too close together to divide into zones, so zones use % of max heart rate."
NO_MAX_HR = "Set your max heart rate in Settings to see heart-rate zones."


@dataclass(frozen=True)
class HrBasis:
    """What a set of heart-rate zones was computed from. Stored with every cached zone result so a screen shows the numbers that
    were actually used, not today's settings."""

    method: str  # effective: "hrr" | "max_pct" | "none"
    requested_method: str
    max_hr: Optional[float]
    resting_hr: Optional[float]
    bounds_pct: dict = field(default_factory=dict)
    rhr_source: str = "none"  # "setting" | "measured" | "measured_stale" | "none"
    rhr_window: Optional[list] = None  # [first ISO date, last ISO date] of the readings the median came from
    rhr_readings: int = 0
    reason: Optional[str] = None
    model: int = ZONES_MODEL

    def as_dict(self) -> dict:
        out = asdict(self)
        out["bounds_bpm"] = hr_zone_bounds(self)
        return out


def hr_basis(
    settings: dict | None = None,
    resting_hr: Optional[float] = None,
    *,
    rhr_source: str = "none",
    rhr_window: Optional[list] = None,
    rhr_readings: int = 0,
) -> HrBasis:
    settings = settings or DEFAULT_SETTINGS
    requested = settings.get("hr_zone_method") or "hrr"
    max_hr = settings.get("max_hr")
    zones = settings["zones"]
    rhr = resting_hr if resting_hr is not None and 30 <= resting_hr <= 100 else None
    if not max_hr:
        return HrBasis("none", requested, None, rhr, {}, rhr_source if rhr is not None else "none", rhr_window, rhr_readings, NO_MAX_HR)
    max_hr = float(max_hr)
    if requested == "hrr":
        if rhr is not None and max_hr - rhr >= MIN_RESERVE_BPM:
            return HrBasis("hrr", requested, max_hr, float(rhr), dict(zones["hrr_pct"]), rhr_source, rhr_window, rhr_readings)
        reason = FALLBACK_NO_RHR if rhr is None else FALLBACK_BAD_RESERVE
        return HrBasis("max_pct", requested, max_hr, rhr, dict(zones["hr_pct"]), rhr_source if rhr is not None else "none", rhr_window, rhr_readings, reason)
    return HrBasis("max_pct", requested, max_hr, rhr, dict(zones["hr_pct"]), rhr_source if rhr is not None else "none", rhr_window, rhr_readings)


def basis_from_dict(d: dict | None) -> Optional[HrBasis]:
    if not d:
        return None
    keys = {k: d.get(k) for k in ("method", "requested_method", "max_hr", "resting_hr", "bounds_pct", "rhr_source", "rhr_window", "rhr_readings", "reason")}
    keys["bounds_pct"] = keys["bounds_pct"] or {}
    keys["rhr_source"] = keys["rhr_source"] or "none"
    keys["rhr_readings"] = keys["rhr_readings"] or 0
    return HrBasis(model=d.get("model", 1), **keys)


def hr_zone_bounds(basis: HrBasis) -> dict[str, float]:
    """Each zone's lower bound in bpm. Karvonen for "hrr" (resting + reserve × %), max × % for "max_pct", empty without a max."""
    if basis.method == "none" or not basis.max_hr:
        return {}
    if basis.method == "hrr" and basis.resting_hr is not None:
        reserve = basis.max_hr - basis.resting_hr
        return {z: basis.resting_hr + reserve * basis.bounds_pct[z] / 100 for z in ZONE_ORDER}
    return {z: basis.max_hr * basis.bounds_pct[z] / 100 for z in ZONE_ORDER}


def zone_for_hr(hr: float | None, basis: HrBasis | None, bounds: dict[str, float] | None = None) -> str | None:
    """The zone `hr` falls in. Below UT2's lower bound still reads UT2 (as it always has); at exactly a bound, the higher zone.
    Pass `bounds` (from hr_zone_bounds) when classifying many samples against one basis."""
    if hr is None or basis is None:
        return None
    bounds = bounds if bounds is not None else hr_zone_bounds(basis)
    if not bounds:
        return None
    zone = ZONE_ORDER[0]
    for name in ZONE_ORDER:
        if hr >= bounds[name]:
            zone = name
    return zone


def training_zones(basis: HrBasis | None = None, watts_2k: float | None = None, settings: dict | None = None) -> dict:
    settings = settings or DEFAULT_SETTINGS
    basis = basis or hr_basis(settings)
    bounds = hr_zone_bounds(basis)
    power_pct = settings["zones"]["power_pct"]
    zones = []
    for i, name in enumerate(ZONE_ORDER):
        hi_name = ZONE_ORDER[i + 1] if i + 1 < len(ZONE_ORDER) else None
        hr_pct_lo = basis.bounds_pct.get(name) if basis.bounds_pct else None
        hr_pct_hi = basis.bounds_pct.get(hi_name) if (basis.bounds_pct and hi_name) else None
        power_pct_lo, power_pct_hi = power_pct[name], (power_pct[hi_name] if hi_name else None)
        zones.append(
            {
                "zone": name,
                "hr_pct_lo": hr_pct_lo,
                "hr_pct_hi": hr_pct_hi,
                "hr_lo": bounds.get(name) if bounds else None,
                "hr_hi": bounds.get(hi_name) if (bounds and hi_name) else None,
                "power_pct_lo": power_pct_lo,
                "power_pct_hi": power_pct_hi,
                "power_lo": watts_2k * power_pct_lo / 100 if watts_2k else None,
                "power_hi": watts_2k * power_pct_hi / 100 if (watts_2k and power_pct_hi) else None,
            }
        )
    return {"zones": zones, "note": ZONE_NOTE, "hr_basis": basis.as_dict()}


def zone_for_power(watts: float | None, watts_2k: float | None, settings: dict | None = None) -> str | None:
    if watts is None or not watts_2k:
        return None
    pct = watts / watts_2k * 100
    return _zone_for_pct(pct, (settings or DEFAULT_SETTINGS)["zones"]["power_pct"])


def _zone_for_pct(pct: float, bounds_pct: dict) -> str:
    zone = ZONE_ORDER[0]
    for name in ZONE_ORDER:
        if pct >= bounds_pct[name]:
            zone = name
    return zone
