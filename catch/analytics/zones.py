from __future__ import annotations

from catch.analytics.defaults import DEFAULT_SETTINGS

ZONE_ORDER = ["UT2", "UT1", "AT", "TR", "AN"]
ZONE_NOTE = "Zone boundaries are defaults — confirm with your coach before training off them."


def training_zones(max_hr: float | None = None, watts_2k: float | None = None, settings: dict | None = None) -> dict:
    settings = settings or DEFAULT_SETTINGS
    hr_pct = settings["zones"]["hr_pct"]
    power_pct = settings["zones"]["power_pct"]
    zones = []
    for i, name in enumerate(ZONE_ORDER):
        hi_name = ZONE_ORDER[i + 1] if i + 1 < len(ZONE_ORDER) else None
        hr_pct_lo, hr_pct_hi = hr_pct[name], (hr_pct[hi_name] if hi_name else None)
        power_pct_lo, power_pct_hi = power_pct[name], (power_pct[hi_name] if hi_name else None)
        zones.append(
            {
                "zone": name,
                "hr_pct_lo": hr_pct_lo,
                "hr_pct_hi": hr_pct_hi,
                "hr_lo": max_hr * hr_pct_lo / 100 if max_hr else None,
                "hr_hi": max_hr * hr_pct_hi / 100 if (max_hr and hr_pct_hi) else None,
                "power_pct_lo": power_pct_lo,
                "power_pct_hi": power_pct_hi,
                "power_lo": watts_2k * power_pct_lo / 100 if watts_2k else None,
                "power_hi": watts_2k * power_pct_hi / 100 if (watts_2k and power_pct_hi) else None,
            }
        )
    return {"zones": zones, "note": ZONE_NOTE}


def zone_for_hr(hr: float | None, max_hr: float | None, settings: dict | None = None) -> str | None:
    if hr is None or not max_hr:
        return None
    pct = hr / max_hr * 100
    return _zone_for_pct(pct, (settings or DEFAULT_SETTINGS)["zones"]["hr_pct"])


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
