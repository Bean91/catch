import dataclasses

import pytest

from catch.core import startup_checks
from catch.core.config import settings as real

GOOD = dict(ollama_enabled=False, secrets_master_key="m" * 40, secrets_master_key_previous="", tick_secret="t" * 40)


def _s(**over):
    return dataclasses.replace(real, **{**GOOD, **over})


def test_a_good_public_config_passes():
    startup_checks.enforce_public_config(_s())
    assert startup_checks.public_config_problems(_s(tick_secret="")) == []  # unset tick secret = routes 404, fine


@pytest.mark.parametrize(
    "override, needle",
    [
        ({"ollama_enabled": True}, "OLLAMA"),
        ({"secrets_master_key": ""}, "MASTER_KEY is not set"),
        ({"secrets_master_key": "short"}, "shorter"),
        ({"secrets_master_key_previous": "old," + "x" * 40}, "PREVIOUS"),
        ({"tick_secret": "abc"}, "TICK_SECRET"),
    ],
)
def test_each_unsafe_setting_refuses_startup(override, needle):
    with pytest.raises(RuntimeError) as exc:
        startup_checks.enforce_public_config(_s(**override))
    assert needle in str(exc.value)


def test_fernet_key_is_not_an_acceptable_master_on_public():
    with pytest.raises(RuntimeError):
        startup_checks.enforce_public_config(_s(secrets_master_key="", fernet_key="f" * 44))


def test_messages_never_contain_the_secret_values():
    with pytest.raises(RuntimeError) as exc:
        startup_checks.enforce_public_config(_s(secrets_master_key="supersecretvalue", tick_secret="tickvalue"))
    assert "supersecretvalue" not in str(exc.value) and "tickvalue" not in str(exc.value)
