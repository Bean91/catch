"""Session 34: two users of the public deployment connect two different Withings accounts through the real callback, interleaved, and sync.
Each user's tokens, Withings user id and measurements stay theirs; one user's state cookie can never complete a flow for the other."""

from __future__ import annotations

import time

import httpx
import pytest
from sqlalchemy import select
from sqlmodel import Session

from catch.core import tenant
from catch.core.models import BodyComp, ProviderConnection
from catch.sync import connections, scheduler
from tests import withings_fake as wf
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A, B = bearer(kit.ALICE), bearer(kit.BOB)
ALICE_W, BOB_W = 1111, 2222
NOW = int(time.time())


@pytest.fixture()
def fake(monkeypatch):
    f = wf.FakeWithings()
    wf.configure(monkeypatch, f)
    f.groups[ALICE_W] = [wf.group(11, NOW - 7200, 64.0), wf.group(12, NOW - 3600, 64.2)]
    f.groups[BOB_W] = [wf.group(21, NOW - 5400, 91.5)]
    monkeypatch.setattr("catch.sync.scoring.recompute_scores", lambda *a, **k: None)
    return f


@pytest.fixture()
def profiles(pub_client):
    for h in (A, B):
        assert pub_client.get("/api/me", headers=h).status_code == 200


def _start(client, headers):
    start = client.post("/api/connections/withings/oauth/start", headers=headers)
    assert start.status_code == 200
    return httpx.URL(start.json()["authorize_url"]).params["state"], start.cookies["catch_oauth_withings"]


def _callback(client, cookie, state, code):
    client.cookies.set("catch_oauth_withings", cookie)
    return client.get("/auth/withings/callback", params={"code": code, "state": state}, follow_redirects=False)


def test_two_users_connect_two_withings_accounts_without_crossover(pub_client, pub_engine, profiles, fake):
    # Interleaved: both start before either finishes.
    state_a, cookie_a = _start(pub_client, A)
    state_b, cookie_b = _start(pub_client, B)
    assert _callback(pub_client, cookie_b, state_b, fake.issue_code(BOB_W)).headers["location"].endswith("result=connected")
    assert _callback(pub_client, cookie_a, state_a, fake.issue_code(ALICE_W)).headers["location"].endswith("result=connected")

    with Session(pub_engine) as s:
        rows = {r.owner_id: r for r in s.execute(select(ProviderConnection).execution_options(tenant_unscoped=True)).scalars()}
    assert rows[kit.ALICE].account_id == str(ALICE_W) and rows[kit.BOB].account_id == str(BOB_W)
    assert rows[kit.ALICE].refresh_enc != rows[kit.BOB].refresh_enc

    for owner in (kit.ALICE, kit.BOB):
        with tenant.use_owner(owner):
            assert scheduler.run_sync("withings", manual=True).get("measures") is not None

    with Session(pub_engine) as s:
        body = s.execute(select(BodyComp).execution_options(tenant_unscoped=True)).scalars().all()
    by_owner = {}
    for row in body:
        by_owner.setdefault(row.owner_id, set()).add(row.external_id)
    assert by_owner == {kit.ALICE: {"11", "12"}, kit.BOB: {"21"}}

    # Each sees only their own card and body-comp through the API.
    for headers, expected in ((A, str(ALICE_W)), (B, str(BOB_W))):
        card = next(c for c in pub_client.get("/api/connections", headers=headers).json()["connections"] if c["provider"] == "withings")
        assert card["connected"] and expected not in str(card)  # the Withings user id is never sent to the browser either

    # Alice disconnecting revokes only her grant and leaves Bob syncing.
    assert pub_client.delete("/api/connections/withings", headers=A).json() == {"revoked": True, "was_connected": True}
    assert fake.revoked == [ALICE_W]
    with tenant.use_owner(kit.BOB):
        assert scheduler.run_sync("withings", manual=True).get("measures") is not None
        with Session(pub_engine) as s:
            assert connections.get(s, "withings").status == connections.CONNECTED


def test_one_users_state_cannot_attach_a_code_to_the_other(pub_client, pub_engine, profiles, fake):
    state_a, cookie_a = _start(pub_client, A)
    _, cookie_b = _start(pub_client, B)
    # Bob's cookie with Alice's state (or the reverse) is refused, whoever's bearer token the browser might also carry.
    pub_client.cookies.set("catch_oauth_withings", cookie_b)
    out = pub_client.get("/auth/withings/callback", params={"code": fake.issue_code(ALICE_W), "state": state_a}, headers=B, follow_redirects=False)
    assert out.status_code == 400
    # Alice's own cookie + state attaches the code to Alice even when Bob's bearer is sent along.
    out = _callback(pub_client, cookie_a, state_a, fake.issue_code(ALICE_W))
    assert out.headers["location"].endswith("result=connected")
    with Session(pub_engine) as s:
        owners = [r.owner_id for r in s.execute(select(ProviderConnection).execution_options(tenant_unscoped=True)).scalars()]
    assert owners == [kit.ALICE]
