import dataclasses

import pytest

from catch.core import startup_checks
from catch.core.config import settings as real

GOOD = dict(
    ollama_enabled=False, secrets_master_key="m" * 40, secrets_master_key_previous="", tick_secret="t" * 40,
    base_url="https://catch.example.com", database_url="postgresql://catch_api.ref:pw@aws-0-eu.pooler.supabase.com:5432/postgres", db_pool_mode="session",
)


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
        ({"base_url": "http://localhost:8000"}, "BASE_URL"),
        ({"base_url": "http://catch.example.com"}, "https://"),
        ({"base_url": "https://127.0.0.1"}, "loopback"),
        ({"db_pool_mode": "pgbouncer"}, "POOL_MODE"),
        ({"database_url": "postgresql://u:pw@h.pooler.supabase.com:6543/postgres"}, "6543"),
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


def test_transaction_pooler_port_with_transaction_mode_is_fine():
    url = "postgresql://u:pw@h.pooler.supabase.com:6543/postgres"
    assert startup_checks.public_config_problems(_s(database_url=url, db_pool_mode="transaction")) == []


def test_warnings_for_missing_tick_secret_and_frontend(tmp_path):
    msgs = startup_checks.warnings(_s(tick_secret=""), tmp_path / "index.html")
    assert any("TICK_SECRET" in m for m in msgs) and any("index.html" in m for m in msgs)
    (tmp_path / "index.html").write_text("x")
    assert startup_checks.warnings(_s(), tmp_path / "index.html") == []


def test_expected_schema_revision_is_the_real_migration_head():
    import re
    from pathlib import Path

    from catch.core import db_pg

    versions = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    revs, downs = {}, set()
    for f in versions.glob("*.py"):
        text = f.read_text()
        revs[re.search(r'^revision = "(\w+)"', text, re.M).group(1)] = f
        d = re.search(r'^down_revision = "(\w+)"', text, re.M)
        if d:
            downs.add(d.group(1))
    assert set(revs) - downs == {db_pg.EXPECTED_SCHEMA_REVISION}


def test_env_secrets_are_redacted_from_logs():
    from catch.core import redact

    s = _s(tick_secret="opaque-secret-value-1234", database_url="postgresql://u:hunter2hunter2@h:5432/db")
    redact.register_env_secrets(s)
    try:
        out = redact.redact("boom opaque-secret-value-1234 and hunter2hunter2 and " + "m" * 40)
        assert "opaque-secret-value-1234" not in out and "hunter2hunter2" not in out and "m" * 40 not in out
    finally:
        for v in ("opaque-secret-value-1234", "hunter2hunter2", "m" * 40):
            redact.forget_secret(v)


def test_configured_secrets_survive_the_rotating_registry_filling_up():
    from catch.core import redact

    redact.register_env_secrets(_s(tick_secret="pinned-deployment-secret-9876"))
    try:
        for i in range(redact._MAX_REGISTERED + 20):  # per-user / hourly-rotating credentials churn through the LRU
            redact.register_secret(f"rotating-credential-{i:04d}")
        assert "pinned-deployment-secret-9876" not in redact.redact("x pinned-deployment-secret-9876 y")
    finally:
        redact.forget_secret("pinned-deployment-secret-9876")
        for i in range(redact._MAX_REGISTERED + 20):
            redact.forget_secret(f"rotating-credential-{i:04d}")


def test_local_base_url_escape_hatch_is_loud(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("CATCH_ALLOW_LOCAL_BASE_URL", "1")
    with caplog.at_level(logging.WARNING, logger="catch"):
        assert startup_checks.public_config_problems(_s(base_url="http://localhost:8000")) == []
    assert any("CATCH_ALLOW_LOCAL_BASE_URL" in r.getMessage() for r in caplog.records)
    monkeypatch.delenv("CATCH_ALLOW_LOCAL_BASE_URL")
    assert startup_checks.public_config_problems(_s(base_url="http://localhost:8000"))


def test_config_check_reports_set_or_unset_never_a_value():
    import dataclasses

    from fastapi.testclient import TestClient

    import catch.main as main
    from catch.api import routes_internal as ri
    from catch.core import config, tenant

    probe = dataclasses.replace(config.settings, whoop_client_id="whoop-id-VALUE", whoop_client_secret="", whoop_redirect_uri="https://catch.example.com/auth/whoop/callback", withings_redirect_uri="", concept2_redirect_uri="",
                                base_url="https://catch.example.com", tick_secret="t" * 40)
    real = tenant.is_public
    tenant.is_public = lambda: True
    saved = ri.settings
    ri.settings = probe
    try:
        resp = TestClient(main.app).get("/internal/config-check", headers={"authorization": "Bearer " + "t" * 40})
    finally:
        ri.settings = saved
        tenant.is_public = real
    assert resp.status_code == 200
    body = resp.json()
    assert body["set"]["WHOOP_CLIENT_ID"] is True and body["set"]["WHOOP_CLIENT_SECRET"] is False
    assert body["redirect_matches_expected"] == {"WHOOP_REDIRECT_URI": True}
    assert "whoop-id-VALUE" not in resp.text and "t" * 40 not in resp.text
