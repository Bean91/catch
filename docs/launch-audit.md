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
| L-10 | Medium | Analytics | `piece.aggregate_from_splits` averages split *times* unweighted although its docstring says time-weighted (500 m@100 s + 600 m@60 s → 80.0 s/500 m; correct 133.3). `piece_intervals._weighted` does it right, so the two disagree. | see §B |
| L-11 | Low | Analytics | `piece.validate_splits` assumes 500 m when a split row has no distance, so a timed piece with typed watts gets a false "implied watts" warning. | Recorded |
| L-12 | Low | Analytics | `piece.find_best_window` has no coverage gate: a window with one real sample and nine gaps can win auto-align. | Recorded |
| L-13 | Medium | Analytics / missing data | `strain.daily_activity_strain` averages a missing kcal in as 0 (`scoring.py` passes `active_kcal or 0.0`). | see §B |
| L-14 | Medium | Nutrition / missing data | Under-fuelling flag includes **today's partial day** (today's Garmin `total_kcal` still accumulating); `_trailing_kcal_target` already excludes today for this reason. Foods with `kcal_100g=None` count as 0 kcal on a day marked as logged → phantom deficit. | see §B |
| L-15 | Low | Nutrition / DST | `copy_day_logs` shifts UTC timestamps by N×24 h, so the local time drifts an hour across a DST change. | Recorded (subsumed by L-09) |
| L-16 | Medium | Recovery / missing data | After 7 HRV nights, a day with **no wellness row at all** still scores (e.g. 50, yellow) from prior-day strain alone. RHR has no minimum-history gate or SD floor (`illness.py` floors at 1.5). | see §B |
| L-17 | Low | Strength | `epley_e1rm(100, 1)` = 103.3 though the docstring says a single returns the weight; reps capped at 10 make a 20-rep set an e1RM floor PR detection treats as real. `normalize_muscle_au` clamps rather than normalises. | see §B |
| L-18 | Low | PBs | `_PB_DISTANCES_M` tolerance `max(25 m, 2 %)`: 475 m counts as a 500 m PB and a 1960 m/400 s piece beats a 2000 m/405 s one. `erg_test.detect_test_type` uses a tighter tolerance; the two disagree. | Recorded |
| L-19 | Info | Load | `load.py` EWMA uses λ = 2/(N+1) (Williams), about 2× faster than Coggan's 1−e^(−1/τ); not comparable to other apps' ATL/CTL. No minimum history for ACR. Sessions with neither HR nor RPE enter load as 0 (same as a rest day). | Recorded (docs/analytics.md) |
| L-20 | Info | Cycling | `cycling_load` docstring claims TSS ≈ TRIMP; one hour at HRr 0.8 is TRIMP ~143 vs TSS 100, so cycling strain is under-weighted ~1.4–2×. Average power, not NP. | Recorded |
| L-21 | Low | Planning | `workload_change_flags` compares against `max(ref)`, so a +16 % planned week can hide a +133 % leap over actual training (docs §29 describe the same rule). | Recorded |
| L-22 | Medium | Web / misleading UI | Settings offers **metric / imperial units**, but nothing reads the setting: the toggle does nothing. | see §I |
| L-23 | Low | Web | Two `formatDistance` functions ("2,000m" vs "2 km"); `formatTimeTenths(-5)` → "-1:55.0" (latent); `predicted_2k` means s/500 m on Today but total seconds in `/api/series` (both rendered correctly today). | Recorded |
| L-24 | Low | Concept2 | `concept2_client.py:183` assumes UTC when a result has neither `date_utc` nor `timezone`. | Recorded |
| L-25 | **High** | Legal / UI | The unreviewed legal drafts are bundled and rendered at `/legal/*` and `/account-deletion` (also signed out) with "DRAFT — NOT LEGALLY REVIEWED", "Contact: [to be filled in]", counsel notes. Same root as F-18. | Open — launch blocker (owner + counsel). Not edited here: inventing legal text or a contact address would be worse. |
| L-26 | Medium | Garmin | `CATCH_GARMIN_BYOK_ENABLED` defaults to `1`; a public deploy that forgets it offers Garmin BYOK, which Garmin's own wording ("not intended for commercial applications serving multiple end users") puts in doubt. The owner's production Garmin uses BYOK today, so the default was **not** flipped. | Accepted? — owner decision (blocker B-6); startup warning added, see §G |
| L-27 | Medium | Abuse | Open Food Facts limiters are process-global (15/min barcode, 10/min search) while a user may make 30/min: one user can exhaust everyone's lookups, which then fail open as "not found". Barcode unvalidated (fixed host, no SSRF); `_miss_cache` unbounded. | see §G |
| L-28 | Medium | Performance | Several reads return the whole history when `from`/`to` are omitted (`/api/wellness`, `/api/checkins`, `/api/body`, `/api/coach/conversations` + messages). `/api/activities` and leaderboards paginate. | Recorded (measured in §H) |
| L-29 | Medium | Abuse | No per-user row/size quotas beyond the 2 MB body cap: note text unbounded, manual `weight_kg` unranged, each write recomputes scores inline; `PUT /api/settings` can trigger a full-history recompute with no rate limit. | Recorded |
| L-30 | Low | Errors | A few handlers return `detail=str(exc)` for `ValueError`/`KeyError` (`routes_coach.py`, `routes_oauth.py`, `routes_analytics.py`, `routes_calendar.py`): parse messages can reach the client. No stack traces. | Recorded |
| L-31 | Low | MCP | `/mcp` principal lookup does blocking DB calls inside the async ASGI `__call__`. | Recorded |
| L-32 | Low | Web | Settings' "Connected sources" lists Garmin even when unavailable. `/clubs` and `/leaderboards` routes exist in personal builds (only the nav link hidden) and show error states. The Coach chat box is enabled with no AI key. | see §I |
| L-33 | **High** (ops) | Withings (production) | Production Withings sync has failed 8× in a row since 2026-11-20 00:37 UTC: `getnonce failed … Invalid HMAC signature` (read via the owner's MCP `get_sync_status`). Matches the newline-terminated-secret bug fixed in `bf3848e` (not yet deployed). | Open — owner: deploy, then confirm the next Withings sync succeeds; if not, re-enter the secret. |

DB/RLS/jobs/provider/tool review findings: §A.2.

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

_Pending the DB/RLS/jobs/providers/tools review; filled in below before commit._

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
| Piece average split | 500 m@100 s + 600 m@60 s → expected 133.3 s | see L-10 |

Topic checks (all from suites that ran in this session, §Evidence):

- Duplicate provider records don't inflate volume — `tests/test_matching_engine.py`, `tests/test_canonical.py`,
  `tests/analytics/test_matching.py`, health-import dedupe tests. PASS.
- Planned workouts never count as completed — `tests/test_planning_sync.py`, `tests/test_api_calendar.py`,
  `tests/coach/test_calendar_tools.py` (incl. the "no completed-total reader imports planning" test). PASS.
- Pieces don't double-count strain — `tests/test_piece_sync.py`, `tests/test_api_piece_intervals.py`, `tests/test_scoring.py`. PASS.
- Time zones / DST — DST day lengths correct; per-user zone missing: **FAIL** (L-09).
- Missing data not treated as zero — **FAIL** before this session's fixes (L-13, L-14, L-16); see status column.
- Units — **FAIL** (L-22 toggle does nothing); everything is metric and labelled.

Remaining formula limitations are listed in docs/analytics.md "Known limitations (session 31)".

## C. AI and MCP

_Filled in below._

## D. Providers

_Filled in below._

## E. Supabase

_Filled in below._

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

## G–I

_Filled in below._

## Blockers

_Filled in below._

## Evidence

_Filled in below._
