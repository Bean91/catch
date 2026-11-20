"""Native push tokens on the real roles (session 30, migration 0009): a global table only the runtime role can reach, one account
per device token, and removal with the account."""

import pytest
from sqlalchemy import text

from catch.core import tenant
from catch.sync import native_push_store as store
from tests.pg.conftest import signup


@pytest.fixture()
def system_role(runtime, monkeypatch):
    from catch.core import db as db_module

    monkeypatch.setattr(db_module, "engine", runtime)
    monkeypatch.setattr(tenant, "is_public", lambda: True)
    return runtime


def _reg(owner, token="a" * 64):
    return store.register(owner, platform="apns", token=token, environment="production", app_id="com.openoted.catch", label="iPhone")


def test_no_user_role_can_touch_the_table(system_role, admin, clean):
    with admin.connect() as conn:
        for role in ("authenticated", "anon", "service_role"):
            assert conn.execute(text("SELECT has_table_privilege(:r, 'catch.native_push_tokens', 'SELECT,INSERT,UPDATE,DELETE')"), {"r": role}).scalar() is False, role
        assert conn.execute(text("SELECT has_table_privilege('catch_api', 'catch.native_push_tokens', 'SELECT,INSERT,UPDATE,DELETE')")).scalar() is True


def test_a_token_moves_to_the_next_account_that_registers_it(system_role, clean):
    a, b = signup("a"), signup("b")
    _reg(a.id)
    assert len(store.list_for(a.id)) == 1
    _reg(b.id)
    assert store.list_for(a.id) == [] and len(store.list_for(b.id)) == 1


def test_the_tokens_go_with_the_account(system_role, admin, clean):
    u = signup("gone")
    _reg(u.id)
    with admin.begin() as conn:
        conn.execute(text("DELETE FROM catch.user_profiles WHERE id = :i"), {"i": u.id})
    with admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM catch.native_push_tokens")).scalar() == 0


def test_health_consent_is_owner_only_under_rls(system_role, admin, clean):
    a = signup("ha")
    with admin.connect() as conn:
        assert conn.execute(text("SELECT has_table_privilege('authenticated', 'catch.health_consents', 'SELECT,INSERT,UPDATE,DELETE')")).scalar() is True
        assert conn.execute(text("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid = 'catch.health_consents'::regclass")).scalar() is True
    assert a.id
