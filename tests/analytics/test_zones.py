from __future__ import annotations

import pytest

from catch.analytics.zones import training_zones, zone_for_hr, zone_for_power


def test_training_zones_hr_bounds():
    result = training_zones(max_hr=190)
    zones = {z["zone"]: z for z in result["zones"]}
    assert zones["UT2"]["hr_lo"] == pytest.approx(190 * 0.60)
    assert zones["UT2"]["hr_hi"] == pytest.approx(190 * 0.70)
    assert zones["AN"]["hr_hi"] is None  # top zone is open-ended
    assert "defaults" in result["note"].lower()


def test_training_zones_without_max_hr_returns_percentages_only():
    result = training_zones()
    zones = {z["zone"]: z for z in result["zones"]}
    assert zones["UT1"]["hr_lo"] is None
    assert zones["UT1"]["hr_pct_lo"] == 70


def test_zone_for_hr():
    # 150/190 = 78.9% -> between UT1 (70%) and AT (80%).
    assert zone_for_hr(150, 190) == "UT1"
    assert zone_for_hr(None, 190) is None
    assert zone_for_hr(150, None) is None


def test_zone_for_power():
    watts_2k = 300.0
    # 90% of 2k watts -> between TR (85%) and AN (95%).
    assert zone_for_power(270.0, watts_2k) == "TR"
    assert zone_for_power(None, watts_2k) is None
