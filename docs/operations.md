# Operating the public deployment (FastAPI Cloud + Supabase)

Runbook for the **public** build only. The personal Pi is separate and untouched by everything here (its tooling is `deploy.sh`,
`deploy/`). First-time setup is `docs/public-setup.md`; the design is `docs/public-architecture.md`. Marks: ✅ verified live in
session 29 (see PLAN.md for the evidence), ⚠ written from vendor documentation or a local stack, not yet exercised on the hosted
project.

## 1. Moving parts

| Piece | What it is | Where state lives |
|---|---|---|
| FastAPI Cloud app | `catch.main:app` via `fastapi run`; serves the API, the built SPA (`catch/api/static`) and `/mcp` from one origin | **nowhere** — scale-to-zero, ≤3 replicas (Hobby), no persistent disk; every in-memory structure (rate limits, JWKS cache, session-liveness cache) resets on cold start |
| Supabase Postgres | the only database; Catch's tables are in the non-exposed `catch` schema; runtime role `catch_api` | Supabase |
| Supabase Auth | sign-up/in, JWTs (ES256, JWKS) | Supabase |
| Supabase Storage | private `piece-photos` bucket | Supabase |
| Supabase `pg_cron` + `pg_net` | the only scheduler: calls `POST /internal/tick/*` with a bearer secret | Supabase (secret in Vault) |

There is no scheduler in the API process (`start_scheduler()` returns `None` when public) and none documented by FastAPI Cloud, so
**if the cron jobs stop, syncs, notifications and retention stop — the app itself keeps working.**

## 2. Deploy

Order matters: FastAPI Cloud's own guidance is to run an additive migration *before* deploying the code that needs it, and rollouts
are gradual (old and new code run side by side for a while), so every migration must be backward compatible with the previous build.
Migrations **never** run on app startup (`init_db()` is a no-op when public; the app only checks the role).

```
# 1. Tests and secret scan
CATCH_DEPLOYMENT=personal uv run pytest --ignore=tests/pg && (cd web && npm run lint && npm test)

# 2. Frontend, with PUBLIC values only (publishable key, never the secret key / DB URL — vite.config.ts refuses to build otherwise)
(cd web && VITE_CATCH_DEPLOYMENT=public VITE_SUPABASE_URL=https://<ref>.supabase.co VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_… npm run build \
   && npm run check:build-secrets && npm run check:bundle-size)

# 3. Database (admin URL from your shell, never committed or pasted into a deploy)
export DATABASE_ADMIN_URL=…            # postgres/admin role, direct or session-pooler string
uv run catch db upgrade                # no-op when already at head
uv run catch db current                # applied == expected, else "MISMATCH"

# 4. App
fastapi deploy                         # package → install/build → rollout → verification; a failed verification keeps the last good deploy

# 5. Verify (the tick secret authorises /internal/*)
curl -fsS https://<host>/api/health
curl -fsS -H "Authorization: Bearer $CATCH_TICK_SECRET" https://<host>/internal/db-check
```

`/internal/db-check` must report `superuser: false`, `bypass_rls: false`, `ssl: true`, both RLS probe fields `true`, and the expected
`pool_mode`. It reports `schema_revision: null` (the runtime role deliberately cannot read the version table); `catch db current` in
step 3 is the authoritative migration check.

`/api/health` is a dependency-free liveness probe (no database call — an outage must not make the platform restart-loop the app).
Use `/internal/db-check` (needs the secret) as the readiness/deep check from your own monitor.

**The built frontend is gitignored.** FastAPI Cloud uploads what `.gitignore` allows, refined by `.fastapicloudignore`; always run
`fastapi deploy` from a workspace where step 2 just ran, then confirm `GET /` returns the app and a nested route
(`/clubs/1`) does too. If the app starts without `catch/api/static/index.html` it logs
`catch/api/static/index.html is missing` and serves the API only.

### Environment variables

Set with `fastapi cloud env set` (secrets: `--secret`, ideally `--value-stdin`; **a secret can only be marked at creation** — to change
one, delete and re-create it). Setting a variable redeploys unless you choose "Save only" in the dashboard.

| Secret (`--secret`) | Plain |
|---|---|
| `DATABASE_URL` (`catch_api` through the pooler, `sslmode=require`) | `CATCH_DEPLOYMENT=public` |
| `SUPABASE_SECRET_KEY` (account deletion only) | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_JWT_AUDIENCE` (default `authenticated`) |
| `CATCH_SECRETS_MASTER_KEY` (≥ 32 chars) | `CATCH_BASE_URL=https://<host>` (**required**: MCP host allowlist, OAuth issuer) |
| `CATCH_TICK_SECRET` (≥ 32 chars) | `CATCH_OLLAMA_ENABLED=0` (**required**) |
| `CATCH_MODERATOR_IDS` | `CATCH_DB_POOL_MODE`, `CATCH_DB_POOL_SIZE` (default 1, +2 overflow) |
| `VAPID_PRIVATE_KEY` (push) | `CATCH_MCP_HTTP_ENABLED=1`, `CATCH_MCP_OAUTH_ENABLED=1`, `CATCH_MODERATOR_REQUIRE_AAL2=1` |
| `WITHINGS_/WHOOP_/CONCEPT2_CLIENT_SECRET`, `USDA_FDC_API_KEY` | provider client ids and redirect URIs, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT`, `CATCH_GARMIN_BYOK_ENABLED` |
| `APNS_KEY_P8`, `FCM_SERVICE_ACCOUNT_JSON` (native push, session 30) | `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_TOPIC`, `CATCH_NATIVE_ORIGINS`, `CATCH_NATIVE_URL_SCHEME`, `CATCH_APPLE_TEAM_ID`, `CATCH_APPLE_BUNDLE_ID`, `CATCH_ANDROID_PACKAGE`, `CATCH_ANDROID_CERT_SHA256` (docs/mobile/README.md) |

Never set on the deployed app: `DATABASE_ADMIN_URL`, `CATCH_PASSWORD_HASH`, `CATCH_FERNET_KEY`, `GARMIN_PERSONAL_API_KEY`,
`CONCEPT2_ACCESS_TOKEN`. The app refuses to start (and says which *setting* — never the value) when: Ollama is on, the master key is
missing/short, the tick secret is short, `CATCH_BASE_URL` is not a public https URL, the pool mode is invalid or contradicts the
port (6543 with `session`), or the runtime role bypasses RLS.

### Connection budget

Session-mode pool = `CATCH_DB_POOL_SIZE` (1) + 2 overflow = **3 server connections per replica**; Hobby tops out at 3 replicas ⇒ **9**.
Compare that with the project's pooler client limit and Postgres `max_connections` (Supabase dashboard → Database → Settings; a
nano/micro compute has a low ceiling). Extra requests wait for a slot (they do not fail), each transaction carries a 60 s
`statement_timeout`, and the connect timeout is 10 s. If session-mode slots run out under autoscaling, switch to the transaction
pooler: port **6543** in `DATABASE_URL` **and** `CATCH_DB_POOL_MODE=transaction` (no app pool, no prepared statements; everything
per-request is `SET LOCAL`, so it is safe). `tests/pg/test_runtime.py` proves 40 concurrent workers × 5 transactions finish through
a 1+2 pool and leave nothing checked out.

## 3. Scheduled work (`pg_cron` + `pg_net`)

| Job | Endpoint | Cadence | Does |
|---|---|---|---|
| sync | `POST /internal/tick/sync` | `7,37 * * * *` | every connected provider per user; advances one 30-day backfill window; refreshes club challenge scores |
| notifications | `POST /internal/tick/notifications` | `*/10 * * * *` | the five push-notification triggers |
| retention | `POST /internal/tick/retention` | `17 3 * * *` | prunes logs/usage/expired club reports and audit rows |

Each tick walks users one at a time under that user's own identity, stops *starting* users after 240 s (the rest are `deferred` to
the next tick, in a shuffled order so nobody starves), and takes a per-(user, job) lease (10 min) so overlapping or duplicate
deliveries skip a user already being served.

```sql
-- once, as the postgres role in the SQL editor; the secret is read from Vault at run time, never written into the job
create extension if not exists pg_cron;  create extension if not exists pg_net;
select vault.create_secret('<CATCH_TICK_SECRET>', 'catch_tick_secret');   -- keep this statement out of any saved snippet

select cron.schedule('catch-sync', '7,37 * * * *', $$
  select net.http_post(
    url := 'https://<host>/internal/tick/sync',
    headers := jsonb_build_object('Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'catch_tick_secret')),
    timeout_milliseconds := 60000) $$);
select cron.schedule('catch-notify', '*/10 * * * *', $$ … same with /internal/tick/notifications … $$);
select cron.schedule('catch-retention', '17 3 * * *', $$ … same with /internal/tick/retention … $$);
```

**Delivery semantics.** `pg_net` is asynchronous and fire-and-forget: it never retries. A missed or failed tick is repaired by the next
one (syncs are idempotent upserts keyed on `(source, external_id)`; the backfill cursor only advances after a window succeeds; a
provider that is rate-limiting or needs reconnecting is skipped with its own backoff). Duplicate or overlapping deliveries are safe
(lease). `pg_net`'s timeout is only how long *it* waits for the response — a tick that outlasts it still finishes in the app, and
shows as a timeout in `net._http_response`. ✅ Observed live: the sync tick outlasts the 5 s default wait and still completes in the app, which is why the jobs
set `timeout_milliseconds := 60000`. ⚠ FastAPI Cloud documents no request timeout; if a platform timeout ever cuts a tick at N
seconds, lower `TICK_BUDGET_S` below N (`catch/api/routes_internal.py`) — the remainder is simply deferred.

**Watching it:** `select * from cron.job_run_details order by start_time desc limit 20;` (did cron fire) and
`select status_code, error_msg, created from net._http_response order by created desc limit 20;` (what the app answered: 200 with
`{"users":…,"ran":…,"failed":…}`, 401 = wrong secret, 404 = tick secret unset/not public, 429 = throttled). A per-user failure is
logged without user data and counted in `failed`; per-source health is each user's *Settings → Connections* / `get_sync_status`.

**Never expose an unauthenticated trigger:** every `/internal/*` route needs `Authorization: Bearer <CATCH_TICK_SECRET>` (constant-time
compare), is throttled per source address *before* the secret is compared, and 404s when no secret is configured.

## 4. Backup and recovery

* Supabase **Free has no backups**; **Pro** keeps 7 daily backups (PITR is a paid add-on). Check the plan before relying on either.
* **Logical backup you control** (works on any plan; schedule it from a machine you own, store it encrypted off the project):
  `pg_dump "$DATABASE_ADMIN_URL" -n catch -Fc -f catch-$(date +%F).dump`. It excludes Storage objects, `auth.*` users and role passwords.
* **Restore drill (rehearsed):** restore into a *scratch* database, never over production: `createdb scratch && psql scratch -c 'create schema auth'` is not
  enough for RLS tests — use the local Supabase stack (`docs/public-setup.md` §8): `pg_restore --no-owner -d <local> catch.dump`, then
  `ALTER ROLE catch_api PASSWORD …`, run `catch db current` and `catch db check`, and compare row counts.
* **"Restore to a new project" (paid plans):** the clone does **not** include Storage objects, Auth settings/keys or Edge Functions, and
  — important — **its `pg_cron` jobs start immediately and would call production with the production secret.** First thing after the
  clone is up: `select cron.alter_job(jobid, active := false) from cron.job;` and rotate `catch_tick_secret` if the clone will live on.
* After any restore: re-set `catch_api`'s password, re-check Storage, confirm Auth URL settings, run `catch db current`.
* Account deletion removes a user's rows immediately; they persist in Supabase backups until those expire (7 days on Pro) — state that
  number in the privacy copy.

## 5. Redeploy, roll back, rotate

* **Redeploy** the same build with current config: dashboard → deployment → *Actions → Redeploy*. A new code build: `fastapi deploy`.
* **Roll back code:** dashboard → *Actions → Rollback* (FastAPI Cloud keeps at least the previous 5 ready deployments; the docs mark
  rollbacks "Coming soon", so ⚠ confirm the button exists, otherwise redeploy the previous git commit with `fastapi deploy`). There is
  no CLI rollback. Because rollouts are gradual, never ship a migration the previous build cannot read.
* **Roll back the database:** take a `pg_dump` first, then `uv run catch db upgrade <previous revision>` (revisions are in `migrations/versions/`).
* **Rotate:**
  * `catch_api` password: `ALTER ROLE catch_api PASSWORD '<new>'` → update `DATABASE_URL` (delete + re-create the secret) → redeploy. Existing
    connections drop on their next recycle (≤ 5 min).
  * Tick secret: delete/re-create `CATCH_TICK_SECRET` **and** `select vault.update_secret(id, '<new>') from vault.secrets where name='catch_tick_secret'`
    in the same window; until both match every tick answers 401.
  * `CATCH_SECRETS_MASTER_KEY`: put the new key in, move the old one to `CATCH_SECRETS_MASTER_KEY_PREVIOUS`, redeploy, `uv run catch secrets rotate`
    (re-seals every stored credential), then drop the previous key (`docs/security.md`).
  * Supabase secret key / publishable key: rotate in the dashboard, update `SUPABASE_SECRET_KEY` (delete + re-create) / `SUPABASE_PUBLISHABLE_KEY` and
    rebuild the frontend for the publishable one.
  * VAPID keys (push): rotating **either** key invalidates every push subscription — users must re-enable notifications. Generate the pair with the snippet in
    `.env.example` into a `chmod 600` file (never print it), set `VAPID_PRIVATE_KEY` with `fastapi cloud env set --secret --value-stdin`, and `VAPID_PUBLIC_KEY`/
    `VAPID_SUBJECT` as plain variables. `VAPID_SUBJECT` is sent to the browser push services, so a bare `https://<host>` origin keeps a personal e-mail out of it.
    The platform will not show a secret again; losing the private key means generating a new pair. Set up live in session 29; real delivery to a phone not yet confirmed.
  * Anything that ever appeared in a build output, log or chat: treat as leaked and rotate (F-38 is the precedent).

## 6. If a dependency is down

| Down | What happens | Do |
|---|---|---|
| FastAPI Cloud | the site and API are unavailable; data is safe in Supabase; `pg_cron` ticks fail harmlessly and resume | wait / check the platform status; redeploy the last good build |
| Supabase Postgres or the pooler | the app **fails closed**: requests error, `/api/health` stays 200 (liveness only), a *cold start* refuses to boot because the role check cannot connect; ticks answer errors and the next tick resumes | check the Supabase status page; connection-limit exhaustion → §2 "Connection budget" |
| Supabase Auth | nobody can sign in or refresh; already-issued tokens work until they expire (≤ 1 h) and the live-session check (`CATCH_SESSION_CHECK_TTL`) fails closed | wait |
| `pg_cron`/`pg_net` | scheduled work pauses, nothing else | `select * from cron.job_run_details`; re-create jobs |
| A user's provider | that user's source is marked failing/needs-reconnect with backoff (5 min … 6 h); nobody else is affected | user reconnects in *Settings → Connections* |

## 7. Monitoring

* **App logs:** `fastapi cloud logs --since 1h` (follow by default; retention 1 day on Hobby, 14 on Pro — ⚠ longer needs a Pro plan or an
  external drain). Every log record passes `catch/core/redact.py` (bearer tokens, JWTs, `?code=`/`?token=` query values, DB URL
  passwords, `sb_secret_…`, and the configured master/tick/DB-password values). ⚠ FastAPI Cloud's *platform* request log is outside that
  filter: check once whether an OAuth callback's `?code=` appears in it.
* **What the running process actually loaded:** `GET /internal/config-check` (tick-secret bearer) returns set/unset booleans for every operator setting, whether each
  provider redirect URI equals this deployment's callback, and which providers are available — never a value. `fastapi cloud env list` shows what was *saved*;
  this shows what the deployed instance *sees* (it caught a provider secret that was saved but empty). A secret is write-once: to change it, `env delete` then
  `env set --secret`.
* **Schema version:** `GET /internal/db-check` includes the applied revision when the runtime role may read it (usually null); `uv run catch db current` (admin URL)
  prints applied vs the revision this build expects.
* **Health:** your monitor polls `GET /api/health` (liveness) and, with the secret in a header, `GET /internal/db-check` (database + RLS).
  Alert on a non-200, `bypass_rls: true`, or `ssl: false`.
* **Supabase:** dashboard → Reports (database connections, CPU, disk), Logs, and the Backups page.
* **Sync/provider health:** `net._http_response` and `cron.job_run_details` (above); the `failed` count in each tick's JSON; per-user
  `get_sync_status`. There is no operator-wide dashboard — by design the operator tooling never reads a user's data.
* **Platform metrics:** *Application health* is on every plan; the request Activity view is Pro-only and needs FastAPI ≥ 0.142.

## 8. MCP

`/mcp/` (trailing slash) is **Streamable HTTP**, mounted in the app when `CATCH_MCP_HTTP_ENABLED=1`. On a public deployment it is
**stateless with plain JSON responses**: there is no `Mcp-Session-Id` to lose across replicas or a scale-to-zero. Auth is a device bearer token
minted in *Settings → Device tokens* (default scope `read`, expires in 90 days, cap 10 per account); the token resolves to its minting user
inside the database, and no tool accepts a user id. OAuth 2.1 for MCP (`CATCH_MCP_OAUTH_ENABLED=1`) is **on in production and confirmed with claude.ai** (connect, consent screen, tool call; 2026-11-19).
claude.ai registers itself as a confidential-style client (`client_secret_post`); Catch only issues public PKCE clients, so `/register` answers 201 as a public client
(`token_endpoint_auth_method: none`, no secret), which RFC 7591 §3.2.1 allows. PKCE S256 and exact redirect-URI rules are unchanged. A rejected `/register`,
`/authorize`, `/token` or `/revoke` is logged as `oauth <path> rejected: <status> <error>: <description>` (server-generated text only, never the request), so a failing
client is diagnosable from `fastapi cloud logs`. Also supported: clients that accept a remote Streamable-HTTP server with a bearer header (e.g. Claude Desktop through
`mcp-remote`/the stdio `catch-mcp` bridge; see `docs/mcp.md`). No claim is made about any chat product's plan tier supporting remote MCP —
verify with that client. Connection check: `POST /mcp/` without a token must answer `401`; with a valid token, an `initialize` + `tools/list`
must succeed (`scripts/smoke_public.py` does both).

## 9. Smoke test

`scripts/smoke_public.py` (needs `SMOKE_BASE_URL`, `SMOKE_SUPABASE_URL`, `SMOKE_PUBLISHABLE_KEY`, `SMOKE_SECRET_KEY`, `CATCH_TICK_SECRET` in the
environment; creates and deletes two disposable users) covers sign-in/out, JWT verification, a persisted write, two-user isolation, a read-only
MCP call, account deletion and a concurrent burst. See PLAN.md session 29 for the last run's results.
