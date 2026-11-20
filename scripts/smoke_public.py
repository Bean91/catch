"""End-to-end smoke test of a DEPLOYED public Catch (docs/operations.md §9).

Creates two disposable users through GoTrue's admin API, exercises the real deployment over HTTPS, and deletes them again (account
deletion is itself one of the checks). Reads everything from the environment and never prints a secret:

  SMOKE_BASE_URL          https://<host>            the deployed app
  SMOKE_SUPABASE_URL      https://<ref>.supabase.co
  SMOKE_PUBLISHABLE_KEY   sb_publishable_…
  SMOKE_SECRET_KEY        sb_secret_…               creates/deletes the disposable users only (or SMOKE_SECRET_KEY_FILE=<path to a file holding it>)
  CATCH_TICK_SECRET       the app's tick secret     /internal checks (optional: those checks are skipped without it)

Run:  uv run python scripts/smoke_public.py          Exit code 0 = every non-skipped check passed.
Refuses to run against a loopback host unless SMOKE_ALLOW_LOCAL=1, and never touches any user it did not create.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx

BASE = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
SB = os.environ.get("SMOKE_SUPABASE_URL", "").rstrip("/")
PUB = os.environ.get("SMOKE_PUBLISHABLE_KEY", "")
SEC = os.environ.get("SMOKE_SECRET_KEY", "")
_key_file = os.environ.get("SMOKE_SECRET_KEY_FILE", "")
if not SEC and _key_file:  # a file the operator wrote themselves (chmod 600), so the key never appears in a command line or transcript
    SEC = open(os.path.expanduser(_key_file)).read().strip()
TICK = os.environ.get("CATCH_TICK_SECRET", "")

results: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(ok: bool | None, name: str, detail: str = "") -> bool:
    status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


def need(name: str) -> None:
    if not os.environ.get(name):
        raise SystemExit(f"Set {name} (see the module docstring)")


class User:
    def __init__(self, label: str):
        self.email = f"catch-smoke-{label}-{secrets.token_hex(4)}@example.com"
        self.password = secrets.token_urlsafe(18) + "aA1!"
        self.id = ""
        self.access = ""

    def headers(self, **extra) -> dict:
        return {"authorization": f"Bearer {self.access}", **extra}


def admin_create(user: User) -> None:
    r = httpx.post(f"{SB}/auth/v1/admin/users", headers={"apikey": SEC}, timeout=20,
                   json={"email": user.email, "password": user.password, "email_confirm": True})
    r.raise_for_status()
    user.id = r.json()["id"]


def admin_delete(user_id: str) -> int:
    return httpx.request("DELETE", f"{SB}/auth/v1/admin/users/{user_id}", headers={"apikey": SEC}, json={"should_soft_delete": False}, timeout=20).status_code


def sign_in(user: User) -> bool:
    r = httpx.post(f"{SB}/auth/v1/token?grant_type=password", headers={"apikey": PUB}, json={"email": user.email, "password": user.password}, timeout=20)
    if r.status_code != 200:
        return False
    user.access = r.json()["access_token"]
    return True


def api(user: User, method: str, path: str, **kw) -> httpx.Response:
    return httpx.request(method, BASE + path, headers=user.headers(), timeout=30, **kw)


def mcp(token: str, payload: dict) -> httpx.Response:
    return httpx.post(f"{BASE}/mcp/", timeout=30, json=payload,
                      headers={"authorization": f"Bearer {token}", "accept": "application/json, text/event-stream", "content-type": "application/json"})


def mcp_result(resp: httpx.Response) -> dict:
    text = resp.text
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        text = next((ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")), "{}")
    return json.loads(text or "{}")


def main() -> int:
    for name in ("SMOKE_BASE_URL", "SMOKE_SUPABASE_URL", "SMOKE_PUBLISHABLE_KEY"):
        need(name)
    if not SEC:
        raise SystemExit("Set SMOKE_SECRET_KEY or SMOKE_SECRET_KEY_FILE (see the module docstring)")
    if ("localhost" in BASE or "127.0.0.1" in BASE) and os.environ.get("SMOKE_ALLOW_LOCAL") != "1":
        raise SystemExit("SMOKE_BASE_URL is a loopback address; set SMOKE_ALLOW_LOCAL=1 to test a local instance")
    a, b = User("a"), User("b")
    created: list[str] = []
    try:
        # --- the deployment itself -------------------------------------------------------------------------------------------------
        h = httpx.get(f"{BASE}/api/health", timeout=30)
        record(h.status_code == 200 and h.json() == {"ok": True}, "GET /api/health", f"{h.status_code}")
        root = httpx.get(f"{BASE}/", timeout=30)
        record(root.status_code == 200 and "<div id=\"root\"" in root.text.replace("'", '"'), "GET / serves the built SPA", f"{root.status_code}, {len(root.text)} bytes")
        deep = httpx.get(f"{BASE}/clubs/1/calendar", timeout=30)
        record(deep.status_code == 200 and deep.text == root.text, "a nested client route returns the SPA (direct navigation)", f"{deep.status_code}")
        record(httpx.get(f"{BASE}/internal/nope", timeout=30).status_code in (401, 404), "an /internal typo is not the SPA")
        for header in ("content-security-policy", "strict-transport-security", "x-content-type-options"):
            record(header in root.headers, f"security header {header}")
        record(httpx.get(f"{BASE}/docs", timeout=30).status_code != 200 or "swagger" not in httpx.get(f"{BASE}/docs", timeout=30).text.lower(), "no public API docs")
        record(httpx.get(f"{BASE}/api/me", timeout=30).status_code == 401, "an API call with no token is 401")
        record(httpx.get(f"{BASE}/api/me", headers={"authorization": "Bearer not-a-jwt"}, timeout=30).status_code == 401, "a malformed token is 401")

        if TICK:
            hdr = {"authorization": f"Bearer {TICK}"}
            chk = httpx.get(f"{BASE}/internal/db-check", headers=hdr, timeout=60)
            body = chk.json() if chk.status_code == 200 else {}
            local = os.environ.get("SMOKE_ALLOW_LOCAL") == "1"  # a local Postgres has no SSL; a deployment must
            record(chk.status_code == 200 and body.get("superuser") is False and body.get("bypass_rls") is False and (body.get("ssl") is True or local)
                   and body.get("sees_nothing_as_stranger") is True and body.get("cannot_write_for_another_user") is True,
                   "/internal/db-check: unprivileged role, SSL, RLS probes", f"role={body.get('role')} pool_mode={body.get('pool_mode')} pg={body.get('version')}")
            record(httpx.post(f"{BASE}/internal/tick/notifications", headers={"authorization": "Bearer wrong"}, timeout=30).status_code == 401, "a tick with a wrong secret is 401")
            record(httpx.post(f"{BASE}/internal/tick/notifications", timeout=30).status_code == 401, "a tick with no secret is 401")
            started = time.monotonic()
            tick = httpx.post(f"{BASE}/internal/tick/notifications", headers=hdr, timeout=300)
            record(tick.status_code == 200 and "ran" in tick.json(), "authenticated tick runs", f"{tick.status_code} {tick.text[:120]} in {time.monotonic() - started:.1f}s")
        else:
            record(None, "/internal checks", "CATCH_TICK_SECRET not set")

        # --- sign up / in / out, JWT --------------------------------------------------------------------------------------------------
        admin_create(a)
        admin_create(b)
        created += [a.id, b.id]
        record(bool(a.id and b.id), "Supabase Auth: two users created", "")
        record(sign_in(a) and sign_in(b), "sign-in with email + password returns an access token")
        me = api(a, "GET", "/api/me")
        record(me.status_code == 200 and me.json().get("id") == a.id and me.json().get("deployment") == "public", "JWT accepted; /api/me is the signed-in user", f"{me.status_code}")

        # --- persistence + isolation ------------------------------------------------------------------------------------------------------
        today = date.today().isoformat()
        text = f"smoke {secrets.token_hex(3)}"
        w = api(a, "POST", "/api/notes", json={"date": today, "text": text})
        r = api(a, "GET", f"/api/notes?date={today}")
        record(w.status_code == 200 and r.status_code == 200 and (r.json() or {}).get("text") == text, "a write by user A persists and reads back", f"{w.status_code}/{r.status_code}")
        rb = api(b, "GET", f"/api/notes?date={today}")
        record(rb.status_code == 200 and rb.json() in (None, {}), "user B cannot see user A's note")
        tok = api(a, "POST", "/api/coach/tokens", json={"name": "smoke"})
        a_token_id = tok.json().get("id") if tok.status_code == 200 else None
        record(tok.status_code == 200 and tok.json().get("scope") == "read", "A mints a read-scope device token", f"{tok.status_code}")
        record(api(b, "GET", "/api/coach/tokens").json() == [], "user B's token list does not include A's")
        d = api(b, "DELETE", f"/api/coach/tokens/{a_token_id}") if a_token_id else None
        record(d is not None and d.status_code == 404, "user B deleting A's token id is 404 (not 403)", f"{d.status_code if d else '-'}")

        # --- MCP (Streamable HTTP, bearer, stateless) ------------------------------------------------------------------------------------------
        raw = tok.json().get("token", "") if tok.status_code == 200 else ""
        record(httpx.post(f"{BASE}/mcp/", json={}, timeout=30).status_code == 401, "MCP without a token is 401")
        init = mcp(raw, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}}})
        record(init.status_code == 200 and "result" in mcp_result(init), "MCP initialize over HTTPS", f"{init.status_code}")
        mcp(raw, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = mcp(raw, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in mcp_result(tools).get("result", {}).get("tools", [])]
        record(tools.status_code == 200 and len(names) >= 60 and "get_today" in names, "MCP tools/list (separate request: stateless)", f"{tools.status_code}, {len(names)} tools")
        call = mcp(raw, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_connected_providers", "arguments": {}}})
        record(call.status_code == 200 and "error" not in mcp_result(call) and not mcp_result(call).get("result", {}).get("isError"), "MCP read-only tool call as user A", f"{call.status_code}")
        write = mcp(raw, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "remember", "arguments": {"category": "other", "text": "smoke", "confirm": True}}})
        wr = mcp_result(write)
        refused = bool(wr.get("result", {}).get("isError")) or bool(wr.get("error"))
        record(write.status_code in (200, 403) and refused and "validation error" not in json.dumps(wr).lower(),
               "a read-scope token cannot perform a confirmed write", f"{write.status_code} {json.dumps(wr)[:120]}")

        wtok = api(a, "POST", "/api/coach/tokens", json={"name": "smoke-write", "scope": "write"})
        wraw = wtok.json().get("token", "") if wtok.status_code == 200 else ""
        prev = mcp(wraw, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "remember", "arguments": {"category": "other", "text": "smoke", "confirm": True}}})
        pr = mcp_result(prev)
        record(prev.status_code == 200 and not pr.get("result", {}).get("isError"),
               "control: a write-scope token sends the same call and is not refused as an error", f"{prev.status_code} {json.dumps(pr)[:120]}")

        # --- concurrency ------------------------------------------------------------------------------------------------------------------------------
        def hit(_: int) -> int:
            return api(a, "GET", f"/api/notes?date={today}").status_code

        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=40) as pool:
            codes = list(pool.map(hit, range(120)))
        bad = [c for c in codes if c >= 500]
        record(not bad and codes.count(200) == len(codes), "120 requests, 40 concurrent: all 200, no 5xx", f"{dict((c, codes.count(c)) for c in set(codes))} in {time.monotonic() - started:.1f}s")

        # --- sign-out revokes the session ------------------------------------------------------------------------------------------------------
        out = httpx.post(f"{SB}/auth/v1/logout", headers={"apikey": PUB, "authorization": f"Bearer {b.access}"}, timeout=20)
        revoked = False
        for _ in range(8):  # the live-session check caches for CATCH_SESSION_CHECK_TTL (15 s default)
            if api(b, "GET", "/api/me").status_code == 401:
                revoked = True
                break
            time.sleep(4)
        record(out.status_code in (200, 204) and revoked, "after sign-out the unexpired token is rejected", f"logout {out.status_code}")

        # --- account deletion -------------------------------------------------------------------------------------------------------------------------
        record(sign_in(b), "user B signs in again (fresh sign-in for step-up)")
        dele = api(b, "DELETE", "/api/account", json={"confirm": "DELETE"})
        record(dele.status_code == 200 and dele.json().get("deleted") is True, "DELETE /api/account removes the account", f"{dele.status_code} {dele.text[:80]}")
        gone = httpx.get(f"{SB}/auth/v1/admin/users/{b.id}", headers={"apikey": SEC}, timeout=20)
        record(gone.status_code == 404, "the Auth user no longer exists")
        record(api(b, "GET", "/api/me").status_code == 401, "B's old token is rejected after deletion")
        record(api(a, "GET", f"/api/notes?date={today}").json().get("text") == text, "user A's data is untouched by B's deletion")
        if gone.status_code == 404:  # only an account the deletion really removed skips the cleanup below (it leaked one in session 31)
            created.remove(b.id)
    finally:
        for uid in created:
            admin_delete(uid)  # an account the checks above did not already delete
    failed = [r for r in results if r[0] == "FAIL"]
    print(f"\n{sum(r[0] == 'PASS' for r in results)} passed, {len(failed)} failed, {sum(r[0] == 'SKIP' for r in results)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
