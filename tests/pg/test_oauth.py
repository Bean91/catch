"""MCP OAuth storage on the real roles (session 28, migration 0008): the unauthenticated token endpoint can find an owner only through two
read-only definer lookups, and everything after that runs under that owner's own RLS context."""

import pytest
from sqlalchemy import text
from sqlmodel import Session

from catch.core import tenant
from catch.mcp_server import oauth
from tests.pg.conftest import signup


@pytest.fixture()
def system_role(runtime, monkeypatch):
    from catch.core import db as db_module

    monkeypatch.setattr(db_module, "engine", runtime)
    monkeypatch.setattr(tenant, "is_public", lambda: True)
    return runtime


def test_the_two_lookups_are_executable_by_the_runtime_role_only(system_role, admin, clean):
    with admin.connect() as conn:
        for fn in ("resolve_oauth_code(text)", "resolve_oauth_token(text)"):
            assert conn.execute(text(f"SELECT has_function_privilege('catch_api', 'catch_private.{fn}', 'EXECUTE')")).scalar() is True
            for role in ("anon", "authenticated"):
                assert conn.execute(text(f"SELECT has_function_privilege('{role}', 'catch_private.{fn}', 'EXECUTE')")).scalar() is False, (role, fn)
        for table in ("oauth_clients",):
            for role in ("authenticated", "anon"):
                assert conn.execute(text("SELECT has_table_privilege(:r, :t, 'SELECT')"), {"r": role, "t": f"catch.{table}"}).scalar() is False


def test_a_grant_round_trips_under_real_rls_and_only_its_owner_can_use_it(system_role, clean):
    alice, bob = signup("oa-a"), signup("oa-b")
    with tenant.use_owner(alice.id), Session(system_role) as s:
        code = oauth.create_code(s, client_id="c1", redirect_uri="https://x.example/cb", explicit=True, challenge="ch", scopes=["catch:read", "catch:write"], resource=oauth.resource_url())
    found = oauth.redeem_code("c1", code)
    assert found is not None and found.subject == alice.id
    assert oauth.redeem_code("someone-else", code) is None  # bound to the client it was issued for
    tok = oauth.exchange_code(found)
    p = oauth.access_principal(tok.access_token)
    assert p.owner_id == alice.id and p.scope == "write"
    # Bob's view of the same tables is empty, whatever the hashes are
    with tenant.use_owner(bob.id), Session(system_role) as s:
        assert oauth.list_grants(s) == []
        assert oauth.revoke_all(s) == 0
    assert oauth.access_principal(tok.access_token) is not None
    new = oauth.exchange_refresh(oauth.load_refresh("c1", tok.refresh_token), [])
    assert oauth.load_refresh("c1", tok.refresh_token).replayed is True  # the rotated-out token is recognised as a replay
    with pytest.raises(oauth._Fail):
        oauth.exchange_refresh(oauth.load_refresh("c1", tok.refresh_token), [])
    assert oauth.access_principal(new.access_token) is None  # and the replay ended the whole grant
