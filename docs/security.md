# Security notes — secrets

## What is secret, where it lives

| Secret | Pi (personal install) | Public deployment |
|---|---|---|
| Deployment secrets (`CATCH_SESSION_SECRET`, `CATCH_SECRETS_MASTER_KEY`, `WHOOP_CLIENT_SECRET`, …) | `.env` (gitignored) | FastAPI Cloud secret configuration or a secret manager — never the database, never the repo |
| Source credentials (Garmin key, Withings/Whoop/Concept2 OAuth tokens, Concept2 token) | `provider_connections`, AES-256-GCM per owner (legacy `oauth_tokens` Fernet rows are adopted on first use) | `provider_connections`, same scheme with its own key purpose (`catch/provider-connection/v1`); see docs/provider-connections.md |
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
  `catch/core/owner.py::current_owner_id`, and tests act as a second owner by overriding that dependency. Since
  session 24 **every** user-owned table carries `owner_id` and is protected by the tenant filter plus forced row-level
  security (see "Public deployment" below and the session 28 review at the end of this file).
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
the API and the UI, can't be selected, and its URL can't be saved. **Since session 28 this is enforced:** a public
deployment *refuses to start* with it enabled (`catch/core/startup_checks.py`). Whatever the switch, the URL must be plain
`http(s)://host` with no credentials in it (`file:`, `gopher:` and `user:pass@` are refused). A self-hosted public build
that does enable it would still need an allowlist or egress rules — not built.

## Changing the master key

Rotation is a command since session 28: put the new key in `CATCH_SECRETS_MASTER_KEY`, move the old one to
`CATCH_SECRETS_MASTER_KEY_PREVIOUS`, run `catch secrets rotate` (re-seals every AI key and provider-connection blob; `--dry-run`
first; `catch secrets status` shows how many blobs are on each key), confirm nothing is on an old key, then delete the
`..._PREVIOUS` entry. A blob that can't be opened is reported by owner/provider only and left untouched. The OAuth state cookie and
the MCP authorization-request signature derive from the same master and keep verifying under the previous one meanwhile.

Setting `CATCH_SECRETS_MASTER_KEY` on an install whose AI keys were sealed under `CATCH_FERNET_KEY` makes those keys
unreadable unless the old value is moved to `CATCH_SECRETS_MASTER_KEY_PREVIOUS`. If that happens the app doesn't crash:
chat and the photo features say "Your stored key can't be read any more … Re-enter it in Settings → AI Providers".

## Public deployment (session 24)

The threat the multi-user build adds is one user reaching another's data. Three independent layers (docs/public-architecture.md §6): the request's owner comes only from a
verified Supabase JWT (or a device token resolved to its minting user), never from a body, query or tool argument; the ORM adds `owner_id = :owner` to every query, stamps/verifies it
on every write and resolves every cross-row id for that owner; and Postgres row level security, evaluated on the same connection, with a runtime role that has no privileges on any owned table (session 26 gave it direct grants on the shared leaderboard tables only, reached through one module),
cannot become any role but `authenticated`, and is checked at startup not to bypass RLS. Foreign-key checks bypass RLS, hence the composite tenant keys. The Data API never sees the tables
(non-exposed schema). JWTs: ES256/RS256 only, fixed issuer/audience, `session_id` checked against `auth.sessions` (an access token can't otherwise be revoked). The browser keeps its Supabase
session in localStorage — an SPA with a separate API has no httpOnly option — so a strict CSP (scripts by hash) is the defence, and sign-out wipes every local trace. `redact.py` scrubs JWTs, `sb_secret_`
keys and database URLs. The secret key exists for one call (deleting a user's sign-in account); AI keys are sealed per user (`secret_store.py`) under a master key that is a platform secret, never a row.

## Leaderboards (session 26)

The first place one user can see another's data, so it is deliberately narrow (docs/leaderboards.md). Private leaderboard data (`leaderboard_settings`, `result_publications`) is ordinary
owned, RLS-protected data. What other users may see lives in **shared tables with no owner column** that the `authenticated` role has *no grant on*; only the runtime role `catch_api`
(granted directly, since it inherits nothing) reaches them, and only through `catch/sync/leaderboard_store.py`, which opens a fresh session with the request's owner cleared
(`tenant.system_detached`) and takes the acting owner as an explicit argument. The public row is a projection holding only allowlisted fields, rendered by one serializer; Concept2 ids, exact
dates, dates of birth and every health or training metric stay in the owner's private snapshot or are never stored. Entry status and the moderation log are in tables the athlete's role cannot
write (the log: INSERT/SELECT, plus UPDATE on the two person-reference columns so account deletion can detach the person). A moderator's closure survives withdraw and opt-out (the entry is kept as a tombstone), so it can't be undone by republishing. Moderators are `CATCH_MODERATOR_IDS` (a server secret). Rate limits that matter (publishing, reports, appeals) are counted in the database. On account
deletion the public rows go, and the audit log is kept with the person detached.

## Clubs (session 27)

Full model in `docs/clubs.md`. In short: club rows are readable only by that club's members, enforced by RLS policies on `authenticated` (so a bug in a query can't leak another club) and by the service's own role checks; a member's
workouts and health data are never copied into a club (a member's own request computes an integer from their own data); members are addressed by a per-club keyed reference, not an account id; invite tokens are random, stored only as a
hash and carried in the URL fragment; reports are invisible to the club's staff; every staff or moderator decision needs a reason and lands in an append-only audit log; a club never loses its owner (a trigger hands it to an adult
member); junior clubs are private, unlisted and coach-approved (a coach or the owner admits every young member; posts from an admin wait for a coach). Because `authenticated` can write its own challenge entry, shared result and participation values (the service, not RLS, makes them honest), `catch` must never be added to Supabase's exposed schemas. Manual entries made on the Garmin or Whoop side aren't detectable and count within the caps; unverified Concept2 results don't count. The club tools are read-only and athlete-only; there is no club write tool. Age is self-declared and no safeguarding review has happened.

## Known gaps

- (Session 26) The shared leaderboard tables' grants, forced-RLS policies and append-only log are written and have `tests/pg` expectations, but were not run against a real Supabase stack here.

- (Session 27) The club RLS policies, helper functions and the account-deletion trigger were run on a local `supabase start` stack (not a hosted project). Age and guardian consent are self-declared; no safeguarding or legal review has happened (`docs/clubs.md` §14).
- The USDA client still sends its key as a query parameter (`usda_client.py`); the log filter now scrubs it from
  records, but moving it to a header would be cleaner.
- (Session 25) Source credentials are now per-user rows sealed like AI keys (`provider_connections`). A personal install's `.env` Garmin key / Concept2 token
  stays plaintext in `.env` as before and is never copied into the database; the public deployment never reads them.
- Rate limiting is in-process (and a stream slot abandoned without its generator being closed expires after the turn's wall-clock cap + 30 s instead of locking the owner out).
- (Session 24) In-process rate limits (`coach/limits.py`) are per replica; with N replicas the ceiling is N× (the DB-backed daily USD/token caps still hold).
- (Session 24) Push subscriptions are per `(owner, endpoint)`: two accounts used on one browser can both receive pushes there until the first signs out (sign-out should unsubscribe — not yet wired).
- (Session 25) Whoop/Withings/Concept2 rotating refresh tokens use a row lock (`FOR UPDATE`) plus the in-process lock; the Postgres path is untested here.
- (Session 25) The OAuth callback authenticates by a signed `HttpOnly` cookie (HMAC key derived from the secrets master key). It assumes the page and API share
  an origin. Rotating the master key invalidates in-flight flows only (the previous key still verifies).



---

# Session 28 — security and privacy review

The review's findings, severity and status are in **`docs/security-findings.md`**; the data held is in **`docs/data-inventory.md`**;
the written policies are *drafts that have not had legal review* in `docs/legal/`. This section records the controls the review added
or confirmed, and the limits that remain.

## Where RLS is bypassed, and what stands in for it

A public request never touches an owned table as anyone but `authenticated` with that user's claims. The deliberate exceptions, each
reviewed and each pinned by a structure test (`tests/tenancy/test_structure.py` bans raw SQL and `tenant_unscoped` outside this list):

| Path | Runs as | Why | Service-layer control |
|---|---|---|---|
| `leaderboard_store.store()` (`tenant.system_detached()`) and the modules built on it (`club_store`, `account_store`, `restrictions`) | bare `catch_api`, owner cleared | Global tables (public entries, clubs, moderation, tombstone, OAuth clients) that `authenticated` has no grant on | Every function takes the acting owner as an argument and checks it; no function touches an owned table; moderators reach only these |
| `catch_private.session_is_live`, `resolve_api_token`, `list_user_ids`, `account_age_days`, `resolve_oauth_code`, `resolve_oauth_token` | SECURITY DEFINER, `search_path=''`, EXECUTE for `catch_api` only | Needed before an owner is known (a token, a code) or for a table the runtime role can't read | Read-only lookups of a single value; the owner they return is used for everything after |
| `catch_club.*` predicates | SECURITY DEFINER, EXECUTE also for `authenticated` | RLS policies call them | They take a caller-chosen user id, so they would be a membership oracle **if** the schema were exposed; it is not (a test asserts `catch` is outside the Data API exposure) |
| Triggers on `auth.users` / `user_profiles` | definer | Profile sync; club succession on deletion | Idempotent, tested on a real stack |
| The `postgres`/admin login | owner | Migrations, `catch db upgrade`, the operator | Never in the running app; `DATABASE_ADMIN_URL` is not a runtime secret |

The runtime role is checked at startup not to bypass RLS, and `tests/pg/test_rls_all_tables.py` proves — with two real GoTrue
identities and the ORM filter out of the picture — that across every strictly owned table one user cannot read, update, delete or forge
another's row, and cannot re-assign their own, and that `anon`, `service_role`, `catch_api` and `PUBLIC` hold no privilege on them.

## Operator access (stated plainly)

The operator can read everything in the database with the admin login and holds the secrets master key, so can decrypt stored AI keys
and provider tokens. Controls that apply to the operator: the master key lives only in the platform's secret store, not the database or
repo; the secret key (service role) is read in exactly one module and never reaches the browser (a CI check greps the built bundle);
logs are scrubbed. What does **not** apply: the operator is not technically prevented from reading user data. The terms and privacy
policy drafts must say so (they do). Envelope encryption with a KMS would narrow this and is the documented upgrade path.

## Prompt injection and AI/MCP safety

Imported and third-party text — provider workout titles/notes, club posts, coach feedback, technique notes, handles — can contain
instructions. The defence is layered and **does not rely on the model behaving**:

1. *Labelling* (`coach/untrusted.py`, applied in the shared `call_tool` so MCP and REST get it too): hidden/reordering characters are
   stripped, our delimiter neutralised, lengths capped, and every tool result names its free-text fields. The coach's system prompt says
   such text is data. This is defence in depth only.
2. *Gating:* every write previews first and `confirm` must be the boolean `true`. Eight tools used to save immediately (plus `forget` of a fact/goal); all now go
   through one gate with validating previews. A call carrying no caller identity is refused.
3. *Server-side confirmation for the in-app coach:* `confirm=true` is honoured only for a call whose identical preview came from the
   **immediately preceding** turn and only when the athlete's reply reads as agreement — short, affirmative, no negation or change of subject
   (`coach/confirmation.py`; an English-wording heuristic, anything else just previews again). An injected "preview and confirm in one turn", or a
   confirm after an unrelated message, is downgraded to a preview. Tested end to end with a scripted model reading a poisoned workout title.
   It cannot prove the athlete *saw* the preview; a confirm card in the UI would.
4. *Scopes and consent:* device tokens and OAuth grants are `read` or `write`; `write` still needs the confirm; no tool reaches credentials,
   AI keys, account deletion, or club/leaderboard writes (none exist); no tool takes SQL, code or a URL.
5. *Audit:* `tool_call_log` records tool, door, write/confirmed/outcome and an argument hash — never arguments or results.

**Residual risk (finding F-02, "Mitigated", not "Fixed"):** over MCP and REST the confirmation is mediated by the *client* (Claude
Desktop's own tool-approval prompt) plus the token's scope; Catch cannot see whether a human clicked. A malicious tool result can
therefore still persuade a client that auto-approves to confirm a low-stakes write the token's scope allows. Read-only tokens are the
default for exactly this reason.

## What is sent to an AI provider

Nothing until the person has acknowledged the disclosure, and each of seven categories starts off (`coach/ai_sharing.py`,
`ai_sharing_settings`). Enforcement is in the service layer on the shared tool path, the chat loop, the system-prompt memory block and
the photo features — not in the prompt. A category that is off yields a fixed "sharing disabled" answer — for writes as well as reads, tools whose payload mixes categories lose the parts
that are off, check-in trend metrics are refused, whether a call is "model-bound" is decided by the credential (any device token is an outside client; a header
can't opt out), and stored tool results are scrubbed every time history is replayed. A person who declares an age
under 19 needs a guardian tick before any health category can be enabled. `docs/ai-data-sharing.md` lists exactly what each path sends.

## Device tokens and MCP OAuth

Device tokens (hashed, shown once) now carry a **scope** (athlete tokens default to read), a **90-day expiry**, a cap of 10 active, and are
all ended by "end all app access". MCP OAuth 2.1 (`catch/mcp_server/oauth.py`, off by default, public only) is built on the installed MCP SDK's
authorization-server interface: consent happens on Catch's own page, PKCE is mandatory, codes are single-use for 60 s and bound to a client and
redirect URI, tokens are opaque and stored as hashes, access 1 h, refresh rotating 30 d / 90 d absolute with replay detection that revokes the
grant, grants bound to the `/mcp` resource, scopes `catch:read`/`catch:write`. Verified against a synthetic client only — **no real Claude Desktop
or Claude.ai connector was run**; keep the flag off until one has been.

## Throttling

In-process, per replica (`coach/limits.py`); new buckets cover account deletion, token minting, the tool endpoint, push, lookups, weather refresh,
OAuth callback/registration, `/internal` (throttled *before* the secret is compared) and export (plus a daily ceiling). With N replicas the ceiling is
N×; the DB-backed counters (publishing, reports, appeals, daily AI caps) still hold. A shared store is the upgrade. Request bodies are size-limited on
the ASGI stream before any buffering (`core/uploads.py`).

## Supabase Auth configuration review

Compared the local stack (`supabase/config.toml` in the test project) with what production must use (docs/public-setup.md checklist):

| Setting | Local stack | Production requirement | Enforced by a test? |
|---|---|---|---|
| JWT expiry | 3600 s | ≤ 3600 s | no (dashboard) |
| Refresh-token rotation / reuse interval | on / 10 s | on | no |
| Sign-up | enabled, **confirmations off** | confirm email **on** (the SPA assumes no session before the link) | `npm run test:live` |
| Anonymous sign-ins | off | off | `supabase_auth` refuses `is_anonymous` (test) |
| Minimum password length | **6** | **≥ 12** recommended; leaked-password protection on (plan permitting) | no — operator action |
| Password requirements | none | letters + digits at least | no — operator action |
| `secure_password_change` | **false** | true (recent sign-in to change a password) | no — operator action |
| MFA (TOTP) | **disabled** | enabled, required for moderator accounts (`CATCH_MODERATOR_REQUIRE_AAL2`) | synthetic tokens only |
| Auth rate limits / CAPTCHA | defaults, none | tighten sign-up/sign-in/recovery; enable CAPTCHA | no — operator action |
| Redirect URLs | localhost | exactly the app URL, no wildcards | no — operator action |
| Signing key | ES256 (JWKS) | asymmetric only (HS256 refused in code) | yes |

## Known gaps after session 28 (see the findings register for IDs and severity)

- MCP and REST write confirmation is client-mediated (F-02, residual).
- MCP OAuth and the moderator `aal2` gate are verified against synthetic tokens and the SDK's own routes only; real GoTrue MFA and a real MCP
  client were not exercised (the local stack has MFA off).
- `activities.raw_json` still stores each provider's full record, including fields Catch never reads (F-13).
- Rate limits are per replica (F-08). There is no per-workout delete in the UI. Chat history has no automatic retention setting.
- Platform-side retention (Supabase backups/PITR/auth logs, FastAPI Cloud request logs — including OAuth callback `?code=`) is outside the code; verify in the dashboards.
- Moderation records (`moderation_events`, `moderation_actions`, `moderator_access_log`) have no retention limit — a question for counsel.
- Legal documents are drafts; nothing here is a claim of legal compliance.
