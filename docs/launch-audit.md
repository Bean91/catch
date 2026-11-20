# Launch audit (session 31, 2026-11-20)

Scope: the full pre-launch audit asked for in session 31 (routes, API, models/migrations, jobs, providers, coach/MCP tools,
Supabase Auth/RLS, permissions, analytics, AI/MCP clients, Supabase, FastAPI Cloud, security, performance, UX, release).
Branch `session-31-launch-audit`.

**Verdict: NO-GO for a public launch.** See [Blockers](#blockers). No release tag was created (docs/release-checklist.md).

Rules this document follows:
- **PASS** means the check was actually run in this session and the evidence line says how. **NOT VERIFIED** means it was not
  run (no account, no device, not authorised). **FAIL** means it was run or inspected and does not meet the bar.
- Production was touched only as authorised: unauthenticated `curl`, `scripts/smoke_public.py` (if run — see §F), and
  read-only/preview-only calls through the owner's own claude.ai MCP connector. No production `pg_dump`, deploy, rollback or
  config change was made.
- Finding IDs `L-nn` are this session's; `F-nn` are the session 28 register (docs/security-findings.md).

## Findings

Severity: Critical / High / Medium / Low / Info. Status: Fixed (commit on this branch) / Open / Accepted (owner decision
needed or taken) / Recorded (a documented limitation, not a defect to fix before launch).

| ID | Sev | Area | Finding | Status |
|---|---|---|---|---|
| L-01 | Low | Tests | `tests/tenancy/test_api_isolation.py::test_the_real_tick_for_fresh_accounts…` failed whenever run 08:00–10:00 local (the morning-brief window). Product behaviour was right; the test was wall-clock dependent. | Fixed (clock pinned) |
| L-02 | Low | Tests | `test_no_private_health_or_training_value_appears_in_any_club_response` flaked: the 4-digit sentinel `3141` matched inside a random id/timestamp. | Fixed (token-bounded match; still catches a real leak) |
| L-03 | Medium | Web / misleading UI | `?mock=1` worked on the **production public site**: it skipped sign-in and showed a signed-in-looking app with fake data and "Connected" sources. No real data exposed, but anyone could send a convincing fake link on the real domain. | Fixed: a public non-dev bundle ignores `?mock` unless built with `VITE_CATCH_ALLOW_MOCK=1`; `vite.config.ts` refuses that (or `VITE_CATCH_MOCK`) in a public production build. Deployed site still has the old bundle until the owner deploys. |
| L-04 | Medium | Web / misleading UI | Public Status page rendered "Disk free 0 B of 0 B", "Database size 0 B", "Uptime 0m", "No backup has run yet" — the API deliberately returns zeros there. | Fixed (cards hidden on public) |
| L-05 | Medium | Leaderboards | `leaderboard_store.board_rows` capped at 5000 rows with **no ORDER BY**, then ranked in Python: past the cap, arbitrary rows dropped and ranks wrong. | Fixed (verified-first, best-first ordering before the cap; regression test fails without the fix) |
| L-06 | Medium | Jobs / abuse | `/internal/*` throttled by IP *before* the secret check. Behind the platform's shared proxy addresses (F-30), junk requests could fill the bucket the real pg_cron tick shares and 429 it. | Fixed (only failed attempts are metered; guessing still is) |
| L-07 | Low | Push | APNs device token went into the URL path and `app_id` into `apns-topic` with only length/whitespace checks (`/`, `?`, `#`, `..` passed). Host allow-list held, so no SSRF. | Fixed (per-platform token alphabet, reverse-DNS app id) |
| L-08 | Low | Tests | `tests/test_postgres_optional.py` hard-coded 3 added columns; session 28 added two. Never noticed because it only runs with `CATCH_TEST_PG_URL`. | Fixed |
| L-09 | **High** | Analytics / multi-user | **No per-user time zone.** Every "local day" (strain, load, recovery's prior-day strain, Today, check-ins, nutrition days, PBs, gym PR grouping) uses the *server's* zone — `astimezone()` with no argument, `date.today()` — or, at a dozen sites, the UTC `.date()` of an aware datetime. On the public server (zone assumed UTC, not verified) a Pacific 18:00 session lands on the next day, "today" rolls over at 16:00–17:00 Pacific, a Sydney 06:30 check-in files under yesterday, and Garmin's athlete-local `calendarDate` disagrees with UTC-bucketed activities. The web also defaults some dates with `toISOString().slice(0,10)` (UTC): `Body.tsx` manual weight date, `ClubSheets.tsx`, the `to` bound in Trends/Body/ExpandedTrendChart. DST itself is handled correctly by `_local_day_utc_range` (23 h / 25 h days verified). **Already affects the owner's production data.** | Open — launch blocker. Needs a `user_profiles.timezone` field + migration + settings UI + one helper every bucketing site goes through; a partial fix would make the mixed conventions worse. |
| L-10 | Medium | Analytics | `piece.aggregate_from_splits` averaged split *durations* for the average split: wrong whenever splits aren't exactly 500 m (3×500 m @1:45 + 250 m in 52 s gave 1:31.75; correct 1:44.86). | Fixed: total time / total distance × 500 in Python and `pieceSplits.ts`; None when there's no distance. Average watts/rate stay unweighted means (no PM5 fixture settles their semantics; Recorded). Pieces saved earlier keep their stored value. |
| L-11 | Low | Analytics | `piece.validate_splits` assumes 500 m when a split row has no distance, so a timed piece with typed watts gets a false "implied watts" warning. | Recorded |
| L-12 | Low | Analytics | `piece.find_best_window` has no coverage gate: a window with one real sample and nine gaps can win auto-align. | Recorded |
| L-13 | Medium | Analytics / missing data | `strain.daily_activity_strain` averaged a missing kcal in as 0 (`scoring.py` passed `active_kcal or 0.0`), halving the steps term. | Fixed (only available terms averaged; test) |
| L-14 | Medium | Nutrition / missing data | Under-fuelling flag included **today's partial day**, and a food with unknown kcal counted as 0 on a "logged" day (phantom deficit). | Fixed (window ends yesterday; unknown-kcal days count as unlogged; both tests fail without the fix) |
| L-15 | Low | Nutrition / DST | `copy_day_logs` shifts UTC timestamps by N×24 h, so the local time drifts an hour across a DST change. | Recorded (subsumed by L-09) |
| L-16 | Medium | Recovery / missing data | After 7 HRV nights, a day with **no wellness row at all** still scored (50, yellow) from prior-day strain alone. | Fixed: no score without HRV, resting HR or sleep (test). RHR still has no minimum history / SD floor (Recorded). |
| L-17 | Low | Strength | `epley_e1rm(100, 1)` = 103.3 (the docstring calls that "close enough"); reps capped at 10 make a 20-rep set an e1RM floor PR detection treats as real; `normalize_muscle_au` clamps rather than normalises. | Recorded (changing it would rewrite users' PR history) |
| L-18 | Low | PBs | `_PB_DISTANCES_M` tolerance `max(25 m, 2 %)`: 475 m counts as a 500 m PB and a 1960 m/400 s piece beats a 2000 m/405 s one. `erg_test.detect_test_type` uses a tighter tolerance; the two disagree. | Recorded |
| L-19 | Info | Load | `load.py` EWMA uses λ = 2/(N+1) (Williams), about 2× faster than Coggan's 1−e^(−1/τ); not comparable to other apps' ATL/CTL. No minimum history for ACR. Sessions with neither HR nor RPE enter load as 0 (same as a rest day). | Recorded (docs/analytics.md) |
| L-20 | Info | Cycling | `cycling_load` docstring claims TSS ≈ TRIMP; one hour at HRr 0.8 is TRIMP ~143 vs TSS 100, so cycling strain is under-weighted ~1.4–2×. Average power, not NP. | Recorded |
| L-21 | Low | Planning | `workload_change_flags` compares against `max(ref)`, so a +16 % planned week can hide a +133 % leap over actual training (docs §29 describe the same rule). | Recorded |
| L-22 | Medium | Web / misleading UI | Settings offered **metric / imperial units**, but nothing read the setting. | Fixed (toggle removed; everything is metric and labelled) |
| L-23 | Low | Web | Two `formatDistance` functions ("2,000m" vs "2 km"); `formatTimeTenths(-5)` → "-1:55.0" (latent); `predicted_2k` means s/500 m on Today but total seconds in `/api/series` (both rendered correctly today). | Recorded |
| L-24 | Low | Concept2 | `concept2_client.py:183` assumes UTC when a result has neither `date_utc` nor `timezone`. | Recorded |
| L-25 | **High** | Legal / UI | The unreviewed legal drafts are bundled and rendered at `/legal/*` and `/account-deletion` (also signed out) with "DRAFT — NOT LEGALLY REVIEWED", "Contact: [to be filled in]", counsel notes. Same root as F-18. | Open — launch blocker (owner + counsel). Not edited here: inventing legal text or a contact address would be worse. |
| L-26 | Medium | Garmin | `CATCH_GARMIN_BYOK_ENABLED` defaults to `1`; a public deploy that forgets it offers Garmin BYOK, which Garmin's own wording ("not intended for commercial applications serving multiple end users") puts in doubt. The owner's production Garmin uses BYOK today, so the default was **not** flipped. | Open — owner decision (B-6); a startup warning now fires when it's left implicit |
| L-27 | Medium | Abuse | Open Food Facts limiters are process-global (15/min barcode, 10/min search) while a user may make 30/min: one user can exhaust everyone's lookups, which then fail open as "not found". Barcode unvalidated (fixed host, no SSRF); `_miss_cache` unbounded. | Open (post-launch; not a data-exposure issue) |
| L-28 | Medium | Performance | Several reads return the whole history when `from`/`to` are omitted (`/api/wellness`, `/api/checkins`, `/api/body`, `/api/coach/conversations` + messages). `/api/activities` and leaderboards paginate. | Recorded (measured in §H) |
| L-29 | Medium | Abuse | No per-user row/size quotas beyond the 2 MB body cap: note text unbounded, manual `weight_kg` unranged, each write recomputes scores inline; `PUT /api/settings` can trigger a full-history recompute with no rate limit. | Recorded |
| L-30 | Low | Errors | A few handlers return `detail=str(exc)` for `ValueError`/`KeyError` (`routes_coach.py`, `routes_oauth.py`, `routes_analytics.py`, `routes_calendar.py`): parse messages can reach the client. No stack traces. | Recorded |
| L-31 | Low | MCP | `/mcp` principal lookup does blocking DB calls inside the async ASGI `__call__`. | Recorded |
| L-32 | Low | Web | Settings' "Connected sources" listed Garmin even when unavailable; `/clubs`, `/leaderboards`, moderation routes existed in personal builds and showed errors; the Coach chat box is enabled with no AI key (it explains on send). | Fixed (first two); the coach box Recorded |
| L-33 | **High** (ops) | Withings (production) | Production Withings sync has failed 8× in a row since 2026-11-20 00:37 UTC: `getnonce failed … Invalid HMAC signature` (read via the owner's MCP `get_sync_status`). Matches the newline-terminated-secret bug fixed in `bf3848e` (not yet deployed). | Open — owner: deploy, then confirm the next Withings sync succeeds; if not, re-enter the secret. |
| L-34 | Medium | MCP OAuth | Registered OAuth clients idle 30 days are pruned, but only `/authorize` marked a client used: a connector that only refreshes (claude.ai) was deleted around day 30 and its next refresh failed. | Fixed (code exchange and refresh count as use; test fails without the fix) |
| L-35 | Medium | Jobs | In the tick, one user's lease claim failing (statement timeout, user deleted mid-tick) aborted the whole tick (500, later users starved); a failed job kept its lease for 10 minutes. | Fixed (claim/release inside the per-user guard; release in `finally`; test) |
| L-36 | Medium | Postgres / weather | `authenticated` had SELECT+INSERT but not UPDATE on `weather_cells`; refreshing a provisional cell-day failed with "permission denied" on Postgres (reproduced on the local stack) and `enrich_pending` stopped there. | Fixed by migration **0010** (UPDATE on provisional rows only; no DELETE). Needs `catch db upgrade` in production. |
| L-37 | Medium | Duplicates | Retention pruned `match_decisions` at 400 days, including the person's own `not_duplicate`/`split`; matching rescans all history, so an old pair they had separated could auto-merge again. | Fixed (blocking decisions are kept; test) |
| L-38 | **Critical** | Production | **Production runs session 30's code on a database at migration 0008.** Endpoints backed by 0009 tables return 500 — reproduced with a disposable user: `/api/push/subscriptions` 500, `/api/health/status` 500, older endpoints 200. **Account deletion fails (500) for every user**, push device listing and health import are broken. Nothing could see it: the runtime role can't read `alembic_version`, so db-check showed the revision as "unknown". | Open — owner: `catch db upgrade` (B-1). Detection fixed: `db_pg.missing_tables` (no grant needed) → ERROR at public startup + `schema_missing_tables` in `/internal/db-check` (PG test). |
| L-39 | High | Backups (docs) | The documented backup command was `pg_dump -n catch`, which omits `catch_private` and `catch_club` (functions many policies call). | Fixed in docs (all three schemas); drill script uses them |
| L-40 | Medium | Backups | A schema-level dump/restore loses the two triggers on `auth.users` (profile creation and deletion cascade): sign-ups would get no profile and deletion would leave rows. | Documented runbook step (operations-runbook.md §7); `scripts/backup_restore_drill.py` checks and re-creates them |
| L-41 | Medium | Providers | Any 400/401 on a token refresh (Whoop, Concept2) and any non-zero Withings refresh status maps to `needs_reconnect`: a rotated app secret or a provider hiccup flips every user to "reconnect" and sends alerts. | Open (treat only `invalid_grant`-class errors as revocation) |
| L-42 | Low | Ops tooling | `scripts/smoke_public.py` dropped user B from its cleanup list even when deletion failed — it leaked one disposable user in production on 2026-11-20. | Fixed (cleanup unless deletion verified); the leaked `catch-smoke-b-…@example.com` user was deleted (0 smoke users left) |
| L-43 | Low | MCP | `/mcp` tool calls have no per-owner throttle (REST does); `sync_provider` with `manual=True` skips backoff and runs synchronously in the async handler. | Open |
| L-44 | Low | Clubs | `get_my_clubs` and `get_club_challenges` (read tools) can write (`complete_approved`, `refresh_entry`), so a read-scope token causes writes. `club_name`/`author` aren't in the untrusted-text keys. | Open |
| L-45 | Low | Club RLS | Owner can delete a staff-hidden `club_results` row and re-share it; `club_audit` insert policy doesn't constrain `actor_kind`; some `catch_club` predicates take any uid (oracle if the schema were ever exposed — it isn't). | Open (Low; `catch_club` is not exposed) |
| L-46 | Low | Weather | `weather_cells` is a global table readable and insertable by every user: anyone can read cell-days (0.1°, ~11 km) where someone trained and insert fake rows others read. | Open (consider routing writes through `catch_api`) |
| L-47 | Low | OAuth | Unauthenticated dynamic registration is capped at 2000 clients globally with 30-day expiry: one IP can fill the cap in ~3 h, blocking new connectors. | Open |
| L-48 | Low | Credentials | `store_oauth` without a new refresh token re-keys the row while the old refresh blob stays under the previous master key; a later rotation can strand it. `run_sync` returns raw `str(exc)`; Withings error text is stored verbatim. | Open |
| L-49 | Info | Analytics | Day bucketing mixes `astimezone()` (host-local) and UTC `.date()` across modules; the per-user fix (L-09) must route all of them through one helper. | Part of L-09 |

## A. Application audit

### A.1 Routes, API, auth (static, by importing the app's route table)

- Every non-public route is behind `require_auth`, `require_tool_auth`, `require_tool_auth_allow_coach` or `require_tick_secret`;
  the unauthenticated set equals the allow-list in `tests/tenancy/test_route_auth_coverage.py` plus the SPA catch-all. PASS
  (that test ran in the full suite).
- Personal-only routes (cookie login, Whoop/`auth/*/start`) 404 on public; leaderboards/clubs/moderation/OAuth are public-only;
  moderation also needs `require_moderator`. PASS (tests ran).
- `/internal/*` 404s without a tick secret configured and compares with `hmac.compare_digest`. PASS. See L-06.
- OpenAPI/docs are off on public — confirmed in production: `/docs`, `/openapi.json`, `/redoc` return the SPA's `index.html`
  (`text/html`), not the API schema. PASS.
- No file-path parameters; static files go through `safe_static_file`; uploads are size-capped and magic-byte sniffed; raw SQL
  only in `ALLOWED_RAW_SQL` modules; 422s drop echoed input. PASS (tests ran).
- Service-layer owner filtering in `sync/clubs.py`, `leaderboard_store.py`, `privacy.py` relies on RLS (Postgres) + tenant hooks
  (both) — exercised by `tests/pg` (separate identities) and `tests/tenancy/test_idor_sweep.py`. PASS as tested; no line-by-line
  read this session.

### A.2 Models, migrations, jobs, providers, tools

- Models vs migrations:
  - No owned table is missing from the migrations.
  - Every owned table has forced RLS and four policies; club tables have their documented counts.
  - Every SECURITY DEFINER function sets `search_path = ''` and is revoked from PUBLIC/anon.
  - Checked statically, then by `tests/pg/test_migrations.py` on the local stack (PASS).
  - Gap found: L-36, fixed by migration 0010.
- Downgrades are destructive (0009 drops consents and native tokens; 0008 drops deletion tombstones). The runbook says so; prefer
  rolling forward.
- Jobs:
  - The tick authenticates with `hmac.compare_digest`; a per-(user, job) lease; a 240 s budget; users shuffled.
  - Fixed: L-06, L-35, L-37.
  - Open: the budget is checked only between users, and provider calls have no per-user deadline (Info).
- Providers:
  - Credentials are sealed with AES-GCM and AAD `owner|provider:slot`.
  - OAuth state is a signed `HttpOnly` cookie with a constant-time nonce compare.
  - Refresh uses a process lock plus a `FOR UPDATE` row lock.
  - Open: L-41, L-48. Only Whoop supports revocation at the provider (documented in each card).
- Tools:
  - Coach `TOOLS` and the MCP `@mcp.tool` wrappers match 66/66, including schemas; all 22 writes take `confirm`; every write is gated
    centrally (`call_tool`/`_gate`) or in its handler.
  - No tool returns a credential. Club and leaderboard tools are athlete-only and strip `owner_id`/`member_ref`.
  - Open: L-43, L-44.

### A.3 Dead code, placeholders, misleading UI

- No `TODO`/`FIXME`/lorem/"coming soon" in `catch/` or `web/src` (grep). The 85 `placeholder` hits are input attributes and
  React Query `placeholderData`.
- Known functional gap: training intelligence treats nutrition and daily activity as context only
  (`training_intelligence.py:397`, docs/analytics.md). Recorded.
- Misleading UI: L-03, L-04, L-22, L-25, L-32.

## B. Data and analytics validation

Independently hand-computed vectors, each then run against the code (agent review + `tests/analytics/test_launch_hand_calcs.py`):

| Formula | Vector | Result |
|---|---|---|
| Concept2 watts = 2.80/(s/500)³ | 1:45.0 → 302.34 W; 2:00.0 → 202.55 W; 1:40.0 → 350.0 W; 200 W → 2:00.5 | PASS |
| 2k prediction (Paul's law, pace − 5·log₂(d/2000)) | 6k @ 1:50 → 1:42.08; 5k @ 2:00 → 1:53.39; 1k @ 1:30 → 1:35.0 | PASS |
| Banister TRIMP / strain | 60 min @ HRr 0.5 → 50.14; strain 2.54·ln(1+50) = 9.99 | PASS |
| Recovery HRV z-score | history [4,4.2,…], today 4.2 → z 1.155, component 78.87; with 8 h sleep → 85.91 | PASS |
| EWMA load | [0]*41+[100] → acute 25.0, chronic 4.651 | PASS (see L-19) |
| TSS | 1 h @ 200 W, FTP 250 → 64.0 | PASS (see L-20) |
| Nutrition fat target | (2800 − 4·1.8·70 − 4·5·70)/9 = 99.56 g | PASS |
| Piece average split | 3×500 m @105 s + 250 m @52 s → 367/1750×500 = 104.86 s | PASS after L-10 fix (Python + TS tests) |

Topic checks (all from suites that ran in this session, §Evidence):

- Duplicate provider records don't inflate volume — `tests/test_matching_engine.py`, `tests/test_canonical.py`,
  `tests/analytics/test_matching.py`, health-import dedupe tests. PASS.
- Planned workouts never count as completed — `tests/test_planning_sync.py`, `tests/test_api_calendar.py`,
  `tests/coach/test_calendar_tools.py` (incl. the "no completed-total reader imports planning" test). PASS.
- Pieces don't double-count strain — `tests/test_piece_sync.py`, `tests/test_api_piece_intervals.py`, `tests/test_scoring.py`. PASS.
- Time zones / DST — DST day lengths correct (`_local_day_utc_range`: 23 h / 25 h days); per-user zone missing: **FAIL** (L-09, blocker B-2).
- Missing data not treated as zero — was **FAIL** (L-13, L-14, L-16); fixed with tests that fail without the fix. Remaining: L-19 (a session with neither HR nor RPE enters load as 0).
- Units — everything is metric and labelled; the no-op imperial toggle was removed (L-22). L-23 recorded.

Remaining formula limitations are listed in docs/analytics.md "Known limitations (session 31)".

## C. AI and MCP

| Check | Result |
|---|---|
| Anthropic / OpenAI / Gemini adapters: streaming, tool calls, normalised errors (`invalid_key`, `rate_limited`, `quota`, `unavailable`, `timeout`) | PASS (synthetic fixtures: `tests/coach/test_provider_*.py`, `test_chat_byok.py`) |
| Ollama | personal only; startup refuses it on public. PASS (mocked) |
| Switching provider and replacing a key keeps conversation history; a rejected key never replaces a working one; another owner can't replace or delete it; no env fallback; key never logged | PASS (`tests/test_ai_credentials.py`, `test_ai_no_leak.py`, `test_secret_rotation.py`) |
| **Live** BYOK calls with real Anthropic/OpenAI/Gemini keys | **NOT VERIFIED.** No keys in this session (B-14). Owner: Settings → AI providers → Test, for each provider |
| MCP over the **remote Streamable HTTP endpoint on FastAPI Cloud with Supabase identity** | **PASS.** The owner's claude.ai connector (OAuth) returned the owner's own connections; `create_event` without `confirm` returned `saved: false` with a preview, and nothing was saved. Production smoke: MCP initialize, 66 tools listed (stateless), a read as user A, a read-scope token refused a confirmed write, `/mcp` without a token returns 401 with RFC 9728 metadata |
| MCP stdio (`catch-mcp`) | **PASS** `scripts/mcp_stdio_check.py` 7/7 (new; there was no automated stdio test before) |
| OAuth: PKCE, rotation, replay → whole grant revoked, resource binding, scopes, revoke, end-all, pruning | PASS (`tests/tenancy/test_mcp_oauth.py`, 40 tests incl. L-34) |
| Write tools require confirmation; read scope can't write | PASS (`tests/coach/test_tool_safety.py`, `tests/test_token_scopes.py`, production smoke) |
| No client can read another user's records | PASS (`tests/tenancy/test_coach_turn.py`, `test_idor_sweep.py`, `test_mcp_principal.py`, `tests/pg`), and in production (smoke: user B can't see A's note or tokens) |
| ChatGPT custom connector, Gemini API, Gemini CLI | **NOT VERIFIED** (no accounts, B-15). Setup and limits from vendor docs in docs/mcp-client-setup.md |

## D. Providers

| Check | Result |
|---|---|
| Garmin with **approved** Catch developer access | **NOT POSSIBLE.** Catch has no Garmin developer-program approval; it uses each user's Personal API key (B-6). The owner's own key syncs in production (`last_success` 2026-11-20 15:07 UTC). |
| Withings OAuth + refresh | **FAIL in production** (L-33, HMAC). Mocked flow PASS (`tests/test_withings_client.py`, `test_connections.py`). Live OAuth for a new user NOT VERIFIED |
| Concept2 authorization + result sync | Owner's personal-token connection syncs in production; OAuth NOT VERIFIED live; mocked PASS |
| Whoop OAuth + sync (rotating refresh tokens) | mocked PASS (`tests/test_whoop_client.py`); live NOT VERIFIED |
| Disconnect / reconnect; credentials deleted; imported data kept | PASS (mocked + tenancy tests) |
| Rate limits and backoff (`Retry-After`, 5 min…6 h) | PASS (tests); see L-41 for the over-eager reconnect mapping |
| Credentials and records isolated per user | PASS (`tests/tenancy/test_provider_connections.py`, `tests/pg`) |

## E. Supabase

Full table: [supabase-setup.md](supabase-setup.md). In short:

- **Production migrations are not current** (L-38, Critical).
- RLS is forced on 89/89 Catch tables. Policies were tested with separate GoTrue identities for select/insert/update/delete
  (`tests/pg`: PASS on HEAD).
- The runtime role is non-bypass. The secret key is used only for the GoTrue admin delete and the Storage purge.
- Session pooler on 5432. 40-concurrent local load peaked at 3 runtime connections with no errors; production took a 40-concurrent
  burst cleanly.
- The Storage bucket is private with per-uid policies.
- Account deletion removes rows and media on the local stack (PASS) and **fails in production** until B-1.
- **Production has no backups** (B-3). The local restore drill passes 15/15 (L-39, L-40).
- No production secret is in any frontend build (web and native scans clean).

## F. FastAPI Cloud (production, unauthenticated checks run 2026-11-20)

| Check | Result |
|---|---|
| HTTPS, certificate | PASS — Google Trust Services WE1, valid to 2027-02-13 |
| http → https | PASS — 301 |
| HSTS | PASS — `max-age=31536000; includeSubDomains` |
| CSP / frame / nosniff / referrer / permissions | PASS — hash-based `script-src`, `x-frame-options: DENY`, `nosniff`, `strict-origin-when-cross-origin`, `camera=(self), geolocation=(), microphone=()` |
| `/api/health` | PASS — 200 `{"ok":true}`, `cache-control: no-store` |
| `/mcp` unauthenticated | PASS — 401 with `WWW-Authenticate: Bearer resource_metadata=…/.well-known/oauth-protected-resource/mcp` |
| OAuth metadata | PASS — RFC 9728 resource metadata and RFC 8414 AS metadata served, scopes `catch:read`/`catch:write` |
| `/internal/db-check`, `/internal/config-check` without secret | PASS — 401 |
| API docs exposed | PASS — not exposed (SPA fallback) |

## G. Security and privacy

| Check | Result |
|---|---|
| Secret scan | PASS: gitleaks v8.30.1, git mode, 150 commits, "no leaks found". (A `dir` scan flags only gitignored `.env`/`*.local` files and allowlisted fixtures, because dir mode prefixes paths with `/repo/`; the native `.local` files hold only the publishable key and URLs.) |
| Dependencies | PASS: `pip-audit` over the 330 locked requirements, "No known vulnerabilities found"; `npm audit --omit=dev --audit-level=high`, 0 vulnerabilities |
| Authorization / cross-user isolation | PASS (§A.1, §C, `tests/pg`, production smoke) |
| Uploads and images | PASS: body limits plus magic bytes (`core/uploads.py`, `test_hardening.py`); photos not stored after estimate; piece photos in the private bucket |
| Rate limits and abuse | Partly. L-06 fixed; L-27, L-29, L-43, L-47 open; F-08 (per replica) and F-30 (shared proxy addresses) remain |
| Logging and error responses | PASS (`test_log_hygiene.py`; 422s drop input; no stack traces); L-30 recorded |
| Account export and deletion | Export PASS (tests). Deletion PASS locally, **FAIL in production** (L-38) |
| Provider disconnection removes credentials | PASS (tests) |
| Public profiles and leaderboards | PASS (tests); L-05 fixed |
| Club permissions and moderation | PASS (tests, plus the PG matrix test); L-44, L-45 Low open |
| Critical/High resolved before launch | **No.** L-38 (Critical, owner action), L-09 (High, code), L-25/F-18 (High, legal), L-33 (High, deploy) |

## H. Performance and reliability

- **Frontend bundle:** initial JS 230.0 KB gzip (budget 250 KB); every route lazy-loaded.
- **Backend, local** (laptop, single uvicorn worker, local Supabase; `scripts/load_local.py`; 20 users × 3 years: 21,900 activities and
  21,900 wellness days):
  - Sequential warm p50: `/api/me` 4 ms, `/api/today` 27 ms, `/api/activities?limit=50` 8 ms, `/api/trends` 14 ms, `/api/series`
    5 ms, `/api/wellness` (unbounded, L-28) 44 ms, `/api/predict/2k` 14 ms, `/api/calendar` 15 ms, `/api/status` 24 ms.
  - 40 concurrent: 360 requests, all 200, p50 489 ms, p95 637 ms, p99 711 ms, peak 3 `catch_api` connections.
  - These are not production numbers.
- **Production:** 120 requests at 40 concurrency, all 200 in 3.3 s (smoke).
- **Tick with many users:** covered by `tests/pg/test_runtime.py` (every user under their own identity, leases prevent double runs)
  and L-35. Not measured in production.
- **Backup and restore:** local drill PASS; production FAIL (no backups).
- **Rollback:** NOT VERIFIED (not authorised).
- **Monitoring and alerts:** none configured (B-8).
- **Supabase resource limits:** Free-plan limits apply (pause on inactivity, connection caps). Owner decision (B-3).
- **Personal Pi build:** the whole suite runs in personal mode (PASS), the personal production build and `test:gym` (real personal
  app) PASS. Not run on Pi hardware (the Pi is being wiped).

## I. UX and accessibility

- Automated: the Playwright touch suite (iPhone-profile Chromium with real multi-touch, real WebKit, desktop mouse; 257 passed).
  It includes keyboard reachability for the privacy controls and the existing `aria`/role selectors.
- This session did not add an automated contrast or axe audit, and did no screen-reader pass: **NOT VERIFIED**. Owner: a manual
  VoiceOver/TalkBack pass plus an axe run before launch.
- Misleading UI fixed: L-03 (`?mock=1` on the real site), L-04 (fake zero stats), L-22 (units toggle), L-32 (unavailable sources,
  public-only routes on personal).
- Still misleading:
  - L-25: legal drafts with placeholders shown publicly.
  - The production deletion button fails (L-38).
- Disconnected and empty states: Status, Connections, offline banner and coach "not configured" paths are covered by the touch
  suite's mock scenarios (`?mock=empty|error|offline`).
- Features are hidden when their configuration is missing:
  - Garmin when BYOK is off.
  - Push on unsupported platforms.
  - Native-only pages on the web.
  - Photo features with no vision-capable key (`useVisionAvailable`).

## Blockers

| ID | Sev | Blocker | Owner | Next action |
|---|---|---|---|---|
| B-1 | **Critical** | Production database at 0008 under 0009 code; account deletion, push device list and health status return 500 (L-38) | Operator | `DATABASE_ADMIN_URL=… uv run catch db upgrade` (to 0010 once this branch is merged), deploy, then check `/internal/db-check` `schema_missing_tables: []` and run `scripts/smoke_public.py`: all PASS |
| B-2 | High | No per-user time zone: days, "today" and check-ins are wrong for anyone not in the server's zone (L-09) | Developer | Design session: `user_profiles.timezone` (browser-detected, editable), migration, one `local_day(ts, tz)` helper used by every bucketing site incl. the UTC `.date()` ones, web date defaults, backfill/recompute |
| B-3 | High | No backups: Supabase Free, no PITR, no dump ever taken | Operator | Upgrade to Pro (7 daily backups) or schedule `pg_dump -n catch -n catch_private -n catch_club` off-project; run `scripts/backup_restore_drill.py`-style restore of a real dump into a scratch stack |
| B-4 | High | Legal documents are unreviewed drafts with placeholders, rendered publicly (F-18, L-25) | Operator + counsel | Counsel review; fill controller/contact details; remove counsel notes; then ship |
| B-5 | High | No custom SMTP: sign-up confirmation and password recovery limited to ~2 emails/hour; never verified end to end | Operator | Configure SMTP (SPF/DKIM), run `npm run test:live` locally and a real sign-up on production |
| B-6 | High | Garmin: no developer-program approval; public BYOK conflicts with Garmin's stated intent (L-26) | Operator | Decide: `CATCH_GARMIN_BYOK_ENABLED=0` for launch, or obtain Garmin approval / legal sign-off; set the variable explicitly either way |
| B-7 | High | F-02 residual (write confirmation over MCP/REST is client-mediated) needs written acceptance | Operator | Accept in docs/security-findings.md, or require a server-side two-step token |
| B-8 | Medium | No monitoring or alerting (uptime, tick failures, error rate) | Operator | External uptime check on `/api/health`; a daily check of `cron.job_run_details`; log-based alert on `database is behind this build` |
| B-9 | High (ops) | Production Withings failing (HMAC) since 2026-11-20 (L-33) | Operator | Deploy this branch (`bf3848e`); confirm the next Withings sync; re-enter the secret if not |
| B-10 | Medium | Supabase Auth dashboard settings unverified (F-17): password policy, MFA + moderator enrolment, CAPTCHA/rate limits, redirect URLs | Operator | Set and screenshot/record them in supabase-setup.md |
| B-11 | Critical→verify | F-38 `catch_api` password rotation owner-reported, not independently verified; connection logs for the exposure window unreviewed | Operator | Review Supabase connection logs; confirm the old password fails |
| B-12 | High (stores) | Mobile: Apple/Google/Firebase accounts, Android release signing, min-version mechanism, device-only checks (APNs/FCM, links, HealthKit/Health Connect) | Operator | Only blocks store submission, not a web launch: docs/mobile/release.md |
| B-13 | High | No live verification of any provider OAuth flow (Withings, Concept2 OAuth, Whoop) for a non-owner account | Operator | Connect each with a test account on production; record results in provider docs |
| B-14 | Medium | No live BYOK call with real Anthropic/OpenAI/Gemini keys | Operator | Settings → AI providers → Test, per provider, then one coach turn each |
| B-15 | Low | ChatGPT / Gemini MCP clients untested | Operator | Follow docs/mcp-client-setup.md with an eligible account |
| B-16 | Medium | L-41 (over-eager needs-reconnect), L-27/L-29/L-43 (abuse limits), L-44 (read tools write) | Developer | Next hardening session |

## Evidence

All runs on 2026-11-20, branch `session-31-launch-audit`, against the final head unless stated otherwise.

| Suite | Command | Result |
|---|---|---|
| Lint | `uv run ruff check .` | All checks passed |
| Backend (SQLite, personal default) | `CATCH_DEPLOYMENT=personal uv run pytest --ignore=tests/pg` | **2209 passed, 3 skipped** |
| Postgres / Supabase (real GoTrue, RLS with separate identities, Storage, pooler, runtime path) | `tests/pg` against the local `supabase start` stack | **100 passed, 1 skipped** |
| Whole backend suite on PostgreSQL | `CATCH_TEST_PG_URL=… pytest --ignore=tests/pg` | **2211 passed, 1 skipped** |
| Frontend unit | `npm test` (vitest) | **95 passed** (13 files) |
| Frontend typecheck, lint, production build, bundle budget, build-secret scan | `npm run typecheck && lint && build && check:bundle-size && check:build-secrets` | pass; initial JS **230.0 KB gzip** (budget 250); 110 files clean |
| Playwright touch/WebKit/desktop vs the production preview | `CI=1 npx playwright test` | full run: 244 passed, **13 failed by timeout** while the machine's load average was 138 (a backup daemon and Spotlight, not Catch). Those 13 re-run with `--last-failed --workers=2`: **13 passed**. An earlier full run in this session (before the last piece-split change) passed 257, with 8 skipped |

Earlier in the session:
- Production smoke (`scripts/smoke_public.py`, disposable users) ran on the session-30 production deploy: 28 passed, 3 failed
  (account deletion 500), 1 skipped (no tick secret). The diagnostic probe with a disposable user found `/api/push/subscriptions` 500
  and `/api/health/status` 500 against `/api/me` and `/api/privacy/summary` 200. Leaked smoke user removed; 0 `catch-smoke-*` users
  remain.
- Production curl checks: §F.
- Owner's claude.ai MCP connector: `get_connected_providers`, `get_sync_status`, and `create_event` without `confirm` (preview only).
- `test:public` 18 passed, `test:update` 4 passed, `test:gym` 1 passed (after the UI fixes).
- Native: `CATCH_NATIVE_ENV=production npm run native:sync`, `check:native-secrets` ("343 files clean across 3 directories"),
  `./gradlew assembleProdDebug assembleDevDebug` (BUILD SUCCESSFUL, JDK 21), `xcodebuild … generic/platform=iOS Simulator`
  (BUILD SUCCEEDED).
- Public production bundle served locally and loaded with `/?mock=1` showed the sign-in form (2 inputs); a public production build
  with `VITE_CATCH_ALLOW_MOCK=1` is refused.
- `scripts/mcp_stdio_check.py` 7/7, `scripts/load_local.py` (numbers in §H), `scripts/backup_restore_drill.py` 15/15.
- Security: gitleaks (git mode) no leaks; pip-audit 0; npm audit 0.

Not run, deliberately and stated as such:
- `npm run test:live` (needs the local stack reconfigured for email confirmations).
- The Android emulator e2e.
- Any live provider or AI-provider call.
- ChatGPT/Gemini clients.
- Production `/internal/*` (tick secret not provided).
- Production backup, deploy and rollback (not authorised).
- A screen-reader or axe pass.
