# Operations runbook (public deployment)

What to do when something is wrong with https://catch.openoted.com (FastAPI Cloud + Supabase). Background, configuration and the
full command reference stay in [operations.md](operations.md); first-time setup is [supabase-setup.md](supabase-setup.md) and
[fastapi-cloud-deployment.md](fastapi-cloud-deployment.md). Written in session 31 (launch audit). Anything marked **untested** has
not been exercised against the hosted services.

Owner: the operator (one person today). Every step needs the FastAPI Cloud CLI logged in, the Supabase dashboard, and the admin
database URL from your own shell, never pasted into a deploy, chat or ticket.

## 0. First five minutes, whatever the problem

1. `curl -sS https://catch.openoted.com/api/health` should return `{"ok":true}`. A connection failure or 5xx means the app is down (§1).
2. `curl -sS -H "authorization: Bearer $CATCH_TICK_SECRET" https://catch.openoted.com/internal/db-check`. Check, in order:
   - `bypass_rls` must be false.
   - `ssl` must be true.
   - the RLS probes must pass.
   - **`schema_missing_tables` must be empty** (added in session 31).
   - `schema_revision` is shown when readable.
3. `curl … /internal/config-check` shows which secrets the running process loaded (booleans only).
4. Read the FastAPI Cloud logs for the window. Logs are redacted (`core/redact.py`), but treat them as sensitive anyway.
5. Read the Supabase dashboard: Database → Reports (connections, CPU), Auth → Logs, and `select * from cron.job_run_details order by start_time desc limit 20;`.

## 1. The app is down or answering 5xx

- **Every request fails.** Check FastAPI Cloud's deployment status, then the startup log. A refused start names the problem
  (`Refusing to start the public deployment: …`), for example a weak master key, Ollama on, or a pool-mode/port mismatch. Fix the
  secret (`fastapi cloud env delete` then `env set --secret`; secrets are write-once) and redeploy.
- **Some endpoints 500, others work.** Look for `database is behind this build — missing tables …` at startup, or a non-empty
  `schema_missing_tables` in db-check. **This happened in production on 2026-11-20:** session 30's code ran on a 0008 database, so
  account deletion, push device listing and health status all returned 500. Fix: `DATABASE_ADMIN_URL=… uv run catch db upgrade`, then
  `uv run catch db current`. Order for every future release: **migrate first, then deploy.** A migration must be one the previous
  build can still run against.
- **Database unreachable.** Check Supabase status and the project's pause state. Free projects pause after inactivity, so resume
  in the dashboard. Then check the pooler string and port: session mode is 5432, transaction mode is 6543 with
  `CATCH_DB_POOL_MODE=transaction`. Then check that `catch_api`'s password still matches `DATABASE_URL`.

## 2. Scheduled work stopped (no syncs, no notifications)

Ticks come from Supabase `pg_cron` + `pg_net`, not from the app (the app scales to zero). The jobs are `sync` and `notifications`
(every 10 min) and `retention` (daily).

1. `select jobname, active, schedule from cron.job;` — all three must be active.
2. `select status, return_message, start_time from cron.job_run_details order by start_time desc limit 10;`
3. `select id, status_code, content::text from net._http_response order by created desc limit 10;`
   - **401:** the Vault secret and `CATCH_TICK_SECRET` differ. Update both in the same window (operations.md §5).
   - **429:** before session 31, bad-secret floods could fill the per-IP bucket the tick shares. That's fixed: only failed attempts
     are counted now. A persistent 429 means a deployment older than session 31.
   - **Timeout:** the job has a 60 s `pg_net` timeout and a 240 s per-tick user budget. Users left over run on the next tick
     (`deferred` in the response).
4. A single user whose syncs never run probably holds a stuck lease. Session 31 releases a lease on failure; an older deployment
   held it for 10 minutes. Leases expire on their own.

## 3. A provider is failing for everyone

`get_sync_status` (coach/MCP) or Settings → Status shows the last error in plain words.

- **Withings: `Invalid HMAC signature`** (seen in production on 2026-11-20, 8 failures in a row). The client secret was stored with a
  trailing newline. Session 31's `bf3848e` strips whitespace from every env value. Deploy that, then confirm the next Withings sync
  succeeds. If it still fails, re-enter `WITHINGS_CLIENT_SECRET` (delete, then `env set --secret --value-stdin` from a file).
- **Everyone flipped to "needs reconnect" at once.** Every 400/401 from a token endpoint is read as a revoked grant (audit L-41).
  A rotated client secret or a provider outage produces this. Fix the app secret first, then ask users to reconnect.
- **429 / backoff.** Catch backs off per user (5 min up to 6 h; `Retry-After` wins). Withings' and Whoop's limits are per app, not
  per user, so a growing user count will hit them.

## 4. Account deletion fails

Users see "could not delete". The causes, in the order the endpoint runs:

1. A Storage purge error gives 502, and nothing is deleted.
2. Global rows: leaderboard entries, native push tokens, club data. **A 500 here usually means the database is behind (§1).**
3. The tombstone is written, then the GoTrue admin delete with the secret key runs. A 502 lifts the tombstone so the person can
   retry.

Every step is idempotent, so retrying is safe. Afterwards, confirm the auth user is gone (Supabase → Auth → Users) and that
`select count(*) from catch.user_profiles where id = '<id>'` returns 0.

## 5. Suspected secret leak

Treat anything that appeared in a log, build output, chat or ticket as leaked (F-38 is the precedent).

1. Rotate it (operations.md §5 lists every secret and its procedure).
2. For `catch_api`, review Supabase connection logs for the exposure window.
3. Run the secret scan: `docker run --rm -v "$PWD:/repo:ro" ghcr.io/gitleaks/gitleaks:v8.30.1 git /repo --config /repo/.gitleaks.toml`.
4. Record it in docs/security-findings.md.

## 6. Roll back a bad release

1. **Code:** redeploy the previous good commit: `git checkout <sha> && (cd web && npm ci && npm run build) && fastapi deploy`.
   FastAPI Cloud's dashboard rollback was documented as "Coming soon" in session 29; **untested**.
2. **Database:** only if the release migrated, and only after a `pg_dump` (§7). Run
   `DATABASE_ADMIN_URL=… uv run catch db upgrade <previous revision>`. Downgrades are destructive:
   - 0010 → 0009 drops the weather refresh policy (harmless).
   - 0009 → 0008 drops native push tokens and health consents.
   - 0008 → 0007 drops the deleted-account tombstones.

   Prefer rolling code forward over downgrading the schema.
3. Run `scripts/smoke_public.py` (operations.md §9). It needs the secret key from a `chmod 600` file. Since session 31 it no longer
   leaks a user when deletion fails.

## 7. Restore data

**Production has no backups today.** The project is on Supabase Free and no `pg_dump` has ever been taken; this is a launch blocker
(docs/launch-audit.md B-3). Until that changes, take one before any risky change:

```sh
pg_dump "$DATABASE_ADMIN_URL" --format=custom -n catch -n catch_private -n catch_club -f catch-$(date +%F).dump   # all three schemas
```

`-n catch` alone (what operations.md and public-setup.md said before session 31) misses `catch_private` and `catch_club`. Policies
call functions in those schemas, so that restore is incomplete.

Restore (rehearsed on the local stack by `scripts/backup_restore_drill.py`: 15/15, 2026-11-20):

1. Restore to the local stack or a scratch project first, never straight over production.
2. Run `pg_restore --exit-on-error -d "$DATABASE_ADMIN_URL" catch-YYYY-MM-DD.dump` into a database without those schemas.
3. **Re-create the two `auth.users` triggers.** They sit on Supabase's own table, so a schema-level dump doesn't carry them, and
   `DROP SCHEMA … CASCADE` removes them. Without them, sign-ups get no profile and account deletion leaves rows behind:

   ```sql
   CREATE OR REPLACE TRIGGER catch_on_auth_user_created AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION catch_private.handle_new_user();
   CREATE OR REPLACE TRIGGER catch_on_auth_user_deleted AFTER DELETE ON auth.users FOR EACH ROW EXECUTE FUNCTION catch_private.handle_deleted_user();
   ```

4. `ALTER ROLE catch_api PASSWORD '<new>'`, then update `DATABASE_URL`.
5. Run `catch db current`, `catch db check` and `/internal/db-check`; `schema_missing_tables` must be empty.
6. Storage objects (piece photos, club logos) are not in the dump. Re-check the bucket.
7. A "restore to a new project" clone starts its `pg_cron` jobs immediately, against production. Disable them first
   (operations.md §4).

## 8. Abuse or a moderation emergency

- Report floods: three distinct reporters, each with an account at least 7 days old, auto-hide an item. Moderators
  (`CATCH_MODERATOR_IDS`, with `aal2` MFA required) act in Settings → Moderation, and every action needs a written reason.
- Suspend a club or restrict a person: `sync/restrictions.py` via the moderation UI.
- Rate limits are per replica and in memory (F-08), so a large flood needs Cloudflare or platform-level blocking.

## 9. Monitoring that exists today

| Signal | Where | Alerting |
|---|---|---|
| App up | `/api/health` | **none configured.** Owner: add an external uptime check (blocker B-8) |
| Ticks running | `cron.job_run_details`, `net._http_response` | none |
| Per-user sync broken | push notification to that user (`sync_broken`) | per user only; `ntfy`/healthchecks are personal-mode only |
| Schema behind code | startup ERROR log, `/internal/db-check` | none, log only |
| Errors | FastAPI Cloud logs | none |

Before launch, at minimum add an uptime check on `/api/health` and a daily check of `cron.job_run_details` (release checklist).
