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
