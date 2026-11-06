from __future__ import annotations

import pytest

from catch.analytics.nutrition import (
    grams_for_quantity,
    nutrition_targets,
    scale_macros_per_100g,
    training_tier,
    under_fuelling_flag,
)

SETTINGS = {
    "protein_g_per_kg": 1.6,
    "carb_g_per_kg_rest": 3.0,
    "carb_g_per_kg_moderate": 5.0,
    "carb_g_per_kg_double_day": 7.0,
    "carb_g_per_kg_pre_race": 8.0,
}


def test_grams_for_quantity_grams_passthrough():
    assert grams_for_quantity(150, "g", serving_size=None) == 150


def test_grams_for_quantity_serving_multiplies_by_serving_size():
    assert grams_for_quantity(2, "serving", serving_size=30) == 60


def test_grams_for_quantity_serving_without_known_size_returns_none():
    assert grams_for_quantity(2, "serving", serving_size=None) is None


def test_grams_for_quantity_non_positive_returns_none():
    assert grams_for_quantity(0, "g", serving_size=None) is None
    assert grams_for_quantity(-5, "g", serving_size=None) is None


def test_scale_macros_per_100g_handles_missing_fields():
    per_100g = {"kcal_100g": 200, "protein_100g": 20, "carbs_100g": None, "fat_100g": 10, "fiber_100g": 2, "sugar_100g": 5, "sodium_100g": 400}
    scaled = scale_macros_per_100g(per_100g, grams=50)
    assert scaled["kcal"] == 100
    assert scaled["protein"] == 10
    assert scaled["carbs"] is None
    assert scaled["fat"] == 5
    assert scaled["sodium"] == 200


def test_training_tier_rest_moderate_double_day():
    assert training_tier(0, days_to_a_race=None, taper=False) == "rest"
    assert training_tier(1, days_to_a_race=None, taper=False) == "moderate"
    assert training_tier(2, days_to_a_race=None, taper=False) == "double_day"
    assert training_tier(3, days_to_a_race=None, taper=False) == "double_day"


def test_training_tier_pre_race_overrides_even_a_double_day():
    assert training_tier(2, days_to_a_race=2, taper=True) == "pre_race"
    # Outside the 3-day carb-loading window, taper alone isn't enough.
    assert training_tier(1, days_to_a_race=10, taper=True) == "moderate"
    assert training_tier(0, days_to_a_race=3, taper=False) == "rest"  # taper flag required


def test_nutrition_targets_scales_with_weight_and_tier():
    result = nutrition_targets(weight_kg=70.0, kcal_target=None, tier="moderate", settings=SETTINGS)
    assert result["protein_g"] == pytest.approx(112.0)  # 1.6 * 70
    assert result["carb_g"] == pytest.approx(350.0)  # 5.0 * 70
    assert result["fat_g"] is None  # no kcal target yet


def test_nutrition_targets_fat_is_kcal_remainder():
    result = nutrition_targets(weight_kg=70.0, kcal_target=2800, tier="rest", settings=SETTINGS)
    protein_g = 1.6 * 70  # 112
    carb_g = 3.0 * 70  # 210
    2800 - protein_g * 4 - carb_g * 4  # 2800 - 448 - 840 = 1512
    assert result["fat_g"] == pytest.approx(1512 / 9)


def test_nutrition_targets_fat_never_negative_when_kcal_target_is_too_low():
    result = nutrition_targets(weight_kg=90.0, kcal_target=1000, tier="double_day", settings=SETTINGS)
    assert result["fat_g"] == 0.0


def test_nutrition_targets_without_weight_returns_none_targets():
    result = nutrition_targets(weight_kg=None, kcal_target=2500, tier="rest", settings=SETTINGS)
    assert result["protein_g"] is None
    assert result["carb_g"] is None
    assert result["fat_g"] is None


def test_under_fuelling_not_enough_logged_days():
    balances = [
        {"date": "2026-01-01", "intake_kcal": 1500, "expenditure_kcal": 2500, "has_log": True},
    ]
    result = under_fuelling_flag(balances, min_logged_days=3)
    assert result["flag"] is False
    assert result["logged_days"] == 1


def test_under_fuelling_ignores_unlogged_days_never_treats_them_as_zero_intake():
    balances = [
        {"date": "2026-01-01", "intake_kcal": 1500, "expenditure_kcal": 2500, "has_log": True},
        {"date": "2026-01-02", "intake_kcal": 0, "expenditure_kcal": 2500, "has_log": False},
        {"date": "2026-01-03", "intake_kcal": 1600, "expenditure_kcal": 2500, "has_log": True},
        {"date": "2026-01-04", "intake_kcal": 1700, "expenditure_kcal": 2500, "has_log": True},
    ]
    result = under_fuelling_flag(balances, min_logged_days=3, deficit_threshold_pct=0.25)
    assert result["logged_days"] == 3  # the unlogged day never counts
    assert result["flag"] is True


def test_under_fuelling_flags_only_when_every_recent_logged_day_is_short():
    balances = [
        {"date": "2026-01-01", "intake_kcal": 1500, "expenditure_kcal": 2500, "has_log": True},  # -40%
        {"date": "2026-01-02", "intake_kcal": 2400, "expenditure_kcal": 2500, "has_log": True},  # -4%, not a deficit day
        {"date": "2026-01-03", "intake_kcal": 1600, "expenditure_kcal": 2500, "has_log": True},  # -36%
    ]
    result = under_fuelling_flag(balances, min_logged_days=3, deficit_threshold_pct=0.25)
    assert result["flag"] is False  # one of the three recent days wasn't a real deficit


def test_under_fuelling_no_shaming_language_in_explanation():
    balances = [
        {"date": f"2026-01-0{i}", "intake_kcal": 1500, "expenditure_kcal": 2500, "has_log": True} for i in range(1, 4)
    ]
    result = under_fuelling_flag(balances, min_logged_days=3)
    assert result["flag"] is True
    lowered = result["explanation"].lower()
    for banned in ("shame", "fail", "bad", "warning", "!"):
        assert banned not in lowered
