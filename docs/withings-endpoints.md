# Withings public API — what Catch uses, and what was confirmed

Session 34 rewrote this file against Withings' own OpenAPI spec (`https://developer.withings.com/openapi.yaml`, downloaded 2026-11-22) and the
"sign your requests" guide, plus harmless live probes made with this deployment's app credentials on 2026-11-22. Where a live response and a
document disagree, the response wins and is noted.

## Session 34: why connecting failed, and what changed

- **Production root cause:** the `WITHINGS_CLIENT_SECRET` saved in FastAPI Cloud did not match the Withings app. Every Withings call
  starts with a signed `getnonce`, and Withings answered it with `status=503 "Invalid Params: Invalid HMAC signature"`. Sync failed 20
  times in a row, and every new connection failed too, because the code exchange also starts with `getnonce`. The whitespace/quote cleanup
  (`bf3848e`, `90b9435`) was already live, so the stored value itself was wrong. The fix was operational: re-set `WITHINGS_CLIENT_ID` and
  `WITHINGS_CLIENT_SECRET` from the app's real pair (`env delete`, then `env set --secret --value-stdin`). The next sync imported 3
  measurements. The stored refresh token was never spent (getnonce fails first), so the existing connection recovered with no reconnect.
- **Why it was hard to see:** the OAuth callback swallowed every exception without logging. A user saw only "couldn't be connected".
  A refused *app* signature was stored as a generic sync failure carrying Withings' raw error text (launch audit L-48).
- **Personal/local:** the Withings app has one registered callback, `https://catch.openoted.com/auth/withings/callback`. A token
  request with `http://localhost:8787/…` or the Pi's `https://…ts.net/…` callback is refused with "invalid redirect_uri". To connect from
  those hosts, add their callback to the app in the Withings dashboard; multiple callbacks are comma-separated.
- **Code changes** (`catch/sync/withings_client.py`, `api/routes_connections.py`, `sync/connections.py`, `sync/scheduler.py`):
  - Errors are classified from the spec's families and the live strings (table below).
  - A bad app signature, client id or callback becomes `WithingsAppMisconfigured`, with connection detail `app_misconfigured`:
    "nothing to fix on your side". It is **not** "reconnect".
  - Only a refused token means reconnect; this fixes L-41 for Withings.
  - Stored errors are fixed words (L-48).
  - The callback logs the exception class and returns `result=connected|denied|expired|server_setup|failed`.
  - Queueing the history import can no longer turn a stored connection into "failed".
  - Disconnect and account deletion now **revoke** the grant at Withings.
  - The first sync reads a bounded window instead of the whole history.
  - The incremental cursor is the sync's *start* time.
  - Ambiguous weigh-ins are skipped.
  - `connected_at` is recorded.
  - Operators get `uv run catch withings check-app [--redirect-uri …]` and `GET /internal/config-check?probe=withings`. Both answer
    booleans only: does this server's app sign correctly, and is its callback registered.

## Signing (confirmed: spec + guide + live)

1. **Nonce:** `POST https://wbsapi.withings.net/v2/signature`.
   - Body: `action=getnonce`, `client_id`, `timestamp`.
   - `signature = HMAC_SHA256(client_secret, "getnonce,<client_id>,<timestamp>")`.
   - Answers `body.nonce`, valid 30 minutes and usable once.
2. **Signed calls** (`requesttoken`, `revoke`): `signature = HMAC_SHA256(client_secret, "<action>,<client_id>,<nonce>")`. Only those three
   values are signed (sorted by key name); `userid`, `code` and the rest are plain body fields.
3. The spec also allows `client_secret` in the body instead of a signature for `requesttoken`. Catch signs, so the secret is only ever
   an HMAC key.

## OAuth

- **Authorize:** `https://account.withings.com/oauth2_user/authorize2?response_type=code&client_id&scope=user.metrics&redirect_uri&state`.
  - Catch requests only `user.metrics`, which is enough for every measurement it reads.
  - `state` is a random nonce tied to a signed, HttpOnly, SameSite=Lax, 10-minute, single-use cookie naming the Catch account that started
    the flow (`core/oauth_state.py`). That covers CSRF, replay and attaching a code to someone else.
  - The code is valid **30 seconds**: the callback exchanges it immediately.
- **Token:** `POST https://wbsapi.withings.net/v2/oauth2`.
  - Body: `action=requesttoken`, `grant_type=authorization_code` (`code`, `redirect_uri`) or `refresh_token` (`refresh_token`), plus
    `client_id`, `nonce` and `signature`.
  - Answers `userid`, `access_token` (3 h), `refresh_token`, `expires_in`, `scope`, `token_type`.
  - **Refresh tokens rotate**: the new pair is sealed and committed before anything else. A process lock plus a row `SELECT … FOR
    UPDATE` stops two refreshes from spending one token (`tests/test_withings_flow.py` races two threads).
- **Revoke:** `POST …/v2/oauth2`, `action=revoke`, `client_id`, `nonce`, `signature`, `userid`. It ends the access and refresh tokens and
  unsubscribes notifications. Live-checked on 2026-11-22: a correctly signed revoke answers status 0, even for a userid that never granted
  the app.
- **Tokens at rest:** sealed per owner with AAD `owner|withings:access|refresh` (`core/secret_store.py`). They are never returned to a
  browser, a coach tool or an MCP client, and never logged. Error text from Withings names a parameter, never a credential.

## Errors (HTTP 200 with a JSON `status`)

| Seen | Status / error | Catch treats it as |
|---|---|---|
| bad signature (live) | `503 "Invalid Params: Invalid HMAC signature"` | app misconfigured: operator fixes it, not a reconnect |
| unregistered callback (live) | `503 "Invalid Params: invalid redirect_uri"` | app misconfigured (`result=server_setup`) |
| bad/expired/used code (live) | `503 "Invalid Params: invalid code"` | `result=expired`: start again |
| bad refresh token (live) | `503 "Invalid Params: invalid refresh_token"` | reconnect needed |
| bad access token (live) | `401 "…invalid_token…"` | reconnect needed |
| spec: 100–102, 200, 401 | "Authentication failed" | reconnect needed |
| spec: 601 / HTTP 429 | "Too many requests" | rate limited, backoff |
| spec: 522 / HTTP 5xx / network | timeout / outage | retried with backoff |
| anything else | — | plain error, retried; stored as fixed words |

Rate limit: 120 requests per minute for the whole application (not per user), so the backoff is per user and the tick spreads users.

## Measures — `getmeas`

`POST https://wbsapi.withings.net/measure` (**no `/v2/`**; using `/v2/` caused a live 503 in session 13). Body: `action=getmeas`,
`meastypes`, `category=1` (real measures), and either `lastupdate` (incremental) or `startdate`/`enddate`, plus `offset` while
`more` is set.

- **Values:** `value × 10^unit`, computed by division for negative units so `72400, -3` is exactly 72.4.
- **Types read** (from the spec's table; on 2026-11-22 a live account's muscle + bone + fat mass summed to its weight):

  | Code | Meaning | Stored as |
  |---|---|---|
  | 1 | weight (kg) | `weight_kg` |
  | 6 | fat ratio (%) | `fat_pct` |
  | 8 | fat mass (kg) | `fat_kg` |
  | 76 | muscle mass (kg) | `muscle_kg` |
  | 77 | hydration (kg) | `hydration_kg` |
  | 88 | bone mass (kg) | `bone_kg` |
  | 5 | fat-free mass (kg) | not stored; only fills fat mass when code 8 is missing (fat mass = weight − fat-free) |

- **Not read, by choice:** blood pressure (9/10), pulse (11), SpO₂ (54) and temperatures (12/71/73) are under the same `user.metrics`
  scope, but nothing in Catch uses them. Fetching them would collect health data for no purpose.
- **`attrib`:** groups with `attrib` 1 (captured by a shared scale and possibly another person's) or 4 (typed in at Withings account
  creation) are skipped. 0/8 (the user's device), 2 (entered by the user) and the rest are kept.
- **Idempotent:** upsert on `(source="withings", grpid)`, so a re-sync or overlapping windows never duplicate a row. A group Withings
  updates (re-attributed, edited) is overwritten in place. A measure deleted at Withings is not removed from Catch: getmeas has no deletion
  signal.
- **Windows:**
  - A newly connected account's first sync reads the last `days` (3 on a manual sync).
  - History is imported by the backfill, 30 days per run, newest-first cursor.
  - Later runs use `lastupdate` = the previous run's start minus 5 s.
- **Isolation:** every row is owner-scoped. Two Catch accounts connecting two Withings accounts never see each other's tokens, user id
  or measurements (`tests/tenancy/test_withings_isolation.py`, interleaved callbacks and syncs).

## Operator checks

```
uv run catch withings check-app                       # this process's app pair + WITHINGS_REDIRECT_URI
uv run catch withings check-app --redirect-uri https://…/auth/withings/callback
curl -H "Authorization: Bearer $TICK" "$BASE/internal/config-check?probe=withings"   # what the deployed process sees
```

Both make two harmless calls: a signed getnonce, then a token request with a made-up code. "invalid code" means the callback is
registered; "invalid redirect_uri" means it isn't. Nothing about any user is read.

## Verified live (2026-11-22) vs not

- **Verified with real Withings:**
  - signing (a made-up client id: `503 "invalid client id/secret"`, which is app-side as well);
  - the five error strings above;
  - revoke's status;
  - `check-app` both ways;
  - the production reset;
  - a real incremental sync (3 measurements);
  - the meastype codes against real readings.
- **Also live:** a refresh. The production access token last refreshed on 2026-11-20 and lives 3 hours, so the successful syncs on
  2026-11-22 had to exchange the refresh token (rotation included) first. That the rotated token was persisted is proven by the *next*
  refresh, about 3 hours later; `get_sync_status` shows it.
- **Not run live:** the authorize page, the callback for a brand-new connection, and revoke of a real grant. They need a person to
  disconnect and reconnect in a browser. The full flow runs against `tests/withings_fake.py`, which enforces the same signature, nonce,
  code, callback and rotation rules.
