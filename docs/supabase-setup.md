# Supabase setup and verification (public deployment)

What the production Supabase project must look like, and what was actually checked. The step-by-step history and rationale are in
[public-setup.md](public-setup.md) §1–3, §7–8. Incident steps are in [operations-runbook.md](operations-runbook.md). Session 31 (launch
audit, 2026-11-20).

Status key:
- **PASS** means checked in session 31.
- **PASS (local)** means checked on the local `supabase start` stack.
- **OWNER** means only the project owner can see or change it in the dashboard.
- **NOT VERIFIED** means it was not checked.

## 1. Project and plan

| Item | Required | Status |
|---|---|---|
| Plan | Pro or higher before real users (Free: no backups, projects pause when idle) | **FAIL — the project is on Free** (session 29). Blocker B-3. |
| Region | close to FastAPI Cloud's region (latency); note it | OWNER |
| Project ref / URL | in `SUPABASE_URL` (server) and `VITE_SUPABASE_URL` (frontend build) | PASS: the production smoke signed users in through it |
| Exposed schemas (Data API) | `catch`, `catch_private` and `catch_club` must **not** be listed | OWNER; `anon` has no privilege on `catch` (PASS (local), `tests/pg/test_migrations.py`) |
| Extensions | `pg_cron`, `pg_net` only (plus Supabase defaults) | PASS: session 29 ran the cron jobs |

## 2. Auth (GoTrue)

| Setting | Required | Status |
|---|---|---|
| JWT signing key | asymmetric (ES256); Catch refuses HS256 | PASS: production sign-in and token verification worked in the smoke |
| Access-token expiry | ≤ 1 hour | OWNER |
| Email provider | on; **Confirm email on** | OWNER. The live confirmation path was never run (no SMTP); see below |
| **Custom SMTP** | configured (the built-in sender sends 2 emails/hour) | **FAIL / NOT VERIFIED.** Blocker B-5. Without it, sign-up confirmation and password recovery don't work beyond a trickle. |
| Site URL / Redirect URLs | exactly `https://catch.openoted.com` (+ `com.openoted.catch://…` for the native apps) | OWNER |
| Password policy | min ≥ 12, character classes, leaked-password protection (plan permitting) | OWNER (F-17) |
| Secure password change | on | OWNER (F-17) |
| MFA (TOTP) | enabled; moderator accounts enrolled (`CATCH_MODERATOR_REQUIRE_AAL2=1`) | OWNER (F-17, F-11). `aal2` was tested only with synthetic tokens. |
| Rate limits + CAPTCHA | sign-up, sign-in and recovery tightened; CAPTCHA on | OWNER (F-17) |
| Session revocation | sign-out and deletion end an unexpired token within `CATCH_SESSION_CHECK_TTL` | **PASS (production smoke, 2026-11-20):** after sign-out the token was rejected |

## 3. Database: migrations, roles, RLS

| Check | Status |
|---|---|
| Migrations at head (`0010` after this branch) | **FAIL in production.** Production is at `0008` under `0009` code (2026-11-20: endpoints backed by `0009` tables return 500). Owner: `DATABASE_ADMIN_URL=… uv run catch db upgrade`, then `catch db current`. Blocker B-1. |
| Migrations apply cleanly from empty and pass the structure tests | PASS (local): `tests/pg/test_migrations.py`, 99 passed with 1 skipped in `tests/pg` on HEAD |
| RLS enabled **and forced** on every user-owned table | PASS (local): 89/89 tables in `catch` (all except `alembic_version`); `test_rls_all_tables.py` + `backup_restore_drill.py` |
| Policies tested with **separate Supabase Auth identities** (select/insert/update/delete denied across users) | PASS (local): `tests/pg/test_rls.py`, `test_rls_all_tables.py`, `test_clubs.py`, `test_leaderboards.py` |
| Same in production | PASS for the paths it covers (production smoke, 2026-11-20): B can't read A's note and can't list or delete A's tokens (404) |
| Runtime role `catch_api`: no superuser, no BYPASSRLS, no grants on owned tables | PASS (local): `test_grants_leave_the_runtime_role_and_anon_with_nothing`. In production the app refuses to start otherwise (`assert_unprivileged`). |
| SECURITY DEFINER functions set `search_path = ''`, revoked from PUBLIC/anon | PASS (static review of 0002–0009 + `tests/pg`) |
| `weather_cells` refresh by a user request | **was FAIL** (permission denied on UPDATE, reproduced locally). Fixed by migration `0010` (provisional rows only); not yet applied in production |
| Global tables reachable only through `catch_api`'s store modules | PASS (local); see audit M2/M4/M5 for the remaining Low notes |

## 4. Privileged access (review)

- **`postgres` / admin URL.** Used only from the operator's machine for `catch db upgrade|seed|current`, never set in FastAPI Cloud
  (`config-check` would show it).
- **Supabase secret key (`SUPABASE_SECRET_KEY`).** Used by one function, `routes_account.admin_delete_auth_user` (GoTrue admin
  delete), plus the Storage purge in account deletion. It is pinned out of the redaction LRU on purpose (session 29). It is never
  in a frontend build: `check:build-secrets` and `vite.config.ts` refuse `sb_secret_`/`service_role`, and the native scan reported
  "343 files clean" (session 31).
- **`catch_api` with direct grants.** Only on global tables, only through `leaderboard_store`, `club_store`, `native_push_store` and
  `account_store` under `tenant.system_detached()`.
- **`service_role`.** Has no privileges on `catch.*` (PASS (local)).

## 5. Connection mode and pool

| Item | Value | Status |
|---|---|---|
| Pooler | shared pooler, **session mode, port 5432** (`CATCH_DB_POOL_MODE=session`) | PASS: session 29 (`/internal/db-check` from the deployed app) |
| App pool | 1 connection per replica + 2 overflow; Hobby caps at 3 replicas | from config |
| Under load | local, 40 concurrent requests over 20 users and 21,900 activities: peak **3** `catch_api` connections, no errors | PASS (local) `scripts/load_local.py` |
| Production under load | 120 requests, 40 concurrent: all 200, 3.3 s | PASS (production smoke, 2026-11-20) |
| Transaction mode (6543) | supported (`CATCH_DB_POOL_MODE=transaction`); startup refuses a mode/port mismatch | PASS (local) `tests/pg/test_pooler.py` |
| Statement timeout | 60 s per transaction (`tenant_hooks`) | from code |

## 6. Storage

| Check | Status |
|---|---|
| `piece-photos` bucket private, per-uid object policies, MIME and size limits (migration 0003) | PASS (local): `tests/pg/test_storage.py` |
| Club logos | stored as DB rows (`club_logos`), not Storage | from code |
| Account deletion purges the user's objects before the auth delete | PASS (local): `tests/pg/test_runtime.py::test_account_deletion_removes_data_files_sessions_and_the_sign_in_account`. **FAIL in production until B-1 is fixed.** |
| Storage objects are in backups | **No.** Supabase backups exclude Storage; there is no separate copy | OWNER, recorded |

## 7. Backups and recovery

- **Production: no backups exist.** Free plan, no PITR, no `pg_dump` ever taken. Blocker B-3.
- The dump command must include all three schemas: `pg_dump --format=custom -n catch -n catch_private -n catch_club`. The previous
  docs said `-n catch` only (audit L-39).
- Restore drill: `scripts/backup_restore_drill.py`, 15/15 on the local stack (2026-11-20). Everything is restored except the two
  `auth.users` triggers, which must be re-created by hand (runbook §7, audit L-40).
- What survives an account deletion and for how long: the backup retention period of whichever plan is chosen. The deletion-policy
  draft needs that number (F-21).

## 8. Re-verify after any change

```sh
DATABASE_ADMIN_URL=… uv run catch db current                       # applied vs expected revision
curl -H "authorization: Bearer $CATCH_TICK_SECRET" https://catch.openoted.com/internal/db-check   # role, ssl, RLS probe, schema_missing_tables ([] is necessary, not sufficient)
SMOKE_SECRET_KEY_FILE=~/.catch-smoke-secret SMOKE_BASE_URL=… SMOKE_SUPABASE_URL=… SMOKE_PUBLISHABLE_KEY=… uv run python scripts/smoke_public.py
```
