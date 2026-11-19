"""Moderation tables and the account-age function on the real roles (session 28, migration 0008)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from catch.core import tenant
from catch.sync import account_store, restrictions
from tests.pg.conftest import signup


@pytest.fixture()
def system_role(runtime, monkeypatch):
    from catch.core import db as db_module

    monkeypatch.setattr(db_module, "engine", runtime)
    monkeypatch.setattr(tenant, "is_public", lambda: True)  # production: no default owner, the store stays as catch_api
    return runtime


def test_account_age_comes_from_the_definer_function_not_a_table_grant(system_role, admin, clean):
    u = signup("age")
    assert account_store.account_age_days(u.id) == 0
    assert account_store.account_age_days("00000000-0000-4000-8000-000000000000") is None
    with admin.connect() as conn:  # catch_api itself can't read the table
        assert conn.execute(text("SELECT has_table_privilege('catch_api', 'catch.user_profiles', 'SELECT')")).scalar() is False
        assert conn.execute(text("SELECT has_function_privilege('authenticated', 'catch_private.account_age_days(text)', 'EXECUTE')")).scalar() is False
        assert conn.execute(text("SELECT has_function_privilege('catch_api', 'catch_private.account_age_days(text)', 'EXECUTE')")).scalar() is True


def test_the_report_rule_uses_the_real_age(system_role, clean, monkeypatch):
    fresh = signup("fresh")
    monkeypatch.setattr(account_store, "MIN_REPORTER_AGE_DAYS", 7)
    assert account_store.eligible_reporters([fresh.id]) == 0
    monkeypatch.setattr(account_store, "MIN_REPORTER_AGE_DAYS", 0)
    assert account_store.eligible_reporters([fresh.id]) == 1


def test_the_moderation_trail_is_append_only_and_unreachable_by_users(system_role, admin, runtime, clean):
    with admin.connect() as conn:
        for table in ("moderation_actions", "moderator_access_log", "account_restrictions", "deleted_accounts"):
            for role in ("authenticated", "anon", "service_role"):
                assert conn.execute(text("SELECT has_table_privilege(:r, :t, 'SELECT,INSERT,UPDATE,DELETE')"), {"r": role, "t": f"catch.{table}"}).scalar() is False, (role, table)
        for table in ("moderation_actions", "moderator_access_log"):
            assert conn.execute(text("SELECT has_table_privilege('catch_api', :t, 'UPDATE')"), {"t": f"catch.{table}"}).scalar() is False
            assert conn.execute(text("SELECT has_table_privilege('catch_api', :t, 'DELETE')"), {"t": f"catch.{table}"}).scalar() is False
    u = signup("restricted")
    mod = signup("mod")
    r = restrictions.restrict(mod.id, u.id, "clubs", "abuse", "Because", days=3)
    assert r["active"] is True
    with pytest.raises(restrictions.Restricted):
        restrictions.assert_allowed(u.id, "clubs")
    restrictions.assert_allowed(u.id, "publish")  # a different capability
    with runtime.begin() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("DELETE FROM catch.moderation_actions"))
    restrictions.lift(mod.id, r["id"], "Served")
    restrictions.assert_allowed(u.id, "clubs")
    assert [a["action"] for a in restrictions.actions()] == ["lift", "restrict"]
