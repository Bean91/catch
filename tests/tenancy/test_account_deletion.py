"""Account deletion (session 28): a recent real sign-in, throttled, ordered so nothing is left that only a retry could clean,
and a token that outlives the account can never bring the profile back."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from catch.api import deps, routes_account
from catch.coach import limits
from catch.core import supabase_auth
from catch.core.models import DeletedAccount, UserProfile
from catch.sync import account_store
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

DELETE = {"confirm": "DELETE"}


@pytest.fixture(autouse=True)
def _fresh_limits():
    limits._windows.clear()
    yield
    limits._windows.clear()


@pytest.fixture()
def calls(monkeypatch):
    log: list[str] = []
    monkeypatch.setattr(routes_account, "purge_storage", lambda token, owner: log.append("storage") or 0)
    monkeypatch.setattr(routes_account, "delete_global_rows", lambda owner: log.append("global_rows"))
    monkeypatch.setattr(routes_account, "admin_delete_auth_user", lambda owner: log.append("auth_delete"))
    real_mark = account_store.mark_deleted
    monkeypatch.setattr(account_store, "mark_deleted", lambda o: log.append("tombstone") or real_mark(o))
    return log


def _profiles(engine):
    with Session(engine) as s:
        return [p.id for p in s.execute(select(UserProfile).execution_options(tenant_unscoped=True)).scalars()]


def _tombstones(engine):
    with Session(engine) as s:
        return [t.user_id for t in s.execute(select(DeletedAccount).execution_options(tenant_unscoped=True)).scalars()]


def _signed_up(pub_client, headers):
    assert pub_client.get("/api/me", headers=headers).status_code == 200


def test_an_old_or_unstamped_sign_in_cannot_delete_the_account(pub_client, pub_engine, calls):
    for kw in ({"amr_age": 3600}, {"amr_age": None}):
        h = bearer(kit.ALICE, **kw)
        _signed_up(pub_client, h)
        resp = pub_client.request("DELETE", "/api/account", headers=h, json=DELETE)
        assert resp.status_code == 403 and resp.json()["detail"] == "reauth_required"
    assert calls == [] and kit.ALICE in _profiles(pub_engine)


def test_a_refreshed_token_does_not_count_as_a_fresh_sign_in(pub_client, pub_engine, calls):
    # `iat` is brand new (a silent refresh minted it) but the sign-in itself was an hour ago.
    h = bearer(kit.ALICE, amr_age=3600)
    _signed_up(pub_client, h)
    assert pub_client.request("DELETE", "/api/account", headers=h, json=DELETE).status_code == 403


def test_the_steps_run_in_a_safe_order_and_the_account_is_gone(pub_client, pub_engine, calls):
    h = bearer(kit.ALICE)
    _signed_up(pub_client, h)
    resp = pub_client.request("DELETE", "/api/account", headers=h, json=DELETE)
    assert resp.status_code == 200 and resp.json()["deleted"] is True
    assert calls == ["storage", "global_rows", "tombstone", "auth_delete"]
    assert kit.ALICE not in _profiles(pub_engine) and _tombstones(pub_engine) == [kit.ALICE]


def test_a_token_that_outlives_the_account_cannot_recreate_the_profile(pub_client, pub_engine, calls):
    h = bearer(kit.ALICE)
    _signed_up(pub_client, h)
    assert pub_client.request("DELETE", "/api/account", headers=h, json=DELETE).status_code == 200
    # Same replica: the session is remembered as dead.
    assert pub_client.get("/api/me", headers=h).status_code == 401
    # Another replica: it never saw the deletion, so its session cache says "alive" and it has no profile cached.
    supabase_auth.liveness.reset()
    deps._profiles_known.clear()
    assert pub_client.get("/api/me", headers=h).status_code == 401
    assert kit.ALICE not in _profiles(pub_engine)


def test_when_the_sign_in_service_refuses_the_person_can_simply_retry(pub_client, pub_engine, calls, monkeypatch):
    h = bearer(kit.ALICE)
    _signed_up(pub_client, h)
    attempts = {"n": 0}

    def flaky(owner):
        attempts["n"] += 1
        calls.append("auth_delete")
        if attempts["n"] == 1:
            raise HTTPException(status_code=502, detail="Could not delete the sign-in account")

    monkeypatch.setattr(routes_account, "admin_delete_auth_user", flaky)
    assert pub_client.request("DELETE", "/api/account", headers=h, json=DELETE).status_code == 502
    # Still exists and still signed in: no tombstone, so the account is not wrongly locked out.
    assert _tombstones(pub_engine) == [] and kit.ALICE in _profiles(pub_engine)
    assert pub_client.get("/api/me", headers=h).status_code == 200
    assert pub_client.request("DELETE", "/api/account", headers=h, json=DELETE).status_code == 200
    assert kit.ALICE not in _profiles(pub_engine)


def test_a_failed_storage_purge_deletes_nothing(pub_client, pub_engine, calls, monkeypatch):
    import httpx

    h = bearer(kit.ALICE)
    _signed_up(pub_client, h)

    def boom(token, owner):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(routes_account, "purge_storage", boom)
    assert pub_client.request("DELETE", "/api/account", headers=h, json=DELETE).status_code == 502
    assert calls == [] and kit.ALICE in _profiles(pub_engine) and _tombstones(pub_engine) == []


def test_the_confirmation_word_is_required_and_deletion_is_throttled(pub_client, pub_engine, calls):
    h = bearer(kit.ALICE, amr_age=3600)  # the throttle runs before the (cheaper to evade) re-auth check
    _signed_up(pub_client, h)
    assert pub_client.request("DELETE", "/api/account", headers=h, json={"confirm": "nope"}).status_code == 400
    codes = [pub_client.request("DELETE", "/api/account", headers=h, json=DELETE).status_code for _ in range(4)]
    assert codes[-1] == 429


def test_another_users_tombstone_does_not_affect_me(pub_client, pub_engine, calls):
    account_store.mark_deleted(kit.BOB)
    assert account_store.is_deleted(kit.BOB) and not account_store.is_deleted(kit.ALICE)
    _signed_up(pub_client, bearer(kit.ALICE))
