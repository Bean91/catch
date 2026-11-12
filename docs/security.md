# Security notes — secrets

## What is secret, where it lives

| Secret | Pi (personal install) | Public deployment |
|---|---|---|
| Deployment secrets (`CATCH_SESSION_SECRET`, `CATCH_SECRETS_MASTER_KEY`, `WHOOP_CLIENT_SECRET`, …) | `.env` (gitignored) | FastAPI Cloud secret configuration or a secret manager — never the database, never the repo |
| Source OAuth tokens (Garmin, Withings, Whoop) | `oauth_tokens`, Fernet under `CATCH_FERNET_KEY` | **to redesign** per user (see below) |
| A user's AI provider key | `ai_credentials`, AES-256-GCM, per-owner key | same table, same scheme, master key from the secret manager |

## AI provider keys (`catch/core/secret_store.py`)

- **Cipher:** AES-256-GCM. **Per-owner key:** HKDF-SHA256(master secret, salt = owner id, info =
  `catch/ai-credential/v1`). **AAD:** `v1|owner_id|provider`. A ciphertext copied to another owner's or another
  provider's row fails authentication instead of decrypting (tested). Blob: `v1.<key id>.<base64(nonce‖ciphertext)>`,
  a fresh random nonce each time.
- **Master secret:** `CATCH_SECRETS_MASTER_KEY`. On the personal Pi, where it is unset, it falls back to the existing
  `CATCH_FERNET_KEY` so no new setup is needed (Pi only — document, don't rely on it elsewhere). **Rotation:**
  `CATCH_SECRETS_MASTER_KEY_PREVIOUS` (comma-separated) keeps old blobs readable; `needs_reseal()` tells you which
  rows still use an old master. Missing master key → a clear error, never plaintext, never a default.
- **What a database-only breach reveals:** ciphertext, last four characters of keys 12+ characters long, statuses.
  Not the keys: the master secret isn't in the database.
- **What it does not protect against:** an attacker holding both the database and the master secret; a compromised
  application process (it decrypts keys to call providers). Both are inherent to a server that calls the provider on
  the user's behalf.
- **Upgrade path for the public build:** envelope encryption with KMS-wrapped per-user data keys (Supabase Vault,
  AWS/GCP KMS), so the application holds a wrapped key and asks KMS to unwrap it. The `seal`/`open_sealed` interface
  is shaped for that swap; it is not built.
- **Per-user isolation today** is an `owner_id` seam (the Pi has one owner, `"owner"`): credentials, coach settings,
  conversations, AI usage and rate limits are all filtered by it, through the single dependency
  `catch/core/owner.py::current_owner_id`, and tests act as a second owner by overriding that dependency. Wellness,
  activity and nutrition tables are **not** owner-scoped yet — that is the multi-user build's job.
- **Migration from session 22:** the old per-provider Fernet rows in `coach_credentials` are *copied* on first read
  and left in place, so rolling the code back still works. Replace and Remove delete the legacy row too, so a removed or
  replaced key can't come back.

## Never in logs, responses, errors or tools

- `catch/core/redact.py` scrubs provider-key shapes, `Bearer …`, `key=`/`api_key=` query values, header-style
  credentials, `user:pass@` URL parts and every secret the process has decrypted (registered at decrypt time). It runs on
  provider errors, chat `error` events, tool-error blocks stored with a conversation, sync-error text, and **every log
  record** (a record factory installed in `main.py`, so tracebacks are scrubbed too).
- Provider errors are reduced to a fixed vocabulary before leaving the adapter; raw response text and request URLs are
  never carried. Gemini's key is a header, not a URL parameter, because httpx puts the URL in its exception text.
- FastAPI's default 422 echoes the submitted `input`; on `/api/ai/*` and `/api/coach/key` that is stripped.
- Key routes are cookie-only; a device token, a coach token or the MCP server cannot reach them, no tool takes or
  returns a key, and tests plant keys and sweep every read tool, the REST tool endpoint, the `/mcp` mount and the
  system-prompt memory block.
- The frontend never stores or receives a key: the field lives in component state until the request is sent, is
  cleared on success, failure and close, and is never put in browser storage.

## Ollama and server-side request forgery

Ollama's base URL is user-supplied and the server fetches it. That is intended on the personal install (your own laptop,
over Tailscale) and **a server-side-request-forgery hole on a public one** (cloud metadata endpoints, internal hosts).
`CATCH_OLLAMA_ENABLED` (default `1`) is the switch: set `0` on a public deployment and the provider disappears from
the API and the UI, can't be selected, and its URL can't be saved. Whatever the switch, the URL must be plain
`http(s)://host` with no credentials in it (`file:`, `gopher:` and `user:pass@` are refused). A self-hosted public build
that does enable it would still need an allowlist or egress rules — not built.

## Changing the master key

Setting `CATCH_SECRETS_MASTER_KEY` on an install whose AI keys were sealed under `CATCH_FERNET_KEY` makes those keys
unreadable unless the old value is moved to `CATCH_SECRETS_MASTER_KEY_PREVIOUS`. If that happens the app doesn't crash:
chat and the photo features say "Your stored key can't be read any more … Re-enter it in Settings → AI Providers".

## Public deployment (session 24)

The threat the multi-user build adds is one user reaching another's data. Three independent layers (docs/public-architecture.md §6): the request's owner comes only from a
verified Supabase JWT (or a device token resolved to its minting user), never from a body, query or tool argument; the ORM adds `owner_id = :owner` to every query, stamps/verifies it
on every write and resolves every cross-row id for that owner; and Postgres row level security, evaluated on the same connection, with a runtime role that has no privileges of its own,
cannot become any role but `authenticated`, and is checked at startup not to bypass RLS. Foreign-key checks bypass RLS, hence the composite tenant keys. The Data API never sees the tables
(non-exposed schema). JWTs: ES256/RS256 only, fixed issuer/audience, `session_id` checked against `auth.sessions` (an access token can't otherwise be revoked). The browser keeps its Supabase
session in localStorage — an SPA with a separate API has no httpOnly option — so a strict CSP (scripts by hash) is the defence, and sign-out wipes every local trace. `redact.py` scrubs JWTs, `sb_secret_`
keys and database URLs. The secret key exists for one call (deleting a user's sign-in account); AI keys are sealed per user (`secret_store.py`) under a master key that is a platform secret, never a row.

## Known gaps

- The USDA client still sends its key as a query parameter (`usda_client.py`); the log filter now scrubs it from
  records, but moving it to a header would be cleaner.
- Source OAuth tokens (including Whoop's rotating refresh token) still use the single Fernet key. A multi-user build
  must give each user their own token row, sealed like AI keys.
- Rate limiting is in-process (and a stream slot abandoned without its generator being closed expires after the turn's wall-clock cap + 30 s instead of locking the owner out).
- (Session 24) In-process rate limits (`coach/limits.py`) are per replica; with N replicas the ceiling is N× (the DB-backed daily USD/token caps still hold).
- (Session 24) Push subscriptions are per `(owner, endpoint)`: two accounts used on one browser can both receive pushes there until the first signs out (sign-out should unsubscribe — not yet wired).
- (Session 24) Whoop's rotating refresh token is guarded by an in-process lock; with several replicas it needs `SELECT … FOR UPDATE` before Whoop is offered publicly.

