from __future__ import annotations

from catch.coach import settings as coach_settings


def test_default_settings_when_unset(session):
    prefs = coach_settings.get_coach_settings(session)
    assert prefs["provider"] == "anthropic"
    assert prefs["anthropic_model"] is None
    assert prefs["prices"] == {}


def test_update_rejects_unknown_key(session):
    try:
        coach_settings.update_coach_settings(session, {"nonsense": 1})
        assert False, "should have raised"
    except ValueError:
        pass


def test_update_rejects_bad_provider(session):
    try:
        coach_settings.update_coach_settings(session, {"provider": "openai"})
        assert False, "should have raised"
    except ValueError:
        pass


def test_update_merges_prices_by_model(session):
    coach_settings.update_coach_settings(session, {"prices": {"claude-sonnet-5": {"input": 2.0, "output": 10.0}}})
    coach_settings.update_coach_settings(session, {"prices": {"claude-opus-5": {"input": 5.0, "output": 25.0}}})
    prefs = coach_settings.get_coach_settings(session)
    assert prefs["prices"]["claude-sonnet-5"]["input"] == 2.0
    assert prefs["prices"]["claude-opus-5"]["output"] == 25.0


def test_update_rejects_unknown_price_field(session):
    try:
        coach_settings.update_coach_settings(session, {"prices": {"claude-sonnet-5": {"bogus": 1.0}}})
        assert False, "should have raised"
    except ValueError:
        pass


def test_set_and_mask_credential(session):
    info = coach_settings.set_credential(session, "anthropic", "sk-ant-1234567890abcd")
    assert info == {"configured": True, "last4": "abcd"}
    assert coach_settings.masked_credential_info(session, "anthropic") == {"configured": True, "last4": "abcd"}
    assert coach_settings.get_decrypted_credential(session, "anthropic") == "sk-ant-1234567890abcd"


def test_masked_credential_info_when_unset(session):
    assert coach_settings.masked_credential_info(session, "anthropic") == {"configured": False, "last4": None}
    assert coach_settings.get_decrypted_credential(session, "anthropic") is None


def test_delete_credential(session):
    coach_settings.set_credential(session, "anthropic", "sk-ant-abc")
    assert coach_settings.delete_credential(session, "anthropic") is True
    assert coach_settings.delete_credential(session, "anthropic") is False
    assert coach_settings.masked_credential_info(session, "anthropic")["configured"] is False
