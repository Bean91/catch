# Setting up the public deployment (Supabase + FastAPI Cloud)

Everything here is for the **public** build. The personal Pi needs none of it and shares nothing with it (docs/public-architecture.md §1).
Steps marked ⚠ could not be tested from the development machine and are listed again in PLAN.md → "needs the owner".

## 1. Supabase project

1. Create a project (note the **project ref** and region). Choose a strong database password; it is only used to log in as `postgres` for step 3.
2. **Auth → Providers → Email**: enabled; **Confirm email: on** (the frontend assumes a sign-up returns no session until the link is clicked);
   minimum password length 8 or more; turn on leaked-password protection if your plan has it.
3. **Auth → URL Configuration**: *Site URL* = the app's public URL; *Redirect URLs* = exactly that URL (no wildcards in production).
4. **Auth → Sessions**: access-token expiry **1 hour or less** (the default). A token cannot be revoked before it expires; Catch narrows that
   window with a live-session check (`CATCH_SESSION_CHECK_TTL`, default 15 s) but a shorter expiry is the second layer.
5. **Auth → Emails**: configure **custom SMTP** before inviting anyone — the built-in sender is limited to 2 emails/hour.
6. **Project Settings → JWT Keys**: use an **asymmetric signing key (ES256)**, not the legacy shared secret. Catch verifies tokens against the
   project's JWKS and refuses HS256 outright. (A legacy-secret project publishes no JWKS, so every request would 401.)
7. **Project Settings → API**: copy the publishable key (`sb_publishable_…`) and the secret key (`sb_secret_…`).
8. **Project Settings → Data API → Exposed schemas**: leave the list as it is — Catch's tables live in a `catch` schema that is **not** exposed,
   and `anon` has no privileges on it. (If you disable the Data API entirely, nothing changes for Catch.)
9. **Database → Extensions**: only `pg_cron` and `pg_net` are needed, and only for the scheduled tick (§5). Enable nothing else.

> **Never add `catch` to Supabase's "Exposed schemas" (Data API / PostgREST).** Session 27's club tables are writable by `authenticated` under row-level policies that check *who* may write, not that a score or result value is honest (the service computes those), so the app role must remain the only way in.

## 2. Roles and migrations (one source of truth: Alembic)

The schema is changed **only** by the Alembic revisions in `migrations/` — never in the dashboard. Run them with an admin URL from a trusted machine:

```
export DATABASE_ADMIN_URL='postgresql://postgres:<db password>@db.<ref>.supabase.co:5432/postgres'   # direct is fine from a laptop with IPv6;
#   otherwise use the pooler string: postgres.<ref>@aws-…pooler.supabase.com:5432
uv sync --extra public
uv run catch db upgrade          # = alembic upgrade head: tables, roles, RLS, tenant FKs, auth triggers, private bucket
uv run catch db seed             # global reference data: the exercise library and example templates
psql "$DATABASE_ADMIN_URL" -c "ALTER ROLE catch_api PASSWORD '<a long random password>'"
```

The migrations create the `catch_api` login role (no superuser, **no BYPASSRLS**, no privileges on any owned table — it can only `SET ROLE authenticated` for those;
since revision `0005` it also has direct grants on the shared leaderboard tables, reached only through `catch/sync/leaderboard_store.py`, and since `0006` permissive policies on the club tables for `catch/sync/club_store.py`) and live in the non-exposed `catch` schema (plus `catch_private` for three SECURITY DEFINER lookups, and `catch_club` — policy predicates for clubs, executable by `authenticated`, see `docs/clubs.md` §10). Revision `0002` needs the `auth` schema, so it only runs against a Supabase database.
To roll back: `uv run catch db upgrade 0001` (drops policies/roles, keeps data) or `base`. **Take a backup first** (§7).

## 3. Connection string for the app (FastAPI Cloud has no documented IPv6 egress)

Use the **shared pooler**, which is IPv4: Supabase dashboard → *Connect* → *Session pooler*. The user is `catch_api.<project-ref>`.

```
DATABASE_URL=postgresql://catch_api.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

* **Session mode (5432)** is the default: supports prepared statements, needs nothing special from the driver.
* **Transaction mode (6543)**: set `CATCH_DB_POOL_MODE=transaction` — no app-side pool, no prepared statements. Everything per-request is
  `SET LOCAL`/`set_config(…, true)` inside the transaction, so it is safe. Use it only if session-mode client slots run out under autoscaling.
* Add `sslmode=verify-full&sslrootcert=…` with the project's root certificate (Database settings) once you can ship the file; `require`
  encrypts but doesn't verify the server. Turn on **Database settings → "Enforce SSL"**.
* Pool: 1 connection per replica (+2 overflow) by default; Hobby caps at 3 replicas.
* ⚠ Whether a custom role works through the pooler, and whether FastAPI Cloud can reach it, is checked by `catch db check` (§4) — run it **from the deployed app**.

Never use the `postgres` user or the direct connection string for `DATABASE_URL`: the app refuses to start when the role bypasses RLS.

## 4. FastAPI Cloud

1. `uv sync --extra public`; build the frontend with the public flags, from a workspace where `catch/api/static` exists:
   ```
   cd web && VITE_CATCH_DEPLOYMENT=public VITE_SUPABASE_URL=https://<ref>.supabase.co VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_… npm run build
   ```
2. Secrets (`fastapi cloud env set --secret …`, write-once): `CATCH_MODERATOR_IDS` (session 26: comma-separated Supabase user ids who may moderate leaderboards), `DATABASE_URL`, `SUPABASE_SECRET_KEY`, `CATCH_TICK_SECRET`, `CATCH_SECRETS_MASTER_KEY`,
   `VAPID_PRIVATE_KEY` (if push is wanted). Plain variables: `CATCH_DEPLOYMENT=public`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `CATCH_OLLAMA_ENABLED=0`,
   `CATCH_BASE_URL=https://<your host>`. **Do not** set `DATABASE_ADMIN_URL`, `CATCH_PASSWORD_HASH`, `CATCH_FERNET_KEY`, `GARMIN_PERSONAL_API_KEY` or `CONCEPT2_ACCESS_TOKEN` there (users supply their own; a public deployment never reads them). To offer OAuth sources set `WITHINGS_*`, `WHOOP_*` and `CONCEPT2_CLIENT_ID/SECRET/REDIRECT_URI` as secrets (redirect URIs `https://<your host>/auth/<provider>/callback`, registered with each provider), and `CATCH_GARMIN_BYOK_ENABLED=0` to switch Garmin off (docs/garmin-byok.md).
3. `fastapi deploy`. The entrypoint is `[tool.fastapi] entrypoint = "catch.main:app"`.
4. **Dependencies.** FastAPI Cloud's docs mention only `pyproject.toml`/`uv.lock`, nothing about extras, and it starts the app with `fastapi run` (confirmed by a failed first deploy:
   `To use the fastapi command, please install "fastapi[standard]"`). So `fastapi[standard]`, `psycopg[binary]` and `pyjwt[crypto]` are in the main dependencies behind a
   `platform_machine not in 'armv6l armv7l'` marker (no 32-bit ARM wheel for psycopg-binary; a 32-bit Pi installs none of them). Only `alembic` stays in the `public` extra, for the laptop.
5. ⚠ **Is the built frontend uploaded?** It is gitignored and uploads follow `.gitignore`; `.fastapicloudignore` has a `!catch/api/static/` line, but whether a
   re-include overrides `.gitignore` is not documented. Check `GET /` after deploying; if it 404s, serve the frontend from a static host instead.
6. ⚠ **Run `curl -H "Authorization: Bearer $CATCH_TICK_SECRET" https://<app>/internal/db-check`** — it reports the connected role, SSL, and performs the RLS probe
   from inside FastAPI Cloud. `superuser`/`bypass_rls` must be `false` and both probe fields `true`.
7. ⚠ Confirm SSE streaming (the coach), request timeouts and the 1-day (Hobby) / 14-day (Pro) log retention suit you — none are documented.

## 5. Scheduled work (no scheduler in the process)

FastAPI Cloud scales to zero and documents no cron, so syncs and notifications are driven by a **tick** — `POST /internal/tick/sync` and `/internal/tick/notifications`,
bearer `CATCH_TICK_SECRET`. Each walks the users one at a time under that user's identity; a per-(user, job) lease keeps overlapping ticks from running twice.
From Supabase (`pg_cron` + `pg_net`; put the secret in Vault, not in the SQL) ⚠ untested:

```sql
select vault.create_secret('<CATCH_TICK_SECRET>', 'catch_tick_secret');
select cron.schedule('catch-sync', '7,37 * * * *', $$
  select net.http_post(url := 'https://<app>/internal/tick/sync',
    headers := jsonb_build_object('Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'catch_tick_secret'))) $$);
select cron.schedule('catch-notify', '*/10 * * * *', $$ … same, /internal/tick/notifications … $$);
```

Source connections (session 25, docs/provider-connections.md): each user connects their own Garmin key / Withings / Concept2 / Whoop under Settings → Connections.
OAuth callbacks are unauthenticated redirects identified by a signed `HttpOnly` cookie, which assumes **the web app and the API share an origin**. The tick walks
connected providers per user within a 240 s budget; history import advances one window per tick.

## 6. Security headers

The app sends a strict `Content-Security-Policy` (scripts from itself plus the hash of the one inline theme script, connections to itself and the Supabase project,
no framing), HSTS, `nosniff`, a restrictive `Permissions-Policy`. Put the app on a custom domain you control (FastAPI Cloud: automatic TLS) and keep the Supabase
Site URL identical to it.

## 7. Backups and recovery

* Supabase **Pro** keeps 7 daily backups (Team 14, Enterprise 30); **Free has none** — schedule `pg_dump -n catch -Fc` yourself. PITR is a paid add-on.
* Backups **do not include Storage objects** or custom-role passwords. After a restore: `ALTER ROLE catch_api PASSWORD …`, and re-check Storage.
* The restore path was rehearsed against the local stack: `pg_dump -n catch -Fc`, drop the schema, `pg_restore --no-owner`, rows and all 210 policies came back
  and isolation held (`tests/pg/test_migrations.py::test_backup_and_restore_…`).
* Never use the production project as a test fixture: the `tests/pg` suite refuses non-local hosts.

## 8. Local rehearsal (what the tests use)

```
npm i supabase && npx supabase init && npx supabase start -x studio,imgproxy,edge-runtime,logflare,vector,mailpit,realtime   # a throwaway stack
export CATCH_TEST_SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres CATCH_TEST_SUPABASE_URL=http://127.0.0.1:54321 \
       CATCH_TEST_SUPABASE_PUBLISHABLE_KEY=… CATCH_TEST_SUPABASE_SECRET_KEY=…          # from `supabase status -o env`
uv run pytest tests/pg                        # migrations, RLS, Storage, GoTrue, the app on the real runtime path
CATCH_TEST_PG_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres uv run pytest   # the whole suite on PostgreSQL
```
Browser end to end (a real browser, the real CSP, real confirmation and recovery emails): set `site_url`/`additional_redirect_urls` to `http://127.0.0.1:8799`, `enable_confirmations = true`, `[auth.rate_limit] email_sent` high, mailpit on; build the web app with the public flags pointing at the local stack; then `cd web && npm run test:live` (see `web/playwright.live.config.ts`).
For the pooler test, enable `[db.pooler]` in `supabase/config.toml` and set `CATCH_TEST_SUPABASE_POOLER_URL=postgresql://postgres.pooler-dev:postgres@127.0.0.1:54329/postgres`.


## 7. Session 28 operator checklist (before real users)

Required settings the app now enforces at startup (it refuses to start otherwise): `CATCH_OLLAMA_ENABLED=0`; `CATCH_SECRETS_MASTER_KEY` set, ≥ 32 characters (the
Pi-only `CATCH_FERNET_KEY` fallback is not accepted); `CATCH_TICK_SECRET` (if used) ≥ 32 characters. Run `catch db upgrade` for migration **0008**.

New or changed settings: `CATCH_MODERATOR_REQUIRE_AAL2=1` (default; moderators must have completed MFA — enable TOTP in Supabase and enrol the moderator accounts);
`CATCH_MCP_OAUTH_ENABLED=0` (keep off until verified with a real client; needs `CATCH_MCP_HTTP_ENABLED=1`). Schedule a third tick job:
`POST /internal/tick/retention` once a day (same bearer secret as the others) — it prunes notification/tool-call/usage logs and expired club reports/audit rows.

Supabase dashboard (the local stack's config is weaker than these on purpose; see the table in `docs/security.md`): minimum password length ≥ 12 and character
requirements; leaked-password protection if the plan has it; **Secure password change on**; **MFA (TOTP) enabled**; sign-up/sign-in/recovery rate limits tightened and
CAPTCHA on; *Redirect URLs* exactly the app URL; confirm email on. Check and write down: database backup / PITR retention (what survives an account deletion and for how
long — the deletion policy draft needs this number), Auth log retention, FastAPI Cloud log retention and whether OAuth callback `?code=` appears in request logs.

Operator duties the code can't do: legal review of `docs/legal/*` before launch; the contact/controller details those drafts leave blank; a process for the safeguarding concerns
and data-subject requests the drafts mention; run `catch secrets status` after any key change; keep `.github/workflows/security.yml` green (gitleaks, pip-audit, npm audit).
