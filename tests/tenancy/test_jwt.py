"""Supabase access-token validation (session 24): signature, algorithm allow-list, issuer, audience, expiry, claims,
key rotation, and the session-revocation check. All against a local ES256 key standing in for the project's."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid

import pytest

from catch.core import supabase_auth as sa
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

pytestmark = pytest.mark.usefixtures("public")


def _b64(obj) -> str:
    raw = obj if isinstance(obj, bytes) else json.dumps(obj, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _payload(**over):
    import time

    base = {"iss": f"{kit.SUPABASE_URL}/auth/v1", "aud": "authenticated", "sub": kit.ALICE, "role": "authenticated",
            "session_id": str(uuid.uuid4()), "exp": int(time.time()) + 600, "iat": int(time.time())}
    return {**base, **over}


def test_a_valid_token_yields_the_verified_subject():
    claims = sa.verify_access_token(kit.mint(kit.ALICE, email="a@example.com"))
    assert claims.sub == kit.ALICE and claims.email == "a@example.com" and claims.aal == "aal1"


@pytest.mark.parametrize(
    "token_kwargs",
    [
        {"expires_in": -60},  # expired (beyond leeway)
        {"audience": "anon"},
        {"audience": "someone-else"},
        {"issuer": "https://evil.supabase.co/auth/v1"},
        {"issuer": "supabase"},  # a legacy anon/service token's issuer
        {"role": "anon"},
        {"role": "service_role"},
        {"extra": {"is_anonymous": True}},
        {"drop": ("sub",)},
        {"drop": ("exp",)},
        {"drop": ("aud",)},
        {"drop": ("iss",)},
        {"drop": ("session_id",)},
        {"extra": {"sub": "not-a-uuid"}},
        {"extra": {"session_id": "nope"}},
    ],
)
def test_invalid_claims_are_rejected(token_kwargs):
    with pytest.raises(sa.AuthError) as err:
        sa.verify_access_token(kit.mint(**token_kwargs))
    assert err.value.status_code == 401


def test_a_token_signed_by_another_key_is_rejected():
    with pytest.raises(sa.AuthError):
        sa.verify_access_token(kit.mint(key=kit.foreign_key()))


def test_a_tampered_payload_is_rejected():
    head, payload, sig = kit.mint(kit.ALICE).split(".")
    evil = json.loads(base64.urlsafe_b64decode(payload + "=="))
    evil["sub"] = kit.BOB
    with pytest.raises(sa.AuthError):
        sa.verify_access_token(f"{head}.{_b64(evil)}.{sig}")


def test_alg_none_is_rejected():
    token = f"{_b64({'alg': 'none', 'typ': 'JWT', 'kid': kit.KID})}.{_b64(_payload(sub=kit.BOB))}."
    with pytest.raises(sa.AuthError):
        sa.verify_access_token(token)


def test_hs256_algorithm_confusion_is_rejected():
    """The classic attack: sign with HMAC using the (public) verification key as the secret."""
    secret = json.dumps(kit.jwks()["keys"][0]).encode()
    head = _b64({"alg": "HS256", "typ": "JWT", "kid": kit.KID})
    body = _b64(_payload(sub=kit.BOB))
    sig = _b64(hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest())
    with pytest.raises(sa.AuthError):
        sa.verify_access_token(f"{head}.{body}.{sig}")


def test_rs256_header_on_an_ec_key_is_rejected():
    with pytest.raises(sa.AuthError):
        sa.verify_access_token(f"{_b64({'alg': 'RS256', 'kid': kit.KID})}.{_b64(_payload())}.{_b64(b'x' * 64)}")


def test_a_token_without_a_kid_or_with_an_unknown_kid_is_rejected():
    with pytest.raises(sa.AuthError):
        sa.verify_access_token(kit.mint(kid="not-in-the-jwks"))
    head, payload, sig = kit.mint().split(".")
    no_kid = _b64({"alg": "ES256", "typ": "JWT"})
    with pytest.raises(sa.AuthError):
        sa.verify_access_token(f"{no_kid}.{payload}.{sig}")


def test_garbage_is_rejected():
    for junk in ("", "x", "a.b.c", "Bearer abc", "eyJ.eyJ.sig"):
        with pytest.raises(sa.AuthError):
            sa.verify_access_token(junk)


# --- the JWKS cache -------------------------------------------------------------------------------------------------


def test_an_unknown_kid_refetches_once_not_per_request():
    fetches = []
    clock = [1000.0]

    def fetch():
        fetches.append(1)
        return kit.jwks()

    cache = sa.JwksCache(fetch=fetch, clock=lambda: clock[0])
    cache.jwk(kit.KID)
    for _ in range(5):
        with pytest.raises(sa.AuthError):
            cache.jwk("rotated-in-later")
    assert len(fetches) == 1  # inside the min-refetch window: no hammering the auth server
    clock[0] += sa.JWKS_MIN_REFETCH_SECONDS + 1
    with pytest.raises(sa.AuthError):
        cache.jwk("rotated-in-later")
    assert len(fetches) == 2


def test_the_cache_expires_so_a_revoked_signing_key_stops_working():
    clock = [0.0]
    state = {"keys": kit.jwks()}
    cache = sa.JwksCache(fetch=lambda: state["keys"], clock=lambda: clock[0])
    cache.jwk(kit.KID)
    state["keys"] = {"keys": []}  # the key was revoked upstream
    cache.jwk(kit.KID)  # still cached
    clock[0] += sa.JWKS_TTL_SECONDS + 1
    with pytest.raises(sa.AuthError):
        cache.jwk(kit.KID)


def test_a_jwks_outage_is_a_503_not_a_bad_token():
    def boom():
        raise OSError("network down")

    sa.jwks_cache = sa.JwksCache(fetch=boom)
    with pytest.raises(sa.AuthError) as err:
        sa.verify_access_token(kit.mint())
    assert err.value.status_code == 503


# --- revocation: logout / account deletion --------------------------------------------------------------------------


def test_a_signed_out_session_is_refused_even_though_its_token_has_not_expired(monkeypatch):
    live = {"value": True}
    monkeypatch.setattr(sa, "session_is_live", lambda sid: live["value"])
    token = kit.mint(kit.ALICE)
    assert sa.authenticate_bearer(token).sub == kit.ALICE
    live["value"] = False
    with pytest.raises(sa.AuthError, match="Session has ended"):
        sa.authenticate_bearer(token)


def test_liveness_is_cached_for_the_ttl_and_a_dead_session_stays_dead(monkeypatch):
    object.__setattr__(sa.config.settings, "supabase_session_check_ttl", 30.0)
    clock = [0.0]
    live = sa.SessionLiveness(clock=lambda: clock[0])
    calls = []

    def query(sid):
        calls.append(sid)
        return len(calls) < 2

    assert live.check("s1", query) is True
    clock[0] += 10
    assert live.check("s1", query) is True and len(calls) == 1  # cached inside the ttl
    clock[0] += 30
    assert live.check("s1", query) is False and len(calls) == 2  # re-asked after the ttl: now gone
    clock[0] += 1
    assert live.check("s1", lambda s: True) is False  # remembered: session ids are never reused


# --- over HTTP ------------------------------------------------------------------------------------------------------


def test_http_requires_a_valid_bearer_and_ignores_the_cookie_login(pub_client):
    assert pub_client.get("/api/me").status_code == 401
    assert pub_client.get("/api/me", headers={"authorization": "Bearer junk"}).status_code == 401
    assert pub_client.get("/api/me", headers={"authorization": "Basic abc"}).status_code == 401
    assert pub_client.post("/api/login", json={"password": "anything"}).status_code == 404  # cookie login is personal-only
    ok = pub_client.get("/api/me", headers=bearer(kit.ALICE))
    assert ok.status_code == 200 and ok.json()["id"] == kit.ALICE and ok.json()["deployment"] == "public"


def test_http_expired_and_revoked_tokens_are_401(pub_client, monkeypatch):
    assert pub_client.get("/api/me", headers=bearer(kit.ALICE, expires_in=-120)).status_code == 401
    monkeypatch.setattr(sa, "session_is_live", lambda sid: False)
    assert pub_client.get("/api/me", headers=bearer(kit.ALICE)).status_code == 401


def test_http_the_first_request_creates_the_profile(pub_client, pub_engine):
    from sqlmodel import Session, select

    from catch.core.models import UserProfile

    pub_client.get("/api/me", headers=bearer(kit.BOB))
    with Session(pub_engine) as s:
        assert s.exec(select(UserProfile.id)).all() == [kit.BOB]
