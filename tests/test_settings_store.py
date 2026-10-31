from __future__ import annotations

import pytest

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.core.settings_store import get_settings, update_settings


def test_get_settings_returns_defaults_with_no_overrides(session):
    assert get_settings(session) == DEFAULT_SETTINGS


def test_update_settings_merges_nested_dict_without_dropping_siblings(session):
    update_settings(session, {"recovery_weights": {"hrv": 0.5}})
    settings = get_settings(session)
    assert settings["recovery_weights"]["hrv"] == 0.5
    assert settings["recovery_weights"]["sleep"] == DEFAULT_SETTINGS["recovery_weights"]["sleep"]


def test_update_settings_persists_across_calls(session):
    update_settings(session, {"max_hr": 185})
    update_settings(session, {"recovery_green": 70})
    settings = get_settings(session)
    assert settings["max_hr"] == 185
    assert settings["recovery_green"] == 70


def test_update_settings_rejects_unknown_top_level_key(session):
    with pytest.raises(ValueError, match="Unknown setting key"):
        update_settings(session, {"not_a_real_setting": 1})


def test_update_settings_rejects_unknown_nested_key(session):
    with pytest.raises(ValueError, match="Unknown key"):
        update_settings(session, {"recovery_weights": {"bogus": 1}})


def test_update_settings_rejects_bad_zone_mode(session):
    with pytest.raises(ValueError, match="zone_mode must be one of"):
        update_settings(session, {"zone_mode": "bogus"})


def test_update_settings_accepts_valid_units(session):
    update_settings(session, {"units": "imperial"})
    assert get_settings(session)["units"] == "imperial"


def test_update_settings_rejects_bad_garmin_key_expiry(session):
    with pytest.raises(ValueError, match="garmin_key_expires_on"):
        update_settings(session, {"garmin_key_expires_on": "not-a-date"})


def test_update_settings_accepts_valid_garmin_key_expiry(session):
    update_settings(session, {"garmin_key_expires_on": "2027-03-01"})
    assert get_settings(session)["garmin_key_expires_on"] == "2027-03-01"
