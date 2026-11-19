# Security findings register — session 28 review

Reviewed: the whole application (API routes, tenancy, RLS and migrations, provider integrations, AI/MCP layer, moderation, web app, CI) by
reading the code, plus tests run against the real routes, a throwaway local Supabase stack (real GoTrue, real RLS roles) and synthetic provider
fixtures. **Not** reviewed or run: a hosted Supabase project, FastAPI Cloud's runtime and logs, real provider accounts, a real MCP client, real
GoTrue MFA (the local stack has it off). "Fixed" means the code change and a test exist; it is a statement about the code, not a guarantee.

**Counts:** Critical **0** · High **4** (3 Fixed, 1 Mitigated with a residual the owner must accept) · Medium **9** (7 Fixed or Mitigated; 2 Open: F-14 pending a real-client run, F-17 operator action) · Low/Info **16** (6 Fixed, 3 Accepted, 5 Open, 2 Info).
No Critical finding was identified. That is a statement about what was reviewed above, not a claim that none exists.

Status vocabulary: **Fixed** (change + test) · **Mitigated** (reduced, residual stated) · **Accepted** (known, deliberate) · **Open** (not done; owner/next step stated).

## Deployment gate

Do **not** deploy publicly until: every Critical/High above is Fixed, or Mitigated with the residual explicitly accepted by the owner (F-02 is the
only one — read it); the operator checklist in `docs/public-setup.md` has been done (Supabase settings, MFA for moderators, backups/log retention
checked); and the legal drafts in `docs/legal/` have had legal review. *Nothing was deployed in this session.* MCP OAuth stays **off**
(`CATCH_MCP_OAUTH_ENABLED=0`) until it has been run against a real client.

## High

| ID | Finding | Evidence | Remediation | Status |
|---|---|---|---|---|
| F-01 | Push `endpoint` was stored unvalidated and the server POSTed to it: SSRF to internal hosts, a status oracle (`/api/push/test`), the notify tick stalled by a slow endpoint, no per-user cap | `routes_push.py`, `notify/push.py` | `core/netguard.py`: https only, no IP literals/userinfo/odd ports, host must be a known browser push service; checked at subscribe **and** send; cap 10/user; throttled; exception text no longer logged | **Fixed** (`tests/test_netguard.py`, `tests/test_api_push.py`) |
| F-02 | No prompt-injection handling: tool results, memory, club posts, feedback were unlabelled; 8 write tools saved immediately (incl. `remember`/`set_goal` → persistent memory poisoning into the system prompt every turn); `confirm` was a convention a model could skip | `coach/tools.py`, `chat.py`, `memory.py` | Untrusted-text sanitising + labelling in the shared tool path; one validating preview gate for every write; strict boolean confirm; fail-closed identity; in-app coach honours confirm only after an earlier-turn preview + a new athlete message; memory writes capped/sanitised; system prompt rules; audit log | **Mitigated.** Tested end to end (poisoned title → injected remember(confirm) saves nothing). **Residual:** over MCP/REST, confirmation is client-mediated (the MCP client's tool-approval prompt) plus token scope — Catch can't see a human click. Athlete tokens default to read-only; write tokens/grants are opt-in. **Owner must accept this residual.** |
| F-03 | Ollama URL is user-supplied and fetched server-side (SSRF); `CATCH_OLLAMA_ENABLED` defaulted on and nothing forced it off on a public deployment | `core/config.py`, `coach/settings.py` | `core/startup_checks.py`: a public deployment refuses to start with it enabled (also: master key missing/short or Fernet-only, short tick secret) | **Fixed** (`tests/test_startup_checks.py`) |
| F-04 | AI sharing had no disclosure, consent or control; no user data export on the public build (CLI/Pi only); no privacy center; no legal pages | `coach/*`, `routes_*`, `web/src` | Consent gate + seven per-category switches (all off) enforced in the service layer; export (gzip NDJSON, every owned table + shared rows, secrets withheld); category deletion; Privacy page; seven legal drafts | **Fixed** for the controls (`tests/coach/test_ai_sharing.py`, `tests/tenancy/test_privacy.py`, Playwright). The *legal documents* are drafts — see F-18 |

## Medium

| ID | Finding | Remediation | Status |
|---|---|---|---|
| F-05 | Deleted-account resurrection: a still-valid token re-created the profile (15 s liveness cache); a failure after GoTrue deletion left global rows no retry could clean; no step-up or throttle on `DELETE /api/account`; UI said "everything" | App-side cleanup **before** the auth delete; `deleted_accounts` tombstone; session marked dead; step-up = JWT `amr[].timestamp` within 10 min (`iat` is renewed by every refresh — verified on a real token); throttle; retryable; honest copy | **Fixed** (SQLite + real-GoTrue tests). Residual: another replica trusts a cached session for up to `CATCH_SESSION_CHECK_TTL` (15 s) but cannot recreate the profile or read rows (cascaded) |
| F-06 | Device tokens never expired, had no scope, weren't throttled or capped; no tool-call audit | Scope (athlete default read), 90-day expiry, cap 10, revoke-all (also ends OAuth grants), `tool_call_log`, resolver updated in the DB | **Fixed** (`tests/test_token_scopes.py`). Residual: Supabase "sign out everywhere" doesn't reach device tokens server-side — the UI ends them first (F-19) |
| F-07 | Unbounded request bodies (`photo.read()`, club logo read before its size check); piece photos had no magic-byte check | `core/uploads.py`: size limit enforced on the ASGI stream before buffering (photos 6 MB, logo 300 KB, tool calls 64 KB, rest 2 MB); magic-byte sniffing on all three upload routes | **Fixed** (`tests/test_uploads.py`). Residual: the hosting platform's own request limit is unverified |
| F-08 | In-process limiter only; account delete, token mint, tool endpoint, push, nutrition lookups, weather refresh, OAuth callback and `/internal` had none | New buckets applied; `/internal` throttled before the secret compare; daily export ceiling; `Retry-After` | **Mitigated.** Still per replica (N× with N replicas); shared store not built (F-12) |
| F-09 | Hardcoded HMAC fallbacks (`"catch-clubs"`, `"catch-leaderboards"`); master key not required or validated on public; `needs_reseal` never called, so a previous master could never be retired | No built-in fallback; startup refuses weak/absent keys; `catch secrets status|rotate` | **Fixed** (`tests/test_secret_rotation.py`). Residual: the master key is a platform secret, not KMS-wrapped (documented upgrade path) |
| F-10 | No secret scanning, dependency audit or `SECURITY.md`; CI had no `permissions:`; actions not SHA-pinned | `security.yml` (gitleaks full history, pip-audit, npm audit, weekly), dependabot, pinned actions, read-only token, bundle check for service keys, `.gitleaks.toml` (verified a real-looking key in tests still fails) | **Fixed.** pip-audit and npm audit on today's locks: no known vulnerabilities |
| F-11 | Three throwaway accounts could auto-hide anyone's result/post; no account-level restriction; appeals covered results only; moderator reads unlogged; no MFA step-up | Reports count only from accounts ≥ 7 days old; restrictions (publish/clubs/posting) with mandatory reasons, user-visible, one appeal reviewed by a different moderator; append-only action and moderator-access logs; moderator routes need `aal2` | **Mitigated.** The `aal2` gate is tested with synthetic tokens only (local MFA is off) — verify with a real MFA session before launch (F-17) |
| F-14 | MCP had only bearer device tokens (no OAuth, no scopes, no revocation UI) | MCP OAuth 2.1 on the SDK's provider interface (PKCE, hashed rotating tokens, replay detection, resource binding, scopes, consent page, grant list/revoke), flag off | **Open until verified:** implemented and tested against a synthetic client and the SDK's real routes, never against Claude Desktop/Claude.ai. Keep off until then |
| F-17 | Supabase Auth settings in the repo's local stack are weaker than production needs (password min 6, no password rules, `secure_password_change` off, MFA off, no CAPTCHA); production settings can't be inspected from here | Checklist table in `docs/security.md`; `docs/public-setup.md` | **Open (operator action):** set and verify in the dashboard |

## Low / Info

| ID | Finding | Status |
|---|---|---|
| F-12a | 422 responses echoed submitted input on the credential and push routes | **Fixed** — every 422 drops `input`/`ctx` (`tests/tenancy/test_hardening.py`) |
| F-12b | `/docs`, `/redoc`, `/openapi.json` public (listing `/internal/*`) | **Fixed** on a public deployment |
| F-12c | No `Cache-Control: no-store` on API responses; service worker cached sensitive paths | **Fixed** — no-store under `/api,/auth,/oauth,/internal,/mcp`; SW never caches privacy/account/tokens/AI/connections; the offline gym fallback is intact (`test:gym`, `test:update` pass) |
| F-12d | OAuth state cookie: non-ASCII → 500; replayable | **Fixed** — clean refusal; single use per replica |
| F-12e | Operator's personal email in the Open Food Facts User-Agent; `.fastapicloudignore` missing dumps/tooling | **Fixed** |
| F-12f | `catch_club.*` predicates executable by `authenticated` (membership oracle *if* the schema were exposed) | **Accepted** — needed by the RLS policies; the schema is not exposed (tested); documented |
| F-13 | `activities.raw_json` stores each provider's full record, including other people's names/photos/likes (Garmin), coordinates and fields Catch never reads | **Open** — recommended ingest allowlist + migration (`docs/data-inventory.md` §3) |
| F-15 | No per-workout delete in the UI (only account deletion removes workouts) | **Open** (UX gap; documented in the deletion policy) |
| F-16 | No retention setting for chat history; moderation records (`moderation_events`, `moderation_actions`, `moderator_access_log`) have no age limit | **Open** — question for counsel; other logs now pruned |
| F-18 | Legal documents are drafts and unreviewed | **Open (blocker for launch):** counsel review; see the "open questions" in each file |
| F-19 | Supabase "sign out everywhere" can't reach device tokens/grants server-side; the UI ends them first | **Accepted** (documented) |
| F-20 | Supabase session in `localStorage` (XSS-exposed by design for an SPA with a separate API); service-worker cache holds the last data on the device until sign-out | **Accepted** — strict CSP by hash, wipe on sign-out/user switch (documented in `docs/security.md`) |
| F-21 | Platform-side retention (Supabase backups/PITR/auth logs; FastAPI Cloud request logs incl. OAuth callback `?code=`) unknown | **Open (operator action):** verify and document |
| F-22 | IDOR sweep: four routes answer 200 for a foreign id (`DELETE /api/gym/templates/{id}`, gym exercise `last`, gym stations list, Garmin-draft import) | **Info** — byte-identical to the answer for a nonexistent id (no existence oracle) and no row changes (`tests/tenancy/test_idor_sweep.py`) |
| F-23 | No analytics/third-party script; the only browser-side third party is OSM tiles (IP + area) | **Info** — disclosed |
| F-24 | Local dev artefacts at the repo root (`catch-before-0005.dump`, `data/fit/*.fit`) are gitignored but not excluded from a cloud upload by default | **Fixed** in `.fastapicloudignore` |

## Not verified (explicitly)

* Any hosted Supabase project, FastAPI Cloud, or a real Garmin/Withings/Whoop/Concept2/AI-provider call (all synthetic fixtures).
* Real GoTrue MFA (`aal2`), the MCP OAuth flow with a real client, the Postgres refresh-token row lock under load.
* The `/mcp` mount with multiple replicas, platform request-size limits, platform log contents.
* That the dashboard settings in the checklist are actually applied.

## How this was tested

`CATCH_DEPLOYMENT=personal uv run pytest --ignore=tests/pg` (the suite), `tests/pg` on a throwaway local Supabase stack (migration, forced RLS on
every owned table with two real identities, the definer functions, real account deletion), `web` Vitest + Playwright (touch, desktop, public,
service-worker update, offline gym), gitleaks over full history, pip-audit, npm audit. See PLAN.md "Session 28 → Verification" for the counts.
