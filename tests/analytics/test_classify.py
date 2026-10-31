from __future__ import annotations

from catch.analytics.classify import workout_category


def test_garmin_indoor_rowing_is_erg():
    assert workout_category("garmin", "indoor_rowing") == "erg"


def test_garmin_rowing_v2_is_on_water():
    # Live-DB-verified this session: every real rowing_v2 row carries GPS fields.
    assert workout_category("garmin", "rowing_v2") == "on_water"


def test_garmin_other_sport_is_other():
    assert workout_category("garmin", "strength_training") == "other"


def test_concept2_rower_is_erg():
    assert workout_category("concept2", "rower") == "erg"
    assert workout_category("concept2", "skierg") == "erg"


def test_concept2_water_and_paddle_are_on_water():
    assert workout_category("concept2", "water") == "on_water"
    assert workout_category("concept2", "paddle") == "on_water"


def test_concept2_snow_and_rollerski_are_other():
    assert workout_category("concept2", "snow") == "other"
    assert workout_category("concept2", "rollerski") == "other"


def test_unknown_source_is_other():
    assert workout_category(None, None) == "other"
