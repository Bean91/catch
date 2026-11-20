"""Session 30 (docs/mobile/push.md): delivery to the store apps — APNs for iOS, FCM (HTTP v1) for Android.

Both are hand-rolled over httpx for the same reason push.py is: the vendor SDKs pull in far more than the one request this app
makes. Credentials come only from server settings (never the database, never a client). Nothing here logs a device token or a
credential, and every host is fixed in `core/netguard.py`.

Return contract matches push.send_to_subscription: `(sent, should_prune)`. `should_prune` is True only when the push service
says the token itself is dead; every other failure (network, 5xx, a bad provider credential) leaves the row alone."""

from __future__ import annotations

import json
import logging
import time
from typing import Callable

import httpx

from catch.core import netguard
from catch.core.config import settings
from catch.core.models import NativePushToken

logger = logging.getLogger("catch.notify.native_push")

APNS_HOST = "https://api.push.apple.com"
APNS_SANDBOX_HOST = "https://api.sandbox.push.apple.com"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
APNS_JWT_TTL_S = 40 * 60  # Apple: refresh no more than every 20 min and before 60 min
TTL_S = 86_400  # same 24 h as Web Push: a morning brief should reach a phone that was off overnight, a stale alert should not resurface

# APNs needs HTTP/2; tests replace this with a MockTransport-backed client.
def _default_client() -> httpx.Client:
    return httpx.Client(http2=True, timeout=10.0)


_client_factory: Callable[[], httpx.Client] = _default_client

_apns_jwt: tuple[str, float] | None = None
_fcm_token: tuple[str, float] | None = None


def apns_configured() -> bool:
    return bool(settings.apns_key_p8 and settings.apns_key_id and settings.apns_team_id and settings.apns_topic)


def _service_account() -> dict | None:
    if not settings.fcm_service_account_json:
        return None
    try:
        sa = json.loads(settings.fcm_service_account_json)
    except ValueError:
        logger.warning("FCM_SERVICE_ACCOUNT_JSON is not valid JSON")
        return None
    return sa if all(sa.get(k) for k in ("client_email", "private_key", "project_id")) else None


def fcm_configured() -> bool:
    return _service_account() is not None


def configured_for(platform: str) -> bool:
    return apns_configured() if platform == "apns" else fcm_configured()


def reset_caches() -> None:
    global _apns_jwt, _fcm_token
    _apns_jwt = _fcm_token = None


def _apns_bearer() -> str:
    global _apns_jwt
    now = time.time()
    if _apns_jwt and _apns_jwt[1] > now:
        return _apns_jwt[0]
    import jwt

    key = settings.apns_key_p8.replace("\\n", "\n")
    token = jwt.encode({"iss": settings.apns_team_id, "iat": int(now)}, key, algorithm="ES256", headers={"kid": settings.apns_key_id})
    _apns_jwt = (token, now + APNS_JWT_TTL_S)
    return token


def _apns_request(client: httpx.Client, host: str, row: NativePushToken, payload: dict) -> httpx.Response:
    url = netguard.assert_native_push_host(f"{host}/3/device/{row.token}")
    # The app's own id is the APNs topic; a row registered by a differently-signed build (a dev/staging suffix) carries its own.
    body = {"aps": {"alert": {"title": payload["title"], "body": payload["body"]}, "sound": "default"}, "url": payload.get("url", "/"), "type": payload.get("type", "")}
    headers = {
        "authorization": f"bearer {_apns_bearer()}",
        "apns-topic": row.app_id or settings.apns_topic,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-expiration": str(int(time.time()) + TTL_S),
        "apns-collapse-id": (payload.get("type") or "catch")[:64],  # one morning brief on the lock screen, not three
    }
    return client.post(url, json=body, headers=headers)


def send_apns(row: NativePushToken, payload: dict, *, on_environment_fix: Callable[[str], None] | None = None) -> tuple[bool, bool]:
    if not apns_configured():
        return False, False
    other = "production" if row.environment == "sandbox" else "sandbox"
    try:
        with _client_factory() as client:
            resp = _apns_request(client, APNS_SANDBOX_HOST if row.environment == "sandbox" else APNS_HOST, row, payload)
            reason = _apns_reason(resp)
            if resp.status_code == 400 and reason == "BadDeviceToken":
                # A TestFlight/App Store build registered as "sandbox" (or the reverse): the token is valid on the other host.
                retry = _apns_request(client, APNS_SANDBOX_HOST if other == "sandbox" else APNS_HOST, row, payload)
                if retry.status_code == 200:
                    if on_environment_fix:
                        on_environment_fix(other)
                    return True, False
                return False, True
    except (httpx.HTTPError, httpx.InvalidURL, ImportError, ValueError) as exc:
        logger.warning("apns send failed (%s) for token id=%s", type(exc).__name__, row.id)
        return False, False
    if resp.status_code == 200:
        return True, False
    if resp.status_code == 410 or (resp.status_code == 400 and reason in ("BadDeviceToken", "DeviceTokenNotForTopic")):
        return False, True
    # 403 InvalidProviderToken / ExpiredProviderToken is OUR credential, not the device: never prune for it.
    if resp.status_code == 403:
        global _apns_jwt
        _apns_jwt = None
    logger.warning("apns send failed status=%s reason=%s for token id=%s", resp.status_code, reason, row.id)
    return False, False


def _apns_reason(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("reason", ""))
    except ValueError:
        return ""


def _fcm_access_token(client: httpx.Client, sa: dict) -> str | None:
    global _fcm_token
    now = time.time()
    if _fcm_token and _fcm_token[1] > now + 60:
        return _fcm_token[0]
    import jwt

    assertion = jwt.encode({"iss": sa["client_email"], "scope": FCM_SCOPE, "aud": GOOGLE_TOKEN_URL, "iat": int(now), "exp": int(now) + 3600}, sa["private_key"], algorithm="RS256")
    resp = client.post(netguard.assert_native_push_host(GOOGLE_TOKEN_URL), data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    if resp.status_code != 200:
        logger.warning("fcm oauth failed status=%s", resp.status_code)
        return None
    data = resp.json()
    _fcm_token = (data["access_token"], now + int(data.get("expires_in", 3600)))
    return _fcm_token[0]


def send_fcm(row: NativePushToken, payload: dict) -> tuple[bool, bool]:
    sa = _service_account()
    if sa is None:
        return False, False
    try:
        with _client_factory() as client:
            access = _fcm_access_token(client, sa)
            if access is None:
                return False, False
            message = {"message": {
                "token": row.token,
                "notification": {"title": payload["title"], "body": payload["body"]},
                "data": {"url": str(payload.get("url", "/")), "type": str(payload.get("type", ""))},
                "android": {"priority": "HIGH", "ttl": f"{TTL_S}s", "collapse_key": (payload.get("type") or "catch")[:64]},
            }}
            resp = client.post(netguard.assert_native_push_host(f"https://fcm.googleapis.com/v1/projects/{sa['project_id']}/messages:send"), json=message, headers={"authorization": f"Bearer {access}"})
    except (httpx.HTTPError, httpx.InvalidURL, ImportError, ValueError, KeyError) as exc:
        logger.warning("fcm send failed (%s) for token id=%s", type(exc).__name__, row.id)
        return False, False
    if resp.status_code == 200:
        return True, False
    status = ""
    try:
        status = str(resp.json().get("error", {}).get("status", ""))
    except ValueError:
        pass
    if resp.status_code == 404 or (resp.status_code == 400 and status == "INVALID_ARGUMENT") or status == "UNREGISTERED":
        return False, True
    if resp.status_code == 401:
        global _fcm_token
        _fcm_token = None
    logger.warning("fcm send failed status=%s for token id=%s", resp.status_code, row.id)
    return False, False


def send_to_token(row: NativePushToken, payload: dict, *, on_environment_fix: Callable[[str], None] | None = None) -> tuple[bool, bool]:
    if row.platform == "apns":
        return send_apns(row, payload, on_environment_fix=on_environment_fix)
    if row.platform == "fcm":
        return send_fcm(row, payload)
    return False, True
