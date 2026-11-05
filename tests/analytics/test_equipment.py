from __future__ import annotations

from catch.analytics.equipment import (
    DEFAULT_UNKNOWN_SMITH_BAR_KG,
    assisted_bodyweight_load,
    band_load,
    barbell_load,
    bodyweight_load,
    cable_load,
    dumbbell_or_kettlebell_load,
    machine_plate_load,
    plates_per_side,
    selectorized_load,
    smith_load,
    weighted_bodyweight_load,
)


def test_barbell_default_bar_weight():
    r = barbell_load(60.0)
    assert r.effective_load_kg == 80.0
    assert not r.is_estimated


def test_barbell_custom_bar_weight():
    r = barbell_load(60.0, bar_weight_kg=15.0)
    assert r.effective_load_kg == 75.0


def test_smith_unknown_bar_weight_is_estimated():
    r = smith_load(50.0, bar_weight_kg=None)
    assert r.is_estimated
    assert r.effective_load_kg == 50.0 + DEFAULT_UNKNOWN_SMITH_BAR_KG
    assert "default" in r.note.lower()


def test_smith_known_counterbalanced_bar_weight():
    r = smith_load(50.0, bar_weight_kg=8.0)
    assert not r.is_estimated
    assert r.effective_load_kg == 58.0


def test_dumbbell_bilateral_doubles_per_hand():
    r = dumbbell_or_kettlebell_load(20.0, bilateral=True)
    assert r.effective_load_kg == 40.0


def test_dumbbell_unilateral_single_hand():
    r = dumbbell_or_kettlebell_load(20.0, bilateral=False)
    assert r.effective_load_kg == 20.0


def test_machine_plate_load_with_base_weight():
    r = machine_plate_load(45.0, base_weight_kg=5.0)
    assert r.effective_load_kg == 50.0


def test_selectorized_stack_number_calibration():
    # a gym whose stack numbers are already in kg.
    assert selectorized_load(12.0).effective_load_kg == 12.0
    # a gym whose stack is calibrated in lb-equivalent increments of 2.27kg.
    r = selectorized_load(12.0, kg_per_increment=2.27)
    assert abs(r.effective_load_kg - 27.24) < 1e-9


def test_cable_pulley_multiplier_halves_felt_load():
    r = cable_load(40.0, pulley_multiplier=0.5)
    assert r.effective_load_kg == 20.0


def test_cable_default_is_1_to_1():
    r = cable_load(40.0)
    assert r.effective_load_kg == 40.0


def test_bodyweight_requires_a_known_weight():
    r = bodyweight_load(None)
    assert r.effective_load_kg is None
    assert r.is_estimated
    r2 = bodyweight_load(75.0)
    assert r2.effective_load_kg == 75.0
    assert not r2.is_estimated


def test_weighted_adds_to_bodyweight():
    r = weighted_bodyweight_load(75.0, added_weight_kg=10.0)
    assert r.effective_load_kg == 85.0


def test_weighted_without_bodyweight_is_estimated_added_only():
    r = weighted_bodyweight_load(None, added_weight_kg=10.0)
    assert r.effective_load_kg == 10.0
    assert r.is_estimated


def test_assisted_subtracts_from_bodyweight():
    r = assisted_bodyweight_load(75.0, assistance_kg=20.0)
    assert r.effective_load_kg == 55.0


def test_assisted_never_goes_negative():
    r = assisted_bodyweight_load(75.0, assistance_kg=200.0)
    assert r.effective_load_kg == 0.0


def test_band_tag_lookup():
    r = band_load("medium")
    assert r.effective_load_kg == 20.0
    assert r.is_estimated


def test_band_unknown_tag():
    r = band_load("nonexistent")
    assert r.effective_load_kg is None


def test_plates_per_side_exact():
    plates, remainder = plates_per_side(100.0)  # 50kg/side — greedy uses two 25s first.
    assert plates == [25.0, 25.0]
    assert remainder == 0.0


def test_plates_per_side_exact_with_limited_supply():
    plates, remainder = plates_per_side(100.0, available_kg=[25.0, 20.0, 15.0, 10.0, 5.0])
    assert plates == [25.0, 25.0]
    assert remainder == 0.0


def test_plates_per_side_with_remainder():
    plates, remainder = plates_per_side(101.0, available_kg=[25.0, 20.0, 10.0])  # 50.5kg/side
    assert sum(plates) == 50.0
    assert remainder == 0.5


def test_plates_per_side_zero():
    plates, remainder = plates_per_side(0.0)
    assert plates == []
    assert remainder == 0.0
