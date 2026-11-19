"""MCP OAuth 2.1 (session 28), against a synthetic client only — no real Claude Desktop/Claude.ai connector was run. The real SDK routes
(/register, /authorize, /token, /revoke) are mounted on a test app and driven end to end; consent runs through Catch's own API."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp.server.auth.routes import create_auth_routes
from pydantic import AnyHttpUrl
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from sqlmodel import Session, select
from starlette.applications import Starlette
from starlette.testclient import TestClient

from catch.coach import tools
from catch.core import config, tenant
from catch.core.models import OAuthGrant
from catch.mcp_server import oauth
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

ALICE, BOB = kit.ALICE, kit.BOB
ISSUER = "https://catch.test"
REDIRECT = "https://client.example/callback"


@pytest.fixture()
def env(pub_client, pub_engine):
    saved = (config.settings.base_url, config.settings.mcp_oauth_enabled)
    object.__setattr__(config.settings, "base_url", ISSUER)
    object.__setattr__(config.settings, "mcp_oauth_enabled", True)
    app = Starlette(routes=create_auth_routes(
        oauth.provider, issuer_url=AnyHttpUrl(ISSUER),
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=list(oauth.SCOPES), default_scopes=["catch:read"]),
        revocation_options=RevocationOptions(enabled=True),
    ))
    server = TestClient(app, base_url=ISSUER)
    for sub in (ALICE, BOB):
        assert pub_client.get("/api/me", headers=bearer(sub)).status_code == 200
    yield type("Env", (), {"web": pub_client, "oauth": server, "engine": pub_engine})
    object.__setattr__(config.settings, "base_url", saved[0])
    object.__setattr__(config.settings, "mcp_oauth_enabled", saved[1])


def pkce():
    verifier = secrets.token_urlsafe(48)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def register(env, **over):
    body = {"redirect_uris": [REDIRECT], "client_name": "Test MCP client", "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "scope": "catch:read catch:write", **over}
    return env.oauth.post("/register", json=body)


def start(env, client_id, challenge, *, scope="catch:read catch:write", resource=None, state="st123"):
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": challenge, "code_challenge_method": "S256", "scope": scope, "state": state}
    if resource:
        params["resource"] = resource
    return env.oauth.get("/authorize", params=params, follow_redirects=False)


def consent(env, location, who=ALICE, approve=True, scopes=None):
    req = parse_qs(urlsplit(location).query)["req"][0]
    info = env.web.get("/api/oauth/authorization-request", params={"req": req}, headers=bearer(who))
    done = env.web.post("/api/oauth/authorize", headers=bearer(who), json={"req": req, "approve": approve, **({"scopes": scopes} if scopes is not None else {})})
    return info, done


def get_code(done):
    q = parse_qs(urlsplit(done.json()["redirect_url"]).query)
    return q


def token(env, client_id, code, verifier, **over):
    return env.oauth.post("/token", data={"grant_type": "authorization_code", "client_id": client_id, "code": code, "code_verifier": verifier, "redirect_uri": REDIRECT, **over})


def full_flow(env, who=ALICE, scopes=None, scope="catch:read catch:write"):
    client = register(env).json()["client_id"]
    verifier, challenge = pkce()
    loc = start(env, client, challenge, scope=scope).headers["location"]
    info, done = consent(env, loc, who, scopes=scopes)
    code = get_code(done)["code"][0]
    tok = token(env, client, code, verifier).json()
    return client, tok


# ---- registration -------------------------------------------------------------------------------------------------------------------

def test_a_public_client_registers_and_nothing_secret_is_issued(env):
    r = register(env)
    assert r.status_code == 201 and r.json()["client_id"] and not r.json().get("client_secret")


@pytest.mark.parametrize("over", [
    {"redirect_uris": ["http://evil.example/cb"]},               # plain http, not loopback
    {"redirect_uris": ["https://x.example/cb#frag"]},            # fragment
    {"redirect_uris": [f"https://x{i}.example/cb" for i in range(9)]},  # too many
    {"token_endpoint_auth_method": "client_secret_post"},         # confidential clients aren't accepted
    {"scope": "catch:admin"},                                      # unknown scope
    {"client_name": "x" * 200},
])
def test_unsafe_registrations_are_refused(env, over):
    assert register(env, **over).status_code == 400


def test_a_loopback_http_redirect_is_allowed_for_native_apps(env):
    assert register(env, redirect_uris=["http://127.0.0.1:8123/callback"]).status_code == 201


# ---- the flow -----------------------------------------------------------------------------------------------------------------------

def test_authorize_only_redirects_to_consent_and_nothing_is_granted_without_the_person(env):
    client = register(env).json()["client_id"]
    _, challenge = pkce()
    r = start(env, client, challenge)
    assert r.status_code == 302 and r.headers["location"].startswith(f"{ISSUER}/oauth/consent?req=")
    with Session(env.engine) as s:
        assert s.execute(select(OAuthGrant).execution_options(tenant_unscoped=True)).scalars().all() == []


def test_the_whole_flow_gives_a_working_scoped_token_bound_to_the_person(env):
    client, tok = full_flow(env)
    assert tok["token_type"].lower() == "bearer" and tok["expires_in"] == oauth.ACCESS_TTL_S and tok["refresh_token"] and set(tok["scope"].split()) == {"catch:read", "catch:write"}
    p = oauth.access_principal(tok["access_token"])
    assert p is not None and p.owner_id == ALICE and p.scope == "write"
    # a different person's consent yields that person's identity, never Alice's
    _, bob_tok = full_flow(env, who=BOB)
    assert oauth.access_principal(bob_tok["access_token"]).owner_id == BOB


def test_the_consent_page_shows_who_is_asking_and_what_for(env):
    client = register(env).json()["client_id"]
    _, challenge = pkce()
    loc = start(env, client, challenge).headers["location"]
    info, _ = consent(env, loc)
    body = info.json()
    assert body["client_name"] == "Test MCP client" and body["redirect_host"] == "client.example"
    assert [s["scope"] for s in body["scopes"]] == ["catch:read", "catch:write"] and "confirm" in body["scopes"][1]["text"]


def test_the_person_can_grant_less_than_was_asked_and_write_never_comes_without_read(env):
    _, tok = full_flow(env, scopes=["catch:read"])
    p = oauth.access_principal(tok["access_token"])
    assert p.scope == "read" and tok["scope"] == "catch:read"
    with tenant.use_owner(ALICE), Session(env.engine) as s, pytest.raises(ValueError, match="scope"):
        tools.call_tool(s, "add_note", {"date": "2026-11-02", "text": "x", "confirm": True}, ctx={"principal": p, "via": "mcp"})
    _, only_write = full_flow(env, scopes=["catch:write"])
    assert set(only_write["scope"].split()) == {"catch:read", "catch:write"}


def test_refusing_redirects_with_access_denied_and_grants_nothing(env):
    client = register(env).json()["client_id"]
    _, challenge = pkce()
    _, done = consent(env, start(env, client, challenge).headers["location"], approve=False)
    q = get_code(done)
    assert q["error"] == ["access_denied"] and q["state"] == ["st123"] and "code" not in q


# ---- the token endpoint -------------------------------------------------------------------------------------------------------------

def test_pkce_is_mandatory_and_the_wrong_verifier_fails(env):
    client = register(env).json()["client_id"]
    verifier, challenge = pkce()
    _, done = consent(env, start(env, client, challenge).headers["location"])
    code = get_code(done)["code"][0]
    assert token(env, client, code, "not-the-verifier-" + "x" * 40).status_code == 400
    # a failed attempt must not burn... but the right verifier still works exactly once
    assert token(env, client, code, verifier).status_code == 200
    again = token(env, client, code, verifier)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
    no_challenge = env.oauth.get("/authorize", params={"response_type": "code", "client_id": client, "redirect_uri": REDIRECT}, follow_redirects=False)
    assert no_challenge.status_code in (302, 400) and "code=" not in no_challenge.headers.get("location", "")


def test_a_code_is_for_one_client_and_one_redirect_uri(env):
    a = register(env).json()["client_id"]
    b = register(env, client_name="Other").json()["client_id"]
    verifier, challenge = pkce()
    _, done = consent(env, start(env, a, challenge).headers["location"])
    code = get_code(done)["code"][0]
    assert token(env, b, code, verifier).status_code == 400  # another client can't redeem it
    assert token(env, a, code, verifier, redirect_uri="https://client.example/other").status_code == 400
    assert token(env, a, code, verifier).status_code == 200


def test_an_expired_code_is_refused(env):
    client = register(env).json()["client_id"]
    verifier, challenge = pkce()
    _, done = consent(env, start(env, client, challenge).headers["location"])
    code = get_code(done)["code"][0]
    from catch.core.models import OAuthAuthCode

    with tenant.use_owner(ALICE), Session(env.engine) as s:
        row = s.exec(select(OAuthAuthCode)).first()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.add(row)
        s.commit()
    assert token(env, client, code, verifier).status_code == 400


def test_the_resource_indicator_must_be_this_server(env):
    client = register(env).json()["client_id"]
    _, challenge = pkce()
    wrong = start(env, client, challenge, resource="https://other.example/mcp")
    assert "error=invalid_target" in wrong.headers["location"]
    ok = start(env, client, challenge, resource=f"{ISSUER}/mcp")
    assert ok.headers["location"].startswith(f"{ISSUER}/oauth/consent")


def test_a_token_bound_to_another_resource_is_refused_on_mcp(env):
    _, tok = full_flow(env)
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        g = s.exec(select(OAuthGrant)).first()
        g.resource = "https://other.example/mcp"
        s.add(g)
        s.commit()
    assert oauth.access_principal(tok["access_token"]) is None


# ---- refresh, replay, revocation, expiry ------------------------------------------------------------------------------------------------

def refresh(env, client, rt, **extra):
    return env.oauth.post("/token", data={"grant_type": "refresh_token", "client_id": client, "refresh_token": rt, **extra})


def test_refresh_rotates_and_the_old_access_token_stops_working(env):
    client, tok = full_flow(env)
    new = refresh(env, client, tok["refresh_token"]).json()
    assert new["access_token"] != tok["access_token"] and new["refresh_token"] != tok["refresh_token"]
    assert oauth.access_principal(tok["access_token"]) is None and oauth.access_principal(new["access_token"]) is not None
    assert refresh(env, client, tok["refresh_token"], scope="catch:read").status_code == 400  # (replayed — see next test)


def test_replaying_a_rotated_refresh_token_revokes_the_whole_grant(env):
    client, tok = full_flow(env)
    newer = refresh(env, client, tok["refresh_token"]).json()
    replay = refresh(env, client, tok["refresh_token"])
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    assert oauth.access_principal(newer["access_token"]) is None  # the legitimate holder is cut off too: the grant is dead
    assert refresh(env, client, newer["refresh_token"]).status_code == 400


def test_a_refresh_cannot_widen_scope_and_another_client_cannot_use_it(env):
    client, tok = full_flow(env, scopes=["catch:read"])
    assert refresh(env, client, tok["refresh_token"], scope="catch:read catch:write").status_code == 400
    other = register(env, client_name="Other").json()["client_id"]
    assert refresh(env, other, tok["refresh_token"]).status_code == 400


def test_revoking_ends_the_grant(env):
    client, tok = full_flow(env)
    assert env.oauth.post("/revoke", data={"token": tok["access_token"], "client_id": client, "client_secret": ""}).status_code == 200
    assert oauth.access_principal(tok["access_token"]) is None
    assert refresh(env, client, tok["refresh_token"]).status_code == 400


def test_expiry_of_the_access_token_and_of_the_absolute_lifetime(env):
    _, tok = full_flow(env)
    with tenant.use_owner(ALICE), Session(env.engine) as s:
        g = s.exec(select(OAuthGrant)).first()
        g.access_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.add(g)
        s.commit()
    assert oauth.access_principal(tok["access_token"]) is None
    client, tok2 = full_flow(env, who=BOB)
    with tenant.use_owner(BOB), Session(env.engine) as s:
        g = s.exec(select(OAuthGrant)).first()
        g.absolute_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.add(g)
        s.commit()
    assert oauth.access_principal(tok2["access_token"]) is None and refresh(env, client, tok2["refresh_token"]).status_code == 400


def test_only_hashes_are_stored(env):
    _, tok = full_flow(env)
    with Session(env.engine) as s:
        g = s.execute(select(OAuthGrant).execution_options(tenant_unscoped=True)).scalars().first()
        assert tok["access_token"] not in repr(g.__dict__) and tok["refresh_token"] not in repr(g.__dict__)
        assert g.access_hash == hashlib.sha256(tok["access_token"].encode()).hexdigest()


# ---- the person's controls and isolation --------------------------------------------------------------------------------------------------

def test_a_person_lists_and_ends_only_their_own_grants(env):
    _, alice_tok = full_flow(env)
    _, bob_tok = full_flow(env, who=BOB)
    mine = env.web.get("/api/oauth/grants", headers=bearer(ALICE)).json()["grants"]
    assert len(mine) == 1 and mine[0]["client_name"] == "Test MCP client" and "access_hash" not in mine[0]
    gid = mine[0]["grant_id"]
    assert env.web.delete(f"/api/oauth/grants/{gid}", headers=bearer(BOB)).status_code == 404  # Bob can't end Alice's
    assert oauth.access_principal(alice_tok["access_token"]) is not None
    assert env.web.delete(f"/api/oauth/grants/{gid}", headers=bearer(ALICE)).status_code == 200
    assert oauth.access_principal(alice_tok["access_token"]) is None and oauth.access_principal(bob_tok["access_token"]) is not None


def test_ending_all_app_access_ends_oauth_grants_too(env):
    _, tok = full_flow(env)
    assert env.web.delete("/api/coach/tokens", headers=bearer(ALICE)).json()["grants_revoked"] == 1
    assert oauth.access_principal(tok["access_token"]) is None


def test_there_is_a_cap_on_connected_apps(env, monkeypatch):
    monkeypatch.setattr(oauth, "MAX_ACTIVE_GRANTS", 2)
    full_flow(env)
    full_flow(env)
    client = register(env).json()["client_id"]
    _, challenge = pkce()
    _, done = consent(env, start(env, client, challenge).headers["location"])
    assert done.status_code == 409


def test_consent_endpoints_need_a_signed_in_user_and_the_feature_flag(env):
    client = register(env).json()["client_id"]
    _, challenge = pkce()
    req = parse_qs(urlsplit(start(env, client, challenge).headers["location"]).query)["req"][0]
    assert env.web.get("/api/oauth/authorization-request", params={"req": req}).status_code == 401
    assert env.web.post("/api/oauth/authorize", json={"req": req, "approve": True}).status_code == 401
    object.__setattr__(config.settings, "mcp_oauth_enabled", False)
    assert env.web.get("/api/oauth/authorization-request", params={"req": req}, headers=bearer(ALICE)).status_code == 404


def test_a_forged_or_expired_authorization_request_is_refused(env):
    for bad in ["garbage", "a.b", "é.ü", "e30.AAAA"]:
        assert env.web.get("/api/oauth/authorization-request", params={"req": bad}, headers=bearer(ALICE)).status_code == 400
    good = oauth.sign_request({"c": "x", "r": REDIRECT, "x": True, "s": ["catch:read"], "st": None, "ch": "c", "res": oauth.resource_url()}, now=time.time() - 10_000)
    assert env.web.get("/api/oauth/authorization-request", params={"req": good}, headers=bearer(ALICE)).status_code == 400
    body, sig = oauth.sign_request({"c": "x"}).rsplit(".", 1)
    assert env.web.get("/api/oauth/authorization-request", params={"req": body + "." + sig[:-2] + "AA"}, headers=bearer(ALICE)).status_code == 400
    with pytest.raises(ValueError):
        oauth.verify_request("tampered." + sig)


def test_another_client_cannot_revoke_a_grant_it_does_not_hold(env):
    client, tok = full_flow(env)
    other = register(env, client_name="Other").json()["client_id"]
    env.oauth.post("/revoke", data={"token": tok["access_token"], "client_id": other, "client_secret": ""})
    assert oauth.access_principal(tok["access_token"]) is not None  # untouched: the SDK checks the token belongs to the caller


def test_the_mcp_mount_accepts_an_oauth_token_and_challenges_everyone_else(env):
    from catch.mcp_server.http_app import _BearerAuthMiddleware

    _, tok = full_flow(env)
    principal = _BearerAuthMiddleware._principal_for(tok["access_token"])
    assert principal is not None and principal.owner_id == ALICE and principal.scope == "write"
    assert _BearerAuthMiddleware._principal_for("not-a-token") is None
    object.__setattr__(config.settings, "mcp_oauth_enabled", False)
    assert _BearerAuthMiddleware._principal_for(tok["access_token"]) is None  # the flag off means OAuth tokens mean nothing


def test_an_oauth_read_token_cannot_run_a_write_tool_over_the_mcp_backend(env):
    import asyncio

    from catch.mcp_server.backend import InProcessBackend, current_principal

    _, tok = full_flow(env, scopes=["catch:read"])
    principal = oauth.access_principal(tok["access_token"])
    reset = current_principal.set(principal)
    try:
        with pytest.raises(ValueError, match="scope"):
            asyncio.run(InProcessBackend().call_tool("add_note", {"date": "2026-11-02", "text": "x", "confirm": True}))
    finally:
        current_principal.reset(reset)


def test_a_public_app_with_the_flags_on_serves_the_metadata_and_challenges_unauthenticated_mcp_calls():
    """The real `catch.main` app in a clean interpreter (the routes are mounted at import time): the RFC 8414 / 9728 documents exist, and a
    /mcp call with no token gets a 401 that points the client at them."""
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "from fastapi.testclient import TestClient\n"
        "import catch.main as m\n"
        "c = TestClient(m.app, base_url='https://catch.test')\n"
        "a = c.get('/.well-known/oauth-authorization-server').json()\n"
        "r = c.get('/.well-known/oauth-protected-resource/mcp').json()\n"
        "u = c.post('/mcp/', json={})\n"
        "print(a['issuer'], a['authorization_endpoint'], a['token_endpoint'], a['registration_endpoint'], a['code_challenge_methods_supported'], sorted(a['scopes_supported']))\n"
        "print(str(r['resource']), r['authorization_servers'])\n"
        "print(u.status_code, u.headers.get('www-authenticate'))\n"
    )
    root = Path(__file__).resolve().parents[2]
    env = {
        "PATH": "/usr/bin:/bin", "HOME": str(root), "PYTHONPATH": str(root), "CATCH_DEPLOYMENT": "public", "SUPABASE_URL": "https://x.supabase.co",
        "DATABASE_URL": "postgresql://u:p@127.0.0.1:1/db", "CATCH_BASE_URL": "https://catch.test", "CATCH_MCP_HTTP_ENABLED": "1", "CATCH_MCP_OAUTH_ENABLED": "1",
    }
    out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    meta, resource, challenge = out.stdout.strip().splitlines()[-3:]
    assert meta.startswith("https://catch.test/ https://catch.test/authorize https://catch.test/token https://catch.test/register ['S256']")
    assert "catch:read" in meta and "catch:write" in meta
    assert resource.startswith("https://catch.test/mcp") and "https://catch.test/" in resource
    assert challenge.startswith('401 Bearer resource_metadata="https://catch.test/.well-known/oauth-protected-resource/mcp"')
