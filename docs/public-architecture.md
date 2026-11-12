# Public deployment architecture (Supabase + FastAPI Cloud)

Written **before** any schema change (Session 24; the brief called itself "session 19" — this repo already had 23).
Status key used throughout: **[docs]** = stated by the vendor's current documentation (URL in §9), **[local]** =
verified by running the real Supabase local stack (`supabase start`, GoTrue + Postgres + Storage) during this session,
**[unverified]** = could not be tested from here and is listed in §10 as something the owner must check.

## 1. Two deployments, nothing shared

| | Personal | Public |
|---|---|---|
| Host | Raspberry Pi 3 (1 GB, PiAware alongside) | **FastAPI Cloud** (API + static SPA) |
| Database | SQLite (WAL) on the Pi's disk | **Supabase** managed PostgreSQL |
| Identity | one argon2 password → signed cookie | **Supabase Auth** (JWT, ES256) |
| Users | exactly one (`owner_id = "owner"`) | many (`owner_id = auth.users.id`) |
| Scheduler | in-process APScheduler | **none in the process** (see §5) |
| Files | `data/fit/*.fit`, local disk | none on local disk (see §5, §8) |
| AI keys | the owner's, in `ai_credentials` | each user's own (BYOK), same table |
| Selected by | `CATCH_DEPLOYMENT=personal` (default) | `CATCH_DEPLOYMENT=public` |

They share **code** (one repository) and nothing else: separate database, separate secrets, separate Supabase project,
no Supabase dependency on the Pi (`uv sync` on the Pi installs none of the Postgres/JWT/Alembic packages — they live in
the optional `public` extra, because `psycopg-binary` publishes no 32-bit ARM wheel).

Hosted by **Supabase**: PostgreSQL, Auth (GoTrue), Storage (private buckets), the pooler (Supavisor), backups.
Hosted by **FastAPI Cloud**: the FastAPI app (REST + coach SSE + the built SPA) and nothing stateful.
Hosted by **neither / the owner**: the cron trigger for scheduled work (§5), DNS, the Anthropic/OpenAI/Gemini accounts
(each user's own).

## 2. Data inventory — every table, and who owns it

52 tables before this session (53 with `user_profiles`): 48 strictly owned, 3 shared-reference, 2 global. `owner_id` is Catch's name for the brief's `user_id` (10 tables already carried it from session 23; renaming
them would have rewritten sealed-credential AAD bindings and ~80 call sites for no isolation benefit).

**Global / shared reference data (no user data, shared read-only to everyone):**

| Table | Why global |
|---|---|
| `weather_cells` | cache keyed by 0.1° cell + UTC day; contains no user id, only public weather |
| `foods` (`source` = `off`/`usda`) | public-database cache. **`source="manual"` rows are user-owned** (`owner_id` set, NULL for the shared cache) — a manual food would otherwise become every user's barcode answer |
| `exercises` (`custom = false`) | seeded library. **`custom = true` rows are user-owned** (NULL `owner_id` = global/seeded) |

Seeded `workout_templates` examples are rows with `owner_id IS NULL`, readable by all, writable by none.

**User-owned (every other table), grouped:**

- *Source data:* `activities`, `strokes`, `activity_samples`, `activity_tracks`, `activity_weather`, `canonical_activities`,
  `match_decisions`, `merge_log`, `routes`, `daily_wellness`, `wellness_readings`, `daily_scores`, `body_comp`
- *Subjective / notes:* `notes`, `checkins`, `illness_acks`, `technique_notes`, `coach_feedback`, `coach_feedback_revisions`
- *Training:* `pieces`, `piece_intervals`, `piece_photos`, `recommendations`, `planned_workouts`, `training_phases`,
  `workout_templates` (non-seed), `events`, `goals`, `athlete_facts`
- *Gym:* `gyms`, `gym_stations`, `strength_sets`, `strength_templates`
- *Nutrition:* `food_logs`, `my_foods`, `saved_meals`, `nutrition_targets`
- *Coach / AI:* `coach_settings`, `coach_conversations`, `coach_messages`, `ai_credentials`, `ai_usage_events`, `coach_credentials` (legacy, Pi-only)
- *Integrations & devices:* `oauth_tokens`, `sync_state`, `api_tokens`, `push_subscriptions`, `notification_log`, `settings`

Plus one new table: `user_profiles` (§4).

Tables whose **primary key was a single non-owner column** need an owner in the key or two users collide:
`daily_wellness`, `daily_scores`, `checkins`, `illness_acks` (`date`), `wellness_readings` (`date,source,signal`),
`sync_state`, `oauth_tokens` (`source`), `settings`, `nutrition_targets` (`id=1`), `coach_credentials` (`provider`).
Unique constraints that were global and would let user B overwrite user A's row on an idempotent sync:
`activities (source, external_id)`, `body_comp (source, external_id)`, `strength_sets.client_id`, `my_foods.food_id`,
`push_subscriptions.endpoint`, `workout_templates.external_id`, `match_decisions`, `planned_workouts.linked_canonical_id`.
All gain `owner_id` (§6).

## 3. Everything that assumed one user

- `OWNER_ID` / `ATHLETE` constants: 79 uses across 19 modules (planning, workout library, coaching notes, coach
  memory/tools/chat, providers registry, notify triggers, training intelligence, routes) — **the owner now comes from a
  request-scoped context, never a constant or an argument a tool/frontend can supply**.
- `require_auth` = "a valid cookie exists"; it identifies nobody.
- `catch.core.db`: SQLite engine built at import time; `Path(...).mkdir` at import; `init_db()` runs `create_all` +
  hand-rolled `ALTER TABLE` + seeds on every startup; `CREATE INDEX IF NOT EXISTS` raw SQL.
- `catch.sync.scheduler`: APScheduler in the web process, one in-process lock per source, jobs that touch "the" athlete.
- `catch/sync/whoop_client.py`: a process-global `threading.Lock` guarding a *rotating* refresh token — unsafe across replicas.
- Module-level caches: `routes_analytics._series_cache` (keyed by metric, **not** by owner — a cross-user leak on a
  shared process), `openfoodfacts_client._miss_cache` (public data, safe), `coach/limits.py` rate/concurrency state
  (already per-owner, in-process), `scoring._lock`.
- Local filesystem: `data/fit/*.fit` (Garmin downloads, re-parsed by `backfill-gps`); `catch/api/static` (the built SPA,
  **gitignored** — and FastAPI Cloud's upload follows `.gitignore`).
- Server-wide secrets that stay server-wide: VAPID keys, `CATCH_SECRETS_MASTER_KEY`, OAuth *app* credentials.
- Frontend: service worker caches every `GET /api/*` (network-first, cache fallback); the gym logger keeps a device
  IndexedDB queue — both survive a logout and would show/flush user A's data into user B's session.

## 4. Identity: Supabase Auth, one profile table

- Supabase Auth owns credentials, email verification, password recovery, sessions, refresh tokens. **Catch has no
  password database in public mode** (`CATCH_PASSWORD_HASH` and the cookie are Pi-only).
- Catch's own `user_profiles(id, display_name, email, created_at)`; `id` is `auth.users.id` **as text** (and the constant `"owner"` on the Pi).
  Every `owner_id` column is `TEXT` on both engines, with a foreign key to `user_profiles(id) ON DELETE CASCADE`. (A native `uuid` column would allow a
  real FK to `auth.users`, but the Pi's owner is not a uuid, one model has to serve both engines, and the suite runs the same schema on SQLite and PostgreSQL.
  The link to `auth.users` is therefore the trigger pair below plus the lazy upsert, not a foreign key.)
- **Synchronisation** (two independent paths, so a failure of one never loses a user):
  1. *Trigger* `on auth.users after insert` → insert the profile (`security definer`, in a non-exposed schema,
     body wrapped in `exception when others` so **it can never block a sign-up** — Supabase warns that a failing
     trigger blocks signups [docs]).
  2. *Lazy upsert* on the first validated request: `INSERT … ON CONFLICT DO NOTHING` under the user's own RLS context.
  - *Deletion:* every owned table has `owner_id → user_profiles(id) ON DELETE CASCADE`, and `user_profiles.id → auth.users(id)
    ON DELETE CASCADE`, so removing the auth user removes the profile and every row. Storage objects are **not** covered by
    that cascade and *block* user deletion [docs], so account deletion deletes objects first (§8).

## 5. Runtime facts that shape the public design

**FastAPI Cloud** (beta-era docs, fastapicloud.com):
- Code is uploaded, built into a container image in the cloud, rolled out gradually; `.gitignore` is honoured, refined
  by `.fastapicloudignore` [docs]. Python 3.10+; dependencies from `uv.lock`/`pylock.toml`/`requirements.txt` [docs].
  Whether **optional extras** are installed is **not documented** [unverified] — see §10.
- **Scale to zero is on by default; on Hobby it is always on** (min 0, max 1–3 replicas); a Pro team can keep a
  minimum of 1 [docs]. Cold starts are expected. Nano instance = 0.1 vCPU / 500 MiB [docs].
- Env vars and *secrets* (encrypted, write-once, never viewable) via CLI or dashboard [docs]. Logs: dashboard + `fastapi
  cloud logs`; **1-day retention on Hobby, 14 on Pro** [docs]. Custom domains: Hobby 1, Pro 20, automatic TLS [docs].
- **Not documented anywhere I could find:** persistent/local filesystem, background tasks, cron/scheduled jobs,
  long-running processes, WebSocket/SSE behaviour, request timeouts, IPv6/IPv4 egress, static egress IPs, regions.

Consequences (**design rules, because these are unknowns**):
1. **No APScheduler in public mode.** A scale-to-zero replica is not a scheduler, and N replicas would run every job N
   times. `start_scheduler()` is skipped; scheduled work is a **tick endpoint** (`POST /internal/tick/{job}`, bearer
   `CATCH_TICK_SECRET`, constant-time compare, rate-limited) invoked by Supabase `pg_cron` + `pg_net` or any external
   cron. The tick loops over users **one at a time with an explicit per-user context**. A per-(user, job) *lease* (a `sync_state` row `job:<name>`,
   claimed under a transaction-scoped advisory lock — the only kind that is safe behind a pooler) stops two overlapping ticks double-running; a lease older
   than 10 minutes is considered dead. The user list comes from a SECURITY DEFINER function, so the runtime role never needs a bypass.
2. **No local files.** Nothing in public mode writes to or reads from disk for user data. FIT-file based features
   (Garmin download, `backfill-gps`) stay Pi-only until a Storage-backed blob store exists; Garmin public access needs
   Garmin's developer approval anyway.
3. **No `create_all`/`ALTER TABLE` at startup.** The schema is changed only by Alembic, run by a human/CI with an admin
   URL — never by the app and never with the runtime role.
4. **No assumption of IPv6 egress.** The runtime connects through the **shared pooler**, which is IPv4 [docs].
5. **No transaction held across an LLM stream.** The chat loop commits (ending its read transaction) immediately before each provider stream; a test stalls a stream mid-way and asserts via
   `pg_stat_activity` that no `catch_api` session is `idle in transaction` (it failed before the fix — the memory-block read had left one open for the whole stream).
6. **Rotating Whoop refresh tokens** need `SELECT … FOR UPDATE` on the token row in public mode (the in-process lock is
   per-replica); until then Whoop is documented as single-replica-safe only.
7. Rate limits / AI concurrency are in-process (`coach/limits.py`); with several replicas the real ceiling is N× — a
   documented limitation, mitigated by the per-owner USD/token daily caps being DB-backed.

**Supabase** [docs unless noted]:
- Connections: direct `db.<ref>.supabase.co:5432` is **IPv6** on Free/Pro (IPv4 only with the paid add-on, which is
  *not* dual-stack); the **shared pooler** `aws-…pooler.supabase.com` is **IPv4** in **session mode (5432)** and
  **transaction mode (6543)**. Pooler username is `<role>.<project-ref>`. Transaction mode: **no prepared statements**,
  session state (`SET`, advisory session locks, `LISTEN`, temp tables) is lost between transactions.
- SSL: drivers default to `prefer` (can fall back to plaintext); use `sslmode=require` at minimum, `verify-full` with the
  project root certificate for verification.
- Pool sizing: serverless guidance is a pool of 1 per instance; total backends must stay below the compute's maximum.
- Roles: `anon`, `authenticated`, `service_role` (**BYPASSRLS**), `postgres` (**BYPASSRLS**), `authenticator`.
- RLS: `to authenticated` on every policy, `(select auth.uid())` for the initPlan optimisation, one policy per command, an
  UPDATE needs a matching SELECT policy, **views bypass RLS** unless `security_invoker = true`, index the policy columns.
- JWTs: ES256/RS256 signed, public keys at `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` (cached at the edge
  10 min — do not cache longer); claims `iss`, `aud`, `exp`, `sub`, `role`, `session_id`, `aal`, `is_anonymous`.
  **An access token cannot be revoked before `exp`**; the documented check is that `session_id` still exists in
  `auth.sessions`. Legacy HS256 projects return no JWKS.
- Backups: daily on Pro (7 days) / Team (14) / Enterprise (30); PITR is a paid add-on (2-minute RPO); Free has **no**
  automatic backup (use `supabase db dump`); backups **exclude Storage objects**; custom-role passwords are not in backups.

## 6. Isolation model — three layers, none relied on alone

1. **Request principal.** In public mode a dependency validates the bearer JWT and sets a request-scoped owner
   (a `ContextVar`). In personal mode the owner is the constant `"owner"`. Tool handlers read the principal from the
   context; **no tool parameter, route body or query string can name an owner.**
2. **Service layer (ORM) — enforced on both SQLite and Postgres.** A `do_orm_execute` hook adds
   `owner_id = :owner` to every SELECT/UPDATE/DELETE on an owned model (`with_loader_criteria`, applied to
   `session.get`, relationship loads and bulk statements); a `before_flush` hook stamps `owner_id` on new rows and
   **raises** if a row being written carries a different owner. In public mode an owned-table access with no owner set
   **raises** (fail closed); there is no default owner. Anything that bypasses the ORM (`exec_driver_sql`, `text()`) is
   banned outside `catch/core/db.py` and migrations by a test.
3. **PostgreSQL RLS — only where the connection really evaluates it.** The runtime connects as a dedicated login role
   `catch_api` that is `NOSUPERUSER NOBYPASSRLS`, owns no tables, and is granted `authenticated`. Every *transaction*
   (not every request — routes `commit()` mid-request and `SET LOCAL` dies with each transaction) begins with
   `SET LOCAL ROLE authenticated` and `set_config('request.jwt.claims', <claims json>, true)` (+ `request.jwt.claim.sub`),
   issued from a SQLAlchemy `after_begin` event. With no owner set, the begin fails — it never falls back to
   `catch_api`'s own (empty) privileges silently, and `catch_api` has **no** table grants, so a missed hook yields
   "permission denied", not data. Policies are `to authenticated using (owner_id = (select auth.uid())::…)`, forced
   (`FORCE ROW LEVEL SECURITY`), one per command.

   **The limitation to state plainly:** the migration role (`postgres`/admin) and Supabase's `service_role` **bypass RLS**.
   Alembic and the single account-deletion admin call use those; the request path never does. If an operator ever
   points `DATABASE_URL` at `postgres` or a pooler string for `postgres`, RLS protects **nothing** on those requests and
   only layer 2 remains. A startup check refuses to serve in public mode when `current_setting('is_superuser')` or
   `rolbypassrls` is true for the connected role.

**Data API.** The tables are not meant to be reached through PostgREST. Supabase exposes `public` by default, and with the
publishable key in the browser any signed-in user could call it with their own JWT — RLS would stop cross-user access but
not a user rewriting *their own* `ai_usage_events` (resetting their spend cap) or skipping piece/interval validation. So:
all Catch tables live in a **`catch` schema that is not in the project's exposed-schemas list**, `anon` has no grants, and
`authenticated` has only the DML grants FastAPI needs. RLS stays on as depth.

**Foreign-key checks bypass RLS.** A user could attach a piece to another user's `canonical_id` (the FK check reads the parent
as the table owner). Two defences: on Postgres the 20 declared child references to strictly-owned parents are *composite*
`(owner_id, parent_id) → parent(owner_id, id)` keys (migration `0002`, `fk_tenant_*`); and in public mode the ORM's `before_flush`
resolves **every** reference — those 20 plus the 9 soft ids the models carry without a foreign key (technique notes, coach feedback,
merge log, template provenance; soft because the app deliberately keeps them after the target is merged or deleted) — *for this owner*, reporting
a foreign id as *not found* (404, never 403 — no existence oracle). References to the three shared tables (exercises, foods, workout templates)
keep a plain FK (a composite one can't match a NULL-owner parent) plus the ORM guard; a stray reference there yields an invisible row, not a disclosure.

## 7. Connection modes

`DATABASE_URL` (runtime, role `catch_api`) and `DATABASE_ADMIN_URL` (migrations only, never in the runtime env).
- Default for FastAPI Cloud: shared pooler, **session mode (5432)** — IPv4, supports prepared statements, no driver
  restrictions, and `set_config(..., true)` works as it does in any transaction.
- Transaction mode (6543) is supported by configuration (`CATCH_DB_POOL_MODE=transaction` → psycopg `prepare_threshold=None`,
  `NullPool`) because a scale-to-zero fleet can exhaust session-mode client slots; it is safe here because all per-request
  state is `SET LOCAL`/`set_config(…, true)` inside a transaction.
- `catch db check` connects, reports role/BYPASSRLS/SSL/prepared-statement support and performs an RLS probe — **run it from
  FastAPI Cloud itself** (it is also `GET /internal/db-check` behind the tick secret) because egress cannot be tested from a
  laptop [unverified].
- Pool: `pool_size=1, max_overflow=2, pool_pre_ping=True, pool_recycle=300` per replica (Hobby ≤ 3 replicas ⇒ ≤ 9
  backends), overridable by env.

## 8. Storage

See `docs/public-storage.md`. Summary: user photos (PM5 photos) go in a **private** bucket under `<user id>/…`, `storage.objects`
policies compare `(storage.foldername(name))[1]` to the JWT `sub`, access via short-lived signed URLs, deleted before the
auth user (objects block deletion) and **not** covered by database backups. The Pi keeps `piece_photos` in SQLite.

## 9. Sources

FastAPI Cloud: how-it-works, install-dependencies, configuring-fastapi, environment-variables, logs, custom-domains,
autoscaling, instance-sizes, billing (all under https://fastapicloud.com/docs/). Supabase: guides/database/connecting-to-postgres,
…/pooling-and-limits, database/postgres/row-level-security, …/roles, platform/backups, auth/jwts, auth/signing-keys,
auth/sessions, auth/passwords, auth/redirect-urls, auth/managing-user-data, api/api-keys, storage/security/access-control,
storage/serving/downloads, storage/uploads/file-limits, reference/javascript/auth-admin-deleteuser.

## 10. Verified against a real Supabase stack (`supabase start`, CLI 3.1, Postgres 17.11, GoTrue 2.197) — session 24

* `auth.uid()` is `coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''), (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid`
  (`pg_get_functiondef`) — Supabase's docs don't say which setting it reads; the app sets **both** (`set_config(…, true)`, i.e. `SET LOCAL`).
* Roles: `service_role` and `postgres` have `rolbypassrls = true`; `anon`, `authenticated`, `authenticator` do not. `postgres` is not a superuser there.
* The local project signs with **ES256** and publishes `/auth/v1/.well-known/jwks.json` (one P-256 key with a `kid`).
* `catch_api` (`NOINHERIT`, `NOBYPASSRLS`) **cannot** `SET ROLE anon|service_role|postgres|supabase_admin` — only `authenticated` — and has no table privileges until it does.
* `GRANT authenticated TO catch_api` and triggers on `auth.users` work for the `postgres` migration role; `storage.objects` policies can be created by it; direct
  `DELETE FROM storage.objects` is refused by Storage (objects are removed through its API).
* A real sign-up fires the profile trigger; GoTrue's admin delete with the **secret key in the `apikey` header only** cascades `auth.sessions`, so the app's session
  check rejects the user's unexpired token; `signOut(scope=global)` does the same.
* Through a real **Supavisor transaction pooler**, 60 interleaved transactions across three users never saw each other's rows, and a bare pooled connection afterwards carried no
  identity. (Local Supavisor only knows its provisioned `postgres.<tenant>` user; custom roles through the *hosted* pooler are documented but ⚠ untested.)
* `alembic upgrade head` ≡ the SQLModel metadata (`compare_metadata` is empty); downgrade to `0001`/`base` and back keeps data; pg_dump/pg_restore of the schema keeps rows,
  forced RLS and all policies.
* The whole existing suite passes on SQLite **and** on PostgreSQL (`CATCH_TEST_PG_URL`; the one skip is a SQLite-rowid-reuse premise).

## 11. Needs the owner (cannot be tested from this environment)

1. Create the Supabase project and FastAPI Cloud app; follow `docs/public-setup.md`.
2. Run `fastapi cloud` deploy, then `catch db check` **on FastAPI Cloud** — egress to the pooler, SSL, role, RLS probe.
3. Confirm FastAPI Cloud installs the `public` extra (else deploy a `requirements.txt` — documented in `docs/public-setup.md`).
4. Confirm SSE streaming and request timeouts for the coach on FastAPI Cloud (undocumented).
5. Garmin Connect Developer Program approval; Whoop tier approval (new apps capped at 10 members); Open-Meteo commercial
   licence; a non-OSM tile source (see session 20/23 blockers in PLAN.md).
