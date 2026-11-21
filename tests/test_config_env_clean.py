import pytest

from catch.core import config


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("abc123", "abc123"),
        ("abc123\n", "abc123"),
        ("  abc123 ", "abc123"),
        ("'abc123'", "abc123"),
        ('"abc123"', "abc123"),
        ("'abc123'\n", "abc123"),
        ("'abc", "'abc"),  # an unbalanced quote is data, not decoration
        ("a'b'c", "a'b'c"),
        ("", ""),
    ],
)
def test_env_values_are_cleaned(monkeypatch, raw, expected):
    monkeypatch.setenv("CATCH_TEST_VALUE", raw)
    assert config._get("CATCH_TEST_VALUE") == expected


def test_a_pem_block_survives():
    pem = "-----BEGIN PRIVATE KEY-----\nMIGT\n-----END PRIVATE KEY-----"
    assert config._clean(pem + "\n") == pem
