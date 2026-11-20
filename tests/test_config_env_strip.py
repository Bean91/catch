from catch.core.config import _get, load_settings


def test_unset_variable_returns_default(monkeypatch):
    monkeypatch.delenv("CATCH_TEST_UNSET", raising=False)
    assert _get("CATCH_TEST_UNSET") == ""
    assert _get("CATCH_TEST_UNSET", "fallback") == "fallback"


def test_trailing_newline_secret_is_stripped(monkeypatch):
    monkeypatch.setenv("WITHINGS_CLIENT_SECRET", "abc123\n")
    assert load_settings().withings_client_secret == "abc123"


def test_surrounding_whitespace_is_stripped(monkeypatch):
    monkeypatch.setenv("CATCH_TEST_PADDED", "  value \r\n")
    assert _get("CATCH_TEST_PADDED") == "value"


def test_multiline_value_keeps_inner_newlines(monkeypatch):
    pem = "-----BEGIN PRIVATE KEY-----\nAAAA\nBBBB\n-----END PRIVATE KEY-----\n"
    monkeypatch.setenv("VAPID_PRIVATE_KEY", pem)
    got = load_settings().vapid_private_key
    assert got == pem.strip()
    assert got.count("\n") == 3


def test_whitespace_only_value_is_empty_not_default(monkeypatch):
    monkeypatch.setenv("CATCH_TEST_BLANK", " \n")
    assert _get("CATCH_TEST_BLANK", "fallback") == ""
