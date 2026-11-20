# FastAPI Cloud deployment (public build)

How the public app is deployed and what was verified. Set-up rationale is in [public-setup.md](public-setup.md) §4–6; day-to-day
operation is in [operations.md](operations.md); incidents are in [operations-runbook.md](operations-runbook.md). Session 31 (launch
audit, 2026-11-20).

**FastAPI Cloud was in beta when this was written.** Anything not run against it is marked **untested**.

## 1. What runs where

- **App:** `catch.main:app` started with `fastapi run` (`[tool.fastapi] entrypoint`). Scale-to-zero. One process per replica, with
  no scheduler in the process (`start_scheduler` is a no-op on public).
- **Frontend:** `catch/api/static`, built locally with the public flags and uploaded by `fastapi deploy`. `.fastapicloudignore`
  re-includes the gitignored build.
- **Scheduled work:** Supabase `pg_cron` + `pg_net` POST `/internal/tick/{sync,notifications,retention}` with `CATCH_TICK_SECRET`.
  It doesn't depend on a permanently running process (PASS, session 29 and session 31: ticks wake the app).
- **No local persistent disk.** The public code path writes nothing durable to the filesystem:
  - Garmin FIT files are parsed in a temporary directory and deleted.
  - Photos go to Supabase Storage.
  - OAuth state uses a signed cookie plus an in-memory single-use set (F-7: resets on a cold start, per replica).

  Rate-limit buckets are also in memory, per replica (F-08).
- **No inbound webhooks.** No provider pushes to Catch: Garmin's Personal API, Withings, Concept2 and Whoop are all pull-only here
  (provider-connections.md). So "webhook delivery and retries" doesn't apply. The only push-like inbound is the `pg_net` tick,
  retried by the next cron run.

## 2. Release procedure (migrate first, then deploy)

```sh
# 0. On a clean checkout of the commit being released
make check                                     # ruff + pytest + frontend typecheck/lint/vitest/build/bundle/secret greps + Playwright
DATABASE_ADMIN_URL=… uv run catch db current    # where production is
# 1. Backup (no platform backups on Free; see supabase-setup.md §7)
pg_dump "$DATABASE_ADMIN_URL" --format=custom -n catch -n catch_private -n catch_club -f catch-$(date +%F).dump
# 2. Migrate (the previous build must still run on the new schema)
DATABASE_ADMIN_URL=… uv run catch db upgrade && DATABASE_ADMIN_URL=… uv run catch db current
# 3. Frontend with PUBLIC values only
(cd web && npm ci && VITE_CATCH_DEPLOYMENT=public VITE_SUPABASE_URL=https://<ref>.supabase.co VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_… npm run build && npm run check:build-secrets)
# 4. Deploy
fastapi deploy
# 5. Verify
curl -sS https://catch.openoted.com/api/health
curl -sS -H "authorization: Bearer $CATCH_TICK_SECRET" https://catch.openoted.com/internal/db-check   # schema_missing_tables must be [] (necessary, not sufficient)
DATABASE_ADMIN_URL=… uv run catch db current   # the authoritative revision check
SMOKE_SECRET_KEY_FILE=~/.catch-smoke-secret … uv run python scripts/smoke_public.py
```

**Why the order matters.** On 2026-11-20, production ran session 30's code on a 0008 database. Account deletion, push device
listing and health status returned 500 (audit L-38). Since session 31 the app logs `database is behind this build — missing tables …`
at startup, and db-check reports `schema_missing_tables`.

## 3. Environment variables and secrets

The full list is in [operations.md](operations.md) "Environment variables". Rules:

- **Secrets are write-once.** To change one: `fastapi cloud env delete NAME`, then `fastapi cloud env set --secret NAME --value-stdin`
  from a `chmod 600` file. Use `--no-redeploy` to batch changes. A change redeploys.
- **Whitespace.** Every value is `.strip()`ped since session 31 (`bf3848e`). A trailing newline from `--value-stdin` broke Withings
  in production.
- Never set `DATABASE_ADMIN_URL`, `CATCH_PASSWORD_HASH`, `CATCH_FERNET_KEY`, `GARMIN_PERSONAL_API_KEY` or `CONCEPT2_ACCESS_TOKEN` here.
- **Set `CATCH_GARMIN_BYOK_ENABLED` explicitly** (`1` or `0`). Leaving it unset now logs a startup warning (audit L-26), because the
  default offers Garmin BYOK to every user. Whether to offer it is the owner's decision (blocker B-6).
- `GET /internal/config-check` (with the tick secret) lists which settings the running process loaded, as booleans only.

| Check (production) | Status |
|---|---|
| Secrets stored as encrypted secrets, not plain variables | OWNER. The session 29 runbook did this; session 31 couldn't list them without the CLI login |
| `config-check` shows every required secret loaded | NOT VERIFIED in session 31 (the tick secret wasn't provided). PASS in session 29 |
| No production secret in frontend builds | PASS: `check:build-secrets` (web) and `check:native-secrets` ("343 files clean"), 2026-11-20 |

## 4. Domain and HTTPS (checked 2026-11-20, unauthenticated)

| Check | Result |
|---|---|
| `https://catch.openoted.com` TLS | PASS: Google Trust Services WE1, expires 2027-02-13 (automatic renewal is the platform's) |
| `http://` → `https://` | PASS: 301 |
| HSTS | PASS: `max-age=31536000; includeSubDomains` |
| CSP / XFO / nosniff / Referrer / Permissions-Policy | PASS |
| API docs not exposed | PASS (`/docs` and `/openapi.json` serve the SPA's HTML) |
| `/mcp` requires auth, OAuth metadata served | PASS |

## 5. Logs

- The app's own log records pass `core/redact.py` (env secrets pinned; provider errors, tool errors and sync errors redacted).
  The log-hygiene tests pass (`tests/tenancy/test_log_hygiene.py`).
- **Platform request logs are not under the app's control.** Whether FastAPI Cloud logs query strings, such as an OAuth
  `?code=` on `/auth/*/callback` or `/oauth/consent?req=…`, and for how long (1 day Hobby, 14 days Pro per its docs), is
  **NOT VERIFIED** (F-21). Owner: read a callback's log line after the next provider connection.

## 6. Rollback, restart, autoscaling (all **untested** in session 31; not authorised)

- **Rollback:** redeploy the previous good commit (`git checkout <sha>`, rebuild the frontend, `fastapi deploy`). The dashboard's
  *Actions → Rollback* was documented as "Coming soon"; check whether it exists.
- **Instance restart / cold start:** the app holds no state that matters across restarts:
  - The in-memory rate limits reset.
  - OAuth single-use state resets (at most a replayed state within 10 minutes; the signed cookie still binds it).
  - The JWKS cache refills.

  Scale-to-zero cold starts were observed in session 29 (ticks wake the app); their latency isn't measured.
- **Autoscaling:** more replicas means more pool connections (≤ 3 per replica) and weaker in-memory rate limits (F-08).
  Untested beyond what the smoke's 40-concurrent burst exercised.

## 7. Operational risks to accept or fix before launch

1. The beta platform has an undocumented cron, rollback and log retention. Mitigated: ticks come from Supabase.
2. Single region and a single person on call; no uptime alerting (blocker B-8).
3. In-memory, per-replica rate limits and OAuth state (F-08, F-7).
4. Request-size limits at the platform edge are unknown; the app enforces its own body limits (`core/uploads.py`).
5. Long SSE coach responses vs. the platform's request timeout are unknown (public-setup.md §4 ⚠).
