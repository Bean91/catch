"""A stand-in for Withings' API that enforces what the real one was observed to enforce on 2026-11-22 (docs/withings-endpoints.md):
an HMAC signature over the sorted action/client_id/nonce (or timestamp) values, single-use nonces, a registered callback URL, single-use
authorization codes, rotating refresh tokens, Bearer access tokens, `more`/`offset` paging, and the same `status`/`error` strings. No
network: it replaces `withings_client.httpx.post`."""

from __future__ import annotations

import hashlib
import hmac
import itertools

import httpx

from catch.sync import withings_client

CLIENT_ID = "test-withings-client-id"
CLIENT_SECRET = "test-withings-client-secret"
REDIRECT_URI = "https://catch.test/auth/withings/callback"


def _resp(url: str, body: dict) -> httpx.Response:
    return httpx.Response(200, json=body, request=httpx.Request("POST", url))


def _error(url: str, status: int, error: str) -> httpx.Response:
    return _resp(url, {"status": status, "error": error})


def group(grpid: int, date: int, weight_kg: float, *, attrib: int = 0, fat_free_kg: float | None = None, fat_kg: float | None = None) -> dict:
    measures = [{"type": 1, "value": round(weight_kg * 1000), "unit": -3}]
    if fat_free_kg is not None:
        measures.append({"type": 5, "value": round(fat_free_kg * 1000), "unit": -3})
    if fat_kg is not None:
        measures.append({"type": 8, "value": round(fat_kg * 100), "unit": -2})
    return {"grpid": grpid, "attrib": attrib, "date": date, "category": 1, "measures": measures}


class FakeWithings:
    def __init__(self, *, secret: str = CLIENT_SECRET, page_size: int = 2, expires_in: int = 10800):
        self.secret = secret
        self.page_size = page_size
        self.expires_in = expires_in
        self.codes: dict[str, int] = {}
        self.access: dict[str, int] = {}
        self.refresh: dict[str, int] = {}
        self.groups: dict[int, list[dict]] = {}
        self.nonces: set[str] = set()
        self.used_nonces: set[str] = set()
        self.revoked: list[int] = []
        self.refreshes = 0
        self.measure_calls: list[dict] = []
        self.token_requests: list[dict] = []
        self._seq = itertools.count(1)

    def issue_code(self, userid: int) -> str:
        code = f"code-{userid}-{next(self._seq)}"
        self.codes[code] = userid
        return code

    def _sig(self, *values: str) -> str:
        return hmac.new(self.secret.encode(), ",".join(values).encode(), hashlib.sha256).hexdigest()

    def _issue_tokens(self, url: str, userid: int) -> httpx.Response:
        n = next(self._seq)
        access, refresh = f"withings-access-{userid}-{n:04d}-XYZ", f"withings-refresh-{userid}-{n:04d}-XYZ"
        self.access[access] = userid
        self.refresh[refresh] = userid
        return _resp(url, {"status": 0, "body": {"userid": userid, "access_token": access, "refresh_token": refresh, "expires_in": self.expires_in,
                                                 "scope": "user.metrics", "token_type": "Bearer", "csrf_token": "x"}})

    def post(self, url, data=None, headers=None, timeout=None):
        data = dict(data or {})
        if url == withings_client.SIGNATURE_URL:
            if data.get("client_id") != CLIENT_ID or data.get("signature") != self._sig("getnonce", CLIENT_ID, str(data.get("timestamp"))):
                return _error(url, 503, "Invalid Params: Invalid HMAC signature")
            nonce = f"nonce-{next(self._seq)}"
            self.nonces.add(nonce)
            return _resp(url, {"status": 0, "body": {"nonce": nonce}})
        if url == withings_client.OAUTH_URL:
            nonce = data.get("nonce")
            if "client_secret" in data or data.get("signature") != self._sig(data.get("action", ""), CLIENT_ID, str(nonce)):
                return _error(url, 503, "Invalid Params: Invalid HMAC signature")
            if nonce not in self.nonces or nonce in self.used_nonces:
                return _error(url, 503, "Invalid Params: invalid nonce")
            self.used_nonces.add(nonce)
            if data["action"] == "revoke":
                userid = int(data["userid"])
                self.revoked.append(userid)
                for table in (self.access, self.refresh):
                    for token in [t for t, u in table.items() if u == userid]:
                        del table[token]
                return _resp(url, {"status": 0, "body": {}})
            self.token_requests.append({k: v for k, v in data.items() if k not in ("signature", "nonce")})
            if data["grant_type"] == "authorization_code":
                if data.get("redirect_uri") != REDIRECT_URI:
                    return _error(url, 503, "Invalid Params: invalid redirect_uri")
                userid = self.codes.pop(data.get("code"), None)  # a code works once
                if userid is None:
                    return _error(url, 503, "Invalid Params: invalid code")
                return self._issue_tokens(url, userid)
            userid = self.refresh.pop(data.get("refresh_token"), None)  # rotation: the old refresh token is spent
            if userid is None:
                return _error(url, 503, "Invalid Params: invalid refresh_token")
            self.refreshes += 1
            return self._issue_tokens(url, userid)
        if url == withings_client.MEASURE_URL:
            token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
            userid = self.access.get(token)
            if userid is None:
                return _error(url, 401, "XRequestID: Not provided invalid_token: The access token provided is invalid")
            self.measure_calls.append(data)
            groups = sorted(self.groups.get(userid, []), key=lambda g: g["date"])
            if "startdate" in data:
                groups = [g for g in groups if int(data["startdate"]) <= g["date"] <= int(data["enddate"])]
            offset = int(data.get("offset") or 0)
            page = groups[offset : offset + self.page_size]
            more = offset + self.page_size < len(groups)
            return _resp(url, {"status": 0, "body": {"measuregrps": page, "more": int(more), "offset": offset + self.page_size if more else 0, "timezone": "UTC"}})
        raise AssertionError(f"unexpected Withings URL {url}")


def configure(monkeypatch, fake: FakeWithings) -> None:
    import dataclasses

    from catch.sync import providers

    configured = dataclasses.replace(withings_client.settings, withings_client_id=CLIENT_ID, withings_client_secret=CLIENT_SECRET,
                                     withings_redirect_uri=REDIRECT_URI)
    monkeypatch.setattr(withings_client, "settings", configured)
    monkeypatch.setattr(providers, "settings", configured)
    monkeypatch.setattr(withings_client.httpx, "post", fake.post)
