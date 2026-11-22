# Provider connections and per-user sync (session 25)

Catch syncs four sources — Garmin, Withings, Concept2, Whoop. On the **personal** Pi there is one user and credentials may still come from `.env`. On the
**public** deployment every account connects its own sources and nothing is shared. This document is the contract.

## The model

`provider_connections` (one row per user and provider; `owner_id` + RLS like every user table):

| Column | Meaning |
|---|---|
| `auth_method` | `oauth`, `api_key` (Garmin), `personal_token` (Concept2) |
| `status` / `status_detail` | `connected`, `needs_reconnect`, `error`, `rate_limited`; detail is a fixed vocabulary, never provider text |
| `account_id`, `scopes_json` | non-secret identification and what was granted |
| `access_enc`, `refresh_enc`, `credential_enc`, `key_id`, `last4` | sealed values; `last4` is blank for a short secret |
| `expires_at`, `credential_expires_on` | an OAuth access token's expiry; a user-entered key expiry reminder (Garmin) |
| `connected_at`, `last_validated_at` | |

Last successful sync, last error, failure count, next allowed attempt and history-import cursor live on `sync_state`, so there is one copy.

**Sealing.** `catch/core/secret_store.py` (AES-256-GCM): key = HKDF(master, salt = owner id, info = `catch/provider-connection/v1`); AAD = `owner|provider:slot`
(`access`, `refresh`, `credential`). A blob moved to another user, provider, slot — or opened as an AI key — fails closed. Master rotation works through
`CATCH_SECRETS_MASTER_KEY_PREVIOUS`. The public deployment never touches the Fernet path.

**Resolution order** (`catch/sync/connections.py`): the user's connection row; then, **personal install only**, a legacy `oauth_tokens` row (adopted once and
deleted in the same transaction — Whoop and Withings refresh tokens rotate, so two copies would diverge) or the `.env` credential (Garmin key, Concept2 token;
kept live, so rotating `.env` needs no re-save). The public deployment has no fallback to anything server-wide.

## Providers

| | How the user connects | Revocation by Catch | Notes |
|---|---|---|---|
| Garmin | Pastes their own **Personal API key** (docs/garmin-byok.md) | none (Garmin has no API for it) | official, self-service; terms caveat; operator switch `CATCH_GARMIN_BYOK_ENABLED` |
| Withings | OAuth (operator's Withings app) | **revoked at Withings on disconnect and account deletion** (`action=revoke`, session 34) | 120 requests/minute across the whole app; refresh token rotates (old one survives ~8 h) |
| Concept2 | OAuth (operator's app) **or** a personal token pasted from Edit Profile → Applications | none documented | read-only scopes `user:read,results:read`; refresh token ~1 year, rotates; "not currently rate limited" |
| Whoop | OAuth (operator's app) | `DELETE /v2/user/access` on disconnect and on account deletion | 100 req/min, 10,000/day; **the operator's app is capped at 10 members until Whoop approves a higher tier** |

OAuth needs one operator-registered app per provider (client id and secret in server secrets, `WITHINGS_*`, `WHOOP_*`, `CONCEPT2_CLIENT_*`). That is the one
unavoidable shared credential: the *user's* authorization, tokens and data are still their own. Garmin needs none.

## OAuth on the public deployment: signed state

A provider redirects the **browser** back, and a redirect carries no `Authorization` header. So: `POST /api/connections/{p}/oauth/start` (bearer) sets a
short-lived `HttpOnly` cookie holding `{owner, provider, nonce, exp}` signed with an HMAC key derived from the secrets master key, and returns the provider's
URL; the URL's `state` is only the nonce (**Whoop requires exactly eight characters**, so nothing else fits). `GET /auth/{p}/callback` (no bearer) accepts a
code only if the cookie's signature, provider and expiry check out and its nonce equals `state`; it then sets the owner **inside the handler** (a sync
dependency would lose it), exchanges the code and redirects to `/settings/connections?provider=…&result=connected|denied|failed`. An account deleted in the
meantime ends in `result=failed`, never an error page. Codes, tokens and provider bodies are never logged or returned.

**Assumption:** the web app and the API share an origin (so the cookie reaches the callback). Frontend hosting is still undecided (PLAN.md session 24 next
step 2); if they end up on different origins this design has to be revisited.

## Sync engine

- **Per user, per provider.** The tick (`POST /internal/tick/sync`) visits users in random order within a time budget (240 s; the rest are deferred to the next
  tick), and for each user calls `run_sync(provider)` inside that user's context. A job's only inputs are the owner (the context) and the provider name;
  credentials are resolved from the user's connection when it runs — never in a payload, log or queue entry. A failing provider or user never stops the others.
- **Never connected → skipped silently** (no attempt, error or alert).
- **No overlap.** An in-process lock plus, on the public deployment, a cross-replica lease: the already-reviewed `sync_state` row `job:sync:<provider>` taken under
  a transaction-scoped advisory lock (`catch/sync/lease.py`), released in `finally`, expiring after 10 minutes if a process dies. Tick and manual syncs share it.
- **Failures.** Auth refused → status `needs_reconnect`, scheduled runs stop, the user gets one `sync_broken` notification, a manual sync (or a new credential)
  tries again. Rate limited → status `rate_limited`, next scheduled attempt at the provider's `Retry-After` (capped at 6 h). Anything else → exponential backoff
  5 min, 10, 20 … up to 6 h, counting toward the existing 3-failures alert. A manual sync ignores backoff but not the lease.
- **History import (backfill).** Connecting queues it (`sync_state.backfill_cursor` = today − `BACKFILL_DAYS`). Each sync then imports one 30-day window after
  the incremental pass; a failed window keeps the cursor and retries, a throttled one defers. It never runs inside the connect request or the OAuth callback.
  Where a provider documents no history (Garmin Personal API), the attempt is made and any refusal is shown as a status.
- **Idempotent.** Upserts are keyed `(owner, source, external_id)`; a re-run changes nothing. Webhooks are not used by any provider here, so there is no
  delivery to de-duplicate.
- **Disconnect** revokes where the provider offers it, deletes the connection and the sync cursor, and **never deletes imported data**. A separate "delete my
  imported data" action is **not built**; deleting the account removes everything.

## API (cookie / bearer only — device tokens and MCP cannot reach it)

`GET /api/connections` · `PUT /api/connections/{p}/credential` (Garmin key / Concept2 token; validated first) · `PUT /api/connections/{p}/expiry` ·
`POST /api/connections/{p}/oauth/start` · `POST /api/connections/{p}/test` · `POST /api/connections/{p}/sync` · `DELETE /api/connections/{p}` ·
`GET /auth/{p}/callback`. Existing `/api/sync/*`, `/api/status`, `/auth/whoop/*`, `/auth/withings/start` keep working for the Pi. A response never contains a
token, key, code or ciphertext — only a card (status, dates, the last four characters of a long secret).

## Coach and MCP

`get_connected_providers` and `get_sync_status` (read) and `sync_provider` (preview-then-`confirm=true`), athlete-only, through the same `connections` service
and `run_sync`. They take no credential arguments and return none; they cannot connect, replace or disconnect anything. 58 tools.

## Not done / limitations

- Nothing ran against a live provider account in this session; every flow is verified against synthetic fixtures. Withings status codes for rate limiting (601)
  and an invalid grant are from memory of Withings' docs, not a live response — the first real call may need a mapping fixed in `withings_client._check_status`.
- Concept2's OAuth token endpoint and the personal token's lifetime are as documented but unobserved. **Concept2's docs never say the authorize redirect returns `state`; the callback requires it, so Concept2 OAuth may fail on its first live call — the pasted personal token is the fallback** (docs/concept2-endpoints.md).
- A Garmin key or Concept2 token kept in `.env` on the Pi shows as a "from environment" connection and cannot be disconnected from the UI (it would be re-adopted at once); remove it from `.env`. Pasting a key in the UI replaces it for that account.
- No "delete imported data" action; no Garmin "Export your data" import.
- The Whoop 10-member cap and Concept2 production validation are operator tasks.
- Rate limits for the connection routes are in-process (per replica).
- `tests/pg` (RLS for `provider_connections`, migration 0004, `FOR UPDATE` on Postgres) needs a local Supabase stack and was not run.

## Launch-audit status (session 31, 2026-11-20)

What is now known from production, via the owner's account through MCP `get_sync_status`:

- **Garmin (Personal API key):** syncing. The owner's key expires 2027-10-31. **Catch has no Garmin developer-program approval.**
  Offering BYOK on the multi-user deployment is an open owner decision (docs/launch-audit.md B-6). The app now warns at startup when
  `CATCH_GARMIN_BYOK_ENABLED` is left implicit.
- **Withings:** failing since 2026-11-20 00:37 UTC, 8 consecutive failures: `getnonce failed: status=503 (Invalid Params: Invalid
  HMAC signature)`. The likely cause is a client secret stored with a trailing newline. Since `bf3848e`, every env value is
  whitespace-stripped (`catch/core/config.py`, `tests/test_config_env_strip.py`). Deploy, then confirm the next sync. Withings
  OAuth for a second account has never run live.
- **Concept2:** the owner's personal-token connection syncs. The OAuth flow has never run live, and the `state` caveat above still
  stands.
- **Whoop:** never connected live.

Open from the audit:

- **L-41.** Any 400/401 on a token refresh (and any non-zero Withings refresh status) is treated as a revoked grant (needs
  reconnect). A rotated app secret or a provider hiccup would flip every user at once. It should be limited to `invalid_grant`-class
  responses.
- **L-48.** A new OAuth token without a refresh token re-keys the row while the old refresh blob keeps the previous master key.
- **`tests/pg`** (incl. `provider_connections` RLS) now runs on HEAD: 99 passed, 1 skipped (session 31).

## Session 34: Withings, verified live

The production failure (20 syncs, `getnonce … Invalid HMAC signature`) was a wrong `WITHINGS_CLIENT_SECRET` in FastAPI Cloud. It was re-set
from the app's real pair on 2026-11-22, and the next sync imported 3 measurements. Error handling now follows the spec's families and the live
strings (docs/withings-endpoints.md):
- a refused **app** signature, client id or callback is `status_detail = "app_misconfigured"`, not "reconnect";
- only a refused **token** means reconnect (L-41 fixed for Withings);
- stored errors are fixed words (L-48 fixed for Withings).

The OAuth callback logs the exception class and answers `result=connected|denied|expired|server_setup|failed`; the Connections page and
setup show one sentence for each. Operators can check an app with `uv run catch withings check-app` or `GET /internal/config-check?probe=withings`
(booleans only). The flow, isolation and refresh race are tested end to end against `tests/withings_fake.py`
(`tests/test_withings_flow.py`, `tests/tenancy/test_withings_isolation.py`). A brand-new account signing in on Withings' page has not been run
live.
