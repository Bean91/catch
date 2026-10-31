# Catch — build plan

Self-hosted, single-user rowing training app. Whoop-style recovery/strain from Garmin +
Withings + Concept2, with an AI coach later. Runs 24/7 on a Raspberry Pi 3 (1GB RAM, ARM)
alongside PiAware.

## Roadmap (6 sessions)

1. Scaffold + Garmin + Withings sync
2. Concept2 sync + rowing analytics engine
3. Design system + Today screen
4. **Workout detail, trends, body comp, settings, installable PWA** ← this session
5. AI coach chat (bring-your-own Anthropic key) + MCP server
6. Deploy to the Pi 3, backups, optional Whoop

## Session 1 checklist

- [x] Fetch Garmin's real swagger spec (extracted from the JS bundle — the page itself is
      client-rendered) → `docs/garmin-openapi.json` + `docs/garmin-endpoints.md`
- [x] Scrape Withings' real OAuth2 + measure docs → `docs/withings-endpoints.md`
- [x] PLAN.md + CLAUDE.md
- [x] Data model (SQLModel): `daily_wellness`, `activities`, `strokes`, `body_comp`,
      `sync_state`, `oauth_tokens`, `notes`
- [x] Garmin client: token exchange + cache + re-exchange, activity list + FIT download,
      daily health range calls, backfill — **live-verified**, see below
- [x] Withings client: HMAC-signed OAuth2 (not the old client-secret-in-body flow — see
      `docs/withings-endpoints.md`), `/auth/withings/start` + `/callback`, token refresh
      with rotation, `getmeas` sync — **implemented, not live-verified** (needs a browser
      to finish OAuth; see "Completing the OAuth flow manually" in
      `docs/withings-endpoints.md`). The two unverified pieces: the signed `requesttoken`
      call with no `client_secret` in the body (locked in by a unit test asserting its
      absence, but never exercised against the real Withings servers), and meastype codes
      8/76/77 (fat mass/muscle/hydration — 1/6/88 are confirmed, see
      `docs/withings-endpoints.md`).
- [x] Scheduler: every 2h + jitter, `POST /api/sync/{source}`, `GET /api/sync/status`
- [x] Read endpoints: `/api/wellness`, `/api/activities`, `/api/activities/{id}`, `/api/body`
      (all with `from`/`to`), argon2 session login
- [x] CLI: `uv run catch sync --source garmin --days 30`, `uv run catch backfill`
- [x] Tests on recorded fixtures (no live calls in the suite) — 21 passing
- [x] One live sync against the real `.env`, results shown to the user — Garmin only; see
      below. Withings needs the manual browser OAuth step above before it can sync.
- [x] git init + commit

## Live sync results (2026-10-31, real `.env`, real Garmin account)

`uv run catch sync --source garmin --days 30`, run twice in separate processes:

- Both runs: `93 daily_wellness rows, 34 activities` (93 = 31 days × 3 source calls per day,
  not 93 distinct days — the count is "metric upserts," not unique rows; 31 unique
  `daily_wellness` dates actually exist, confirmed by querying the DB directly).
- Second run produced identical counts — confirms upserts are idempotent and the cached
  Garmin token was read back from SQLite correctly in a brand-new process (the thing most
  likely to break: a naive/aware datetime mismatch on the cached `expires_at`).
- All 34 activities have a real `fit_path` under `data/fit/*.fit` (40KB–227KB each,
  non-empty, zip cleaned up after extraction). Sample: `rowing_v2` activities with real
  duration/calories/avg HR.
- Sample `daily_wellness` row (2026-10-01): `resting_hr=49, stress=25, body_battery=45,
  spo2=97.0, respiration=13.0, sleep_score=90, hrv_rmssd=66.0` — every task-specified field
  populated with a real value, nothing silently null.
- `uv run catch backfill --days 5`: Garmin side worked; Withings failed with the intended
  clear message (`No Withings tokens stored — visit /auth/withings/start first`) since OAuth
  hasn't been completed yet.

## Bugs an advisor review caught before commit (fixed)

- `/api/activities` and `/api/body`'s `from`/`to` query params parsed to naive datetimes,
  which the `UTCDateTime` column type rejects — would have 500'd on first real use. Fixed
  with an `as_utc()` helper in `catch/api/deps.py`; added regression tests.
- FIT extraction read the whole file into memory (`src.read()`) instead of streaming, which
  is one of the task's explicit rules on this box. Fixed with `shutil.copyfileobj`.
- First PII redaction pass on the Garmin fixtures missed `endLatitude`/`endLongitude`,
  `deviceId`, and `profileImageUrl*` — caught on a second, broader grep before committing.

## Gotchas / deviations from the literal task spec

- **`daily_wellness` sleep stages**: expanded to `deep_sleep_seconds`, `light_sleep_seconds`,
  `rem_sleep_seconds`, `awake_sleep_seconds` (the task said "sleep stages" plural without
  naming columns). Everything else in `daily_wellness` matches the task's literal single
  columns — `v2/dailysummaries`' real (nested) response shape, confirmed against a live
  call, turned out to carry a genuine single `body_battery` number (`bodyBattery.latestValue`)
  and whole-day `spo2`/`respiration` (`pulseOx.avgValue`/`respiration.avgValue`), so no
  splitting or sleep-period fallback was needed after all.
- **`hrv_rmssd`** is Garmin's `hrvSummary.lastNightAvg` as-is. The API doesn't label it
  rMSSD explicitly; that's the closest available nightly HRV number.
- **Withings signing**: the current public docs require HMAC-signed `requesttoken` calls
  (nonce from `/v2/signature`), not the older "send `client_secret` in the token POST body"
  flow many tutorials describe. Implemented the signed version. If Garmin's or Withings'
  live behavior disagrees with the docs once we test against real credentials, the live
  response wins — update the docs files, not just the code.
- **Garmin token-exchange response is a raw JWT as `text/plain`**, not a JSON envelope —
  confirmed against a live call. We decode the JWT's `exp` claim for expiry instead of
  looking for an `expires_in` field (there isn't one).
- `strokes` table exists (schema only) but stays empty this session — Concept2 is session 2.
- Added `uvicorn` and `argon2-cffi` to the stack (approved by user) — FastAPI needs an ASGI
  server, and the existing `.env` password hash is already `$argon2id$`, which the plain
  `cryptography` package can't verify.

## Session 2 checklist

- [x] Concept2 Logbook API client (`catch/sync/concept2_client.py`): long-lived personal
      access token as a static bearer token (no exchange/refresh, unlike Garmin/Withings),
      list results since last sync, fetch per-result detail with `?include=strokes,metadata`,
      upsert into `activities`/`strokes` (drag factor, workout type, intervals/splits JSON,
      stroke rate kept). `docs/concept2-endpoints.md` written from the live API docs.
- [x] De-dup against Garmin: `link_garmin_activity` links a Concept2 result to a Garmin
      `rowing_v2`/`indoor_rowing` activity within a 2-minute window (both sides get
      `linked_activity_id`); Concept2 stays the source of truth for erg metrics, Garmin's
      avg/max HR is copied in only when Concept2 has none. `relink_unmatched` (called at the
      top of every `recompute_scores`) catches pairs where Concept2 synced before Garmin did
      — linking only at insert time would otherwise double-count that session in strain/load
      forever, since Concept2's `updated_after` cursor has already moved past it.
- [x] Scheduler + CLI: `concept2` added to `SOURCES`/`uv run catch sync --source concept2`;
      `cli.cmd_sync` now routes through `scheduler.run_sync` instead of duplicating it.
- [x] Lightweight SQLite migration (`catch/core/db.py`): `activities`/`strokes` got new
      nullable columns via `ALTER TABLE` (not just `create_all`, which only makes missing
      tables) — needed since session 1 already shipped a live `activities` table with real
      data in it.
- [x] Analytics engine (`catch/analytics/`, pure functions, no I/O) — erg math, 2k prediction
      (Paul's law), training zones (HR- and power-based), session strain (Banister TRIMP /
      sRPE fallback, mapped to a 0-21 Whoop-style log-saturation scale), load (7d/42d EWMA,
      form, acute:chronic bands), recovery (0-100%, HRV/RHR/sleep/prior-strain, "calibrating"
      before 7 nights of HRV history), erg technique per piece (split consistency, watts/
      stroke, rate-power slope, fade). All formulas + sources in `docs/analytics.md`.
- [x] Configurable thresholds: singleton `settings` table (JSON blob of overrides merged onto
      `catch/analytics/defaults.py` at read time) via `catch/core/settings_store.py`,
      `GET`/`PUT /api/settings` (unknown keys rejected, `PUT` triggers a recompute so
      `/api/today` doesn't go stale until the next sync).
- [x] `catch/sync/scoring.py`: the one place that reads the DB, builds analytics functions'
      inputs, and caches results into `daily_scores` — runs after every sync/backfill/settings
      change, recomputing full history each time (cheap at single-user scale, avoids staleness
      bugs). A linked Garmin<->Concept2 pair is only scored once (the Concept2 side). Days are
      bucketed by the **system's local calendar date** — only correct if the Pi's timezone is
      set to the athlete's own.
- [x] Endpoints: `GET /api/today`, `GET /api/trends?metric=...` (whitelisted), `GET
      /api/erg/results` (includes nearest-Withings-weight `w_per_kg` per row), `GET
      /api/erg/{id}/strokes` (raw strokes + per-interval technique + time-in-zone),
      `GET`/`PUT /api/settings`.
- [x] Tests: fixture-based Concept2 client tests (8), analytics unit tests with hand-checked
      numbers (37, across `tests/analytics/`), scoring pipeline tests (5), settings-store
      tests (5), API endpoint tests (15) — 90 total, all passing.
- [x] One live sync against the real `.env`/Concept2 account, migration verified against the
      live (non-empty) DB from session 1.
- [x] PLAN.md + commit.

## Live Concept2 check (2026-10-31, real `.env`, real Concept2 account)

`GET /api/users/me` succeeded (confirms the access token and base URL): real profile came
back with `max_heart_rate: 194`, `weight: 7900` decigrams (79.0kg). **This Concept2 account
has zero logged results** (`GET /api/users/me/results` returned `total: 0`) — there was
nothing to record a fixture from, so `tests/fixtures/concept2/*.json` are synthetic, built
directly from the documented request/response examples (same approach session 1 used for
Withings, whose OAuth also couldn't be completed live). The result/stroke JSON shapes are
therefore unverified against a real result — revisit if Concept2 ever disagrees with the docs
once real results exist.

`uv run catch sync --source concept2 --days 30` against the real `.env`, run against the
**live, non-empty DB from session 1** (34 Garmin activities, real FIT files):
- The `activities`/`strokes` schema migration applied cleanly to the existing SQLite file —
  all 34 Garmin activities and their `fit_path`s came through untouched afterward.
- `settings.max_hr` was seeded to `194` from the live Concept2 profile (confirms
  `_seed_max_hr`).
- `recompute_scores` produced 31 `daily_scores` rows from the real Garmin/Withings-less
  history, with plausible recovery bands (yellow, mid-50s) and strain values (TRIMP-based,
  "moderate"/"light"/"light" for the three most recent rowing days) — a reasonable sanity
  check that the whole pipeline holds together against real data, not just fixtures.
- `uv run catch backfill --days 5`: Garmin and Concept2 both ran cleanly; Withings failed with
  the same pre-existing, expected message from session 1 (OAuth not completed).

**The Concept2 access token leaked into this session's shell output once** (an early `grep`
printed the raw `.env` value, violating CLAUDE.md's "key names only" rule) — the user was told
to rotate it under Logbook > Edit Profile > Applications.

## Gotchas / deviations from the literal task spec

- **W/kg** uses the nearest `body_comp` (Withings) row to an activity's start, not a fixed
  profile weight — returns `None` until Withings OAuth is completed (still true as of this
  session).
- **2k prediction** only draws from continuous workout types (`JustRow`/`FixedDistanceSplits`/
  `FixedTimeSplits`/no `workout_type`) within a configurable `predict_lookback_days` (default
  180) — interval/piece sets mix work+rest into `Activity.duration` while `distance` stays
  work-only, which would corrupt the pace Paul's law needs.
- **Time in zone** only works for sessions with per-sample HR, which today means Concept2
  strokes only (Garmin has no sample-level HR without parsing the FIT file — a new dependency,
  out of scope this session).
- **Session RPE** is attached to a session by matching `notes.date` to the session's local
  calendar date — the schema has no per-activity RPE field, so two sessions on the same day
  both get that day's single RPE value.
- A Concept2 `date` with neither `date_utc` nor a `timezone` name falls back to treating it as
  UTC — a documented guess, unconfirmed since no live result exists yet to check it against.

## Session 3 checklist

- [x] Two visual directions proposed and one picked with reasoning — "Boathouse Mono"
      (tabular-numeral mono for every data value, one indigo-violet accent chosen
      specifically to avoid colliding with the yellow recovery band) over "Regatta Sans".
      Full rationale and the validated palette (every pairing checked against WCAG AA
      with a contrast script, not eyeballed) in `DESIGN.md`; tokens as CSS vars in
      `web/src/styles/tokens.css`.
- [x] `GET /api/today` extended for the Today screen's needs: `sleep_last_night` now
      carries stage seconds + `need_seconds`, a new `strain_targets` setting (keyed by
      recovery band, in `catch/analytics/defaults.py`) drives `strain_target_range`,
      `hrv`/`resting_hr` each carry a 14-day sparkline and a `baseline_band` reused
      straight from `recovery_score`'s own `baseline_7d*`/`spread_60d` (not re-derived in
      TS), and `latest_erg`/`predicted_2k` are embedded so Today needs exactly one call.
      Documented in `docs/analytics.md` §8; covered by a new test in
      `tests/test_api_analytics.py`; `uv run pytest` — 93 passed (includes
      `tests/test_main_static.py`, added for the path-traversal fix below).
- [x] `catch/main.py` now mounts `catch/api/static` (Vite's `outDir`) with an SPA fallback,
      registered after every API router so it can't shadow `/api/*`/`/auth/*`; a no-op
      when the directory doesn't exist (dev/test run without a build).
- [x] React + Vite + TS scaffold in `web/`: Tailwind v4 (CSS-first, tokens mapped via
      `@theme`), Radix (`Dialog` for the recovery breakdown), Framer Motion (once-only
      arc/count-up/sparkline-draw animations, all gated on `prefers-reduced-motion`),
      TanStack Query, React Router. Fonts self-hosted via `@fontsource` (latin subset
      only) rather than a Google Fonts runtime dependency — this app is self-hosted and
      often offline on the Pi's LAN.
- [x] Today screen: recovery ring (tap → Radix dialog with the component breakdown + the
      engine's own explanation string), strain gauge (today vs the per-band target
      range), sleep card (hours vs need + stage breakdown), HRV/resting-HR cards (14-day
      sparkline, today's dot, baseline band), load card (acute/chronic/form, high-risk
      callout), erg card (latest Concept2 piece + predicted-2k range), one-line
      recommendation + per-source sync status + manual "Sync now".
- [x] App shell: bottom nav on mobile, a persistent sidebar at `lg:` (not a stretched
      phone column — a real desktop dashboard grid), login screen (password POSTs to
      `/api/login`; there's no `/api/me`, so auth state is probed via a lightweight
      authenticated route), empty states on every card, loading skeletons, an error
      state with retry.
- [x] Mock-data mode: `?mock=1` (realistic fixtures), plus `?mock=calibrating|empty|
      error|loading` for the states that don't exist in the live account yet (zero
      Concept2 results, Withings never connected) — auth is bypassed in mock mode so the
      UI is reviewable with no backend running at all.
- [x] Screenshotted at 390px and 1280px in both themes via Playwright MCP, critiqued and
      fixed across two rounds plus an advisor review (below): capture running in light
      theme by accident (fixed by forcing `prefers-color-scheme` rather than relying on
      the system default), sleep stage colors reusing the reserved red/green status hues
      for non-status data (fixed: stages now ramp through one accent hue, status colors
      stay reserved), a 1280px desktop layout that was just a stretched phone column
      (fixed: sidebar nav + a real 3-column dashboard grid at `lg:`), a sub-44px mobile
      logout button, dead space in the 1280px recovery-ring and recommendation cards, and
      a strain-gauge target band that visually disappeared once the fill passed through
      or past it (fixed: boundary ticks drawn above the fill, not a band under it — see
      the bug log below). WCAG AA contrast was checked numerically (script, not
      eyeballed) against the surfaces each text color actually sits on, before and after
      an advisor review caught two pairings checked only against `--bg`; 44px touch
      targets and `prefers-reduced-motion` were checked programmatically
      (`browser_evaluate` over every interactive element; a screenshot taken 400ms after
      data load with reduced-motion on, confirming the ring/sparklines render at their
      final state with no animation). Final screenshots in `docs/screenshots/`.
- [x] `CLAUDE.md` updated (`web/` is no longer empty; frontend commands added).

## Bugs an advisor review caught before this session's work was declared done

- **Path-traversal / auth hole in the SPA fallback** (`catch/main.py`). The catch-all
  `spa()` route built `_STATIC_DIR / full_path` and served it with `FileResponse` with no
  check that the resolved path stayed under `_STATIC_DIR` — `GET /../../../.env` or an
  encoded equivalent would have served the real `.env` (password hash, Fernet key, every
  API token) or the SQLite DB to anyone, unauthenticated, since this route has no
  `require_auth`. Fixed with `safe_static_file()`, which resolves the path and requires
  `candidate.is_relative_to(_STATIC_DIR)` before ever touching the filesystem, plus an
  explicit 404 for any mistyped `/api/`or `/auth/` path so a broken route can't fall
  through to a 200 HTML response. Covered by `tests/test_main_static.py` (asserts
  traversal inputs return `None`); then verified live against the real build with
  `uv run uvicorn` + `curl -o /dev/null -w '%{http_code} %{content_type} %{size_download}'`
  — traversal attempts now return exactly `index.html`'s byte count (939) rather than
  `.env`'s or the DB's, confirmed with the response body never piped to output (the thing
  that leaked a Concept2 token in session 2).
- **"Sync now" ran all three sources in parallel** via `Promise.all`. `recompute_scores`
  takes a non-blocking lock and skips itself if another recompute is already running, so
  two sources finishing close together could leave one unscored until the next scheduled
  sync — and three concurrent syncs is real memory pressure on a 1GB Pi. Changed to
  sequential (`RecommendationAndSync.tsx`).
- **Desktop screenshots were only critiqued once**, not twice as the quality bar asks:
  the ring card's content wasn't vertically centered in its taller card, and the
  recommendation card had dead space under a short line of text while its sibling erg
  card ran much taller. Fixed (`h-full` + `justify-center` on the ring; a flex spacer that
  pushes the sync row to the card's bottom) and a second desktop round was actually shot.
- **Predicted-2k time wasn't `m:ss.t`** — `predicted_time_s` went through `formatDuration`
  (whole seconds) instead of the same round-to-tenths-then-split logic already used for
  splits, so `393.6s` rendered as `6:34` instead of `6:33.6`; the range next to it was
  also in `/500m` pace while the headline was a total time, two different units side by
  side. Fixed: `formatSplit`'s logic was generalized into `formatTimeTenths` and reused
  for both the headline (`predicted_time_s`) and the range (`pace * 4`, i.e. also a 2k
  time now, not a 500m pace).
- **A 401 mid-session (expired cookie) left every card stuck on "Couldn't load" + Retry**,
  which can never succeed without re-authenticating. `request()` now fires a
  `catch:unauthorized` window event on any 401; `AuthProvider` listens and drops the user
  back to the login screen.
- **Contrast had only been checked against `--bg`**, not the surfaces text actually sits
  on. Re-checking against `--surface`/`--surface-2` found one real failure: the
  high-risk-load warning's red text on its own 10%-opacity tint fell under 4.5:1 in the
  light theme at `text-xs` size (4.42, "AA-large-only," not enough for small text). Fixed
  with a dedicated `--band-red-text` token (darker than `--band-red` in light mode only;
  dark mode's `--band-red` already cleared 4.5:1 there) rather than changing `--band-red`
  itself, which is tuned for dots/badges on `--bg`/`--surface` and already passed there.

## Gotchas / deviations from the literal task spec

- **No `/api/me` endpoint exists.** The frontend's `AuthProvider` probes auth state with
  `GET /api/sync/status` (any authenticated route would do) instead — works, but a real
  `/api/me` would be cleaner if session 4's Settings page ends up wanting more than a
  boolean.
- **Chart library question deferred** — Today's rings/gauges/sparklines are all
  hand-rolled SVG as instructed; Trends (session 4) is where a "do we need a chart
  library" decision actually arises, not this session.
- **JS bundle is ~510KB (164KB gzip)**, mostly React + Router + Query + Framer + Radix.
  Static assets served by FastAPI's `StaticFiles`, not loaded into Pi memory per request,
  so this is a download-size concern, not a 1GB-RAM concern — fine for a single-user LAN
  app, revisit with route-level code-splitting only if it's ever actually slow on the Pi.
- **The Today screen was never rendered against real `.env`/DB data in a browser** — only
  against `?mock=` fixtures and the fixture-backed pytest suite. The real `/api/today`
  JSON shape was dumped and used to build the TypeScript types and mocks (session 3's
  live account has 0 Concept2 results and no Withings connection, so `latest_erg` and
  `predicted_2k` were confirmed null there, matching the `empty`-ish real state), but a
  real authenticated page load was not screenshotted, to avoid the session-cookie/secret
  ever landing in terminal output. Worth doing once real Concept2 data exists.
- **The task named a `frontend-design` skill and a `webapp-testing` skill** for this
  session; neither exists in this environment's skill listing. Design direction/critique
  was done directly (documented in `DESIGN.md`) and the Playwright MCP tools were used
  directly for screenshots instead.

## Session 4 checklist

- [x] **Workouts list** (`/workouts`): merged Garmin + Concept2 feed, cursor-paginated
      (keyset on `(start, id)`, not `OFFSET` — a background sync inserting rows between
      page fetches can't skip or duplicate rows), category filter (erg/on_water/other),
      infinite scroll via `IntersectionObserver`. Each row's strain is read back from the
      already-cached `DailyScore.strain_json` component for that activity, not recomputed.
- [x] **Workout detail** (`/workouts/:id`): branches on category and on whether per-stroke
      data exists (`source === "concept2"`), not just category — a Garmin-only "erg" or
      "on_water" session (no PM5) has no strokes and falls back to the HR-zones/duration/
      strain layout with an explanatory note, same as a non-rowing "other" session. Erg
      detail with strokes: split/watts-over-distance chart with stroke rate as light dots
      (not a third connected line — see bug log) and an HR-zone band beneath; interval
      table (split/rate/watts/HR/drift-vs-rep-1 per rep); technique metrics per rep (split
      consistency, watts/stroke, rate/power slope, fade); drag factor. Notes + RPE box
      (shared across all workout types) saves to the new `/api/notes`.
- [x] **Trends** (`/trends`): metric picker (recovery/HRV/resting HR/sleep/strain/
      load-form/weight/W-per-kg/predicted-2k) x range picker (4w/12w/season/all — "season"
      is an undocumented-elsewhere convention, most recent past Sept 1, `lib/dateRanges.ts`);
      weekly volume bars by zone; personal-bests table (500m/1k/2k/5k/6k/30min/60min).
- [x] **Body** (`/body`, new nav item — sixth slot fit fine at 390px, checked): weight
      trend (raw + 7-day-smoothed-median dashed line, backend-computed), fat %/muscle mass
      (latest value + sparkline, reusing Today's `Sparkline` component), W/kg over time.
- [x] **Settings** (`/settings`): connected sources with last sync + reconnect (Garmin/
      Concept2 = trigger a sync; Withings = link to `/auth/withings/start`, a real OAuth
      redirect, not a fetch) + token expiry; zone mode + editable HR/power zone thresholds;
      max HR; units; theme toggle; a user-entered Garmin-key-expiry reminder (see bug log —
      the API exposes no such field); AI-coach placeholder. One explicit Save button, not
      per-field autosave (`PUT /api/settings` triggers a full-history recompute).
- [x] **Installable PWA**: `manifest.webmanifest`, an original generated icon (a "C"-shaped
      ring — doubles as the recovery-ring motif and Catch's initial; pure-Python PNG
      encoder, no new dependency, `web/public/icons/`), hand-rolled `sw.js` (no Workbox/
      vite-plugin-pwa — generated at build time by a small inline Vite plugin so it can
      know the real hashed asset filenames), offline shell verified **live** end-to-end
      (below), not just read through.
- [x] Backend: new/extended endpoints, all with tests (37 new, 131 total passing) —
      `GET /api/activities` (rewritten: pagination/category/dedup/strain), `GET
      /api/activities/{id}` (zones/strain/note/category), `GET /api/erg/{id}/strokes`
      (added `interval_summary`/drift/`distance_cum`/`t_cum`), `GET`/`POST /api/notes`
      (new), `GET /api/trends` (added `weight`/`w_per_kg`/`predicted_2k`, `load_acr` now
      carries acute/chronic/form), `GET /api/trends/volume` (new), `GET /api/pbs` (new),
      `GET /api/sync/status` (added `token_expires_at`). New pure modules: `classify.py`
      (erg/on_water/other), `body.py` (weight smoothing). `docs/analytics.md` §8-16.
- [x] Frontend quality bar: `App.tsx` converted to `React.lazy` per route (Today stays
      eager); initial bundle **153.9 KB + 16.2 KB modulepreload = ~170 KB gzip JS**
      (budget 250 KB), each new route its own chunk (0.9-3.8 KB gzip). Screenshotted at
      390px/1280px x dark/light for every new screen, critiqued, fixed, reshot (bug log
      below). Charts are hand-rolled SVG extending `Sparkline`'s pattern, not a new chart
      library — avoids the CSS-variable/canvas theming friction a library like uPlot would
      add and keeps the bundle small.
- [x] PLAN.md + CLAUDE.md (layout section) updated + commit.

## Bugs an advisor review and screenshot QA caught before this session's work was declared done

- **Offline Today would never have worked as first designed** — caught by an advisor
  review *before* writing any PWA code, not after: (1) `AuthProvider` treated any fetch
  failure as a 401 and dropped to the login screen, so a network error while offline (not
  an auth error) would hide the cached data behind a login wall with no way back online-only
  to clear it. Fixed: only a real `ApiError` with `status === 401` means "anon"; a network
  failure falls back to a `localStorage` "was last authed" flag instead, set on every
  successful auth check/login and cleared on logout/401. (2) TanStack Query v5 defaults to
  `networkMode: "online"`, which *pauses* queries while the browser is offline — the
  `today` query would never even run to consult the service worker's cache. Fixed:
  `networkMode: "offlineFirst"` on the query client's defaults.
- **The service worker's own cache writes silently never happened** — found by live-testing
  the offline path with Playwright (`context.setOffline(true)`, not just reasoning about
  the code): `cache.put()` calls inside the `fetch` handler weren't wrapped in
  `event.waitUntil()`, so the browser was free to tear the worker down the instant
  `respondWith`'s promise resolved, racing (and usually losing) the detached cache write.
  First attempt left `catch-api-v1` empty after a real page load. Fixed by wrapping both
  cache-write call sites in `waitUntil`; reverified the same way — a second live offline
  reload (after one prior online page load to let the SW populate its cache) rendered the
  real cached recovery/strain/sleep data, authenticated, with zero console errors.
- **Garmin's `rowing_v2` typeKey is on-water, not indoor** — the opposite of session 2's
  `ROWING_TYPE_KEYS = {"rowing_v2", "indoor_rowing"}` comment, which claimed (unverified —
  the Concept2 account had 0 results at the time) that both were erg typeKeys. Querying
  this session's live DB (`SELECT type, SUM(raw_json LIKE '%startLatitude%') ... GROUP BY
  type`) found 29/29 real `rowing_v2` rows carry GPS fields and 0/2 `indoor_rowing` rows do.
  Fixed in a new `catch/analytics/classify.py` (`GARMIN_ERG_TYPES = {"indoor_rowing"}`,
  `GARMIN_ON_WATER_TYPES = {"rowing_v2"}`), which `sync/concept2_client.py`'s Garmin<->
  Concept2 link-matching now imports instead of keeping its own (wrong) copy — this was a
  real, live latent bug in session 2's dedup logic, not just a session-4 classification
  question, caught only because building the Workouts screen required actually checking it.
- **A flexbox `min-width: auto` bug stretched every page past the viewport at 390px** once
  any card held a horizontally-scrollable table (the Settings zones table, the workout-
  detail interval table) — the table's `min-w-[...]` bubbled up through nested flex
  ancestors that never got `min-width: 0`, so `document.documentElement.scrollWidth` (426px)
  exceeded `clientWidth` (390px) site-wide, most visibly as the Settings page's sticky
  "Save" button appearing to hang 20px off the right edge of the screen. Fixed with
  `min-w-0` on `AppShell`'s inner flex column and `<main>`; verified by asserting
  `scrollWidth === clientWidth` after the fix, not just eyeballing a screenshot.
- **`formatShortDate` produced "Invalid Date" on every Workouts-list row** — the function
  assumed a bare `"YYYY-MM-DD"` input (true for every session-3 caller: sparkline/trend
  points) and unconditionally appended `"T00:00:00"`; the new Workouts rows pass
  `workout.start`, a full ISO datetime, so the string became
  `"2026-10-29T07:30:00.000ZT00:00:00"`. Fixed by only appending the time-of-day when the
  input doesn't already contain a `"T"`.
- **The erg chart's stroke-rate line was an unreadable zigzag** — stroke rate is a
  whole-number spm value that often only takes 2-3 distinct integers across a whole piece;
  independently auto-scaling it to fill the full chart height (same per-series scaling the
  split/watts lines use) turned small integer steps into a harsh sawtooth that visually
  dominated the chart. Fixed by rendering rate as small discrete dots instead of a
  connected line — same information, no longer reads as a competing signal with split/watts.
- **Both reps' technique-metric tiles rendered identical values** in mock mode (a static
  mock fixture returning the same hardcoded object twice) — caught by screenshot review
  (two "Technique — rep N" cards with suspiciously identical numbers), not a real-backend
  bug, but fixed since a misleading screenshot QA pass is worse than no screenshot at all.

## Gotchas / deviations from the literal task spec

- **PWA was pulled forward from session 6 into this session**, per explicit task
  instructions this session rather than a planning error — session 6's roadmap line above
  has been updated to drop it.
- **No chart library added.** The task's "lazy-load chart code per route" phrasing was
  weighed against adding one (uPlot was the leading candidate — tiny, canvas-based) versus
  hand-rolled SVG extending `Sparkline`. Chose hand-rolled: a canvas library can't read CSS
  custom properties directly (would need `getComputedStyle` + a redraw on every theme
  toggle), and the route-level `React.lazy` split already achieves "lazy-loaded per route"
  for the chart *code*, library or not. Revisit only if a future screen needs chart
  features hand-rolled SVG can't reasonably do (zoom/pan over thousands of points).
  `docs/analytics.md`/`DESIGN.md` reasoning recorded here since PLAN.md previously deferred
  this exact decision to this session.
- **"Season" range has no single standard definition** for rowing training — picked "most
  recent past September 1" (Northern-hemisphere indoor/winter-block convention) as a pure
  frontend display choice (`lib/dateRanges.ts`), not a backend setting, since nothing else
  needs that definition.
- **Predicted-2k trend is not the same number as Today's `predicted_2k`** — the trend is
  one point per qualifying piece, each independently extrapolated to 2000m; Today's
  headline number averages several recent pieces into one ensemble estimate. Documented in
  `docs/analytics.md` §13 specifically so the two numbers sitting near each other on
  different screens don't look like a bug.
- **"Garmin key expiry" is two different things, shown separately** — the API exposes no
  key-expiry field at all (checked `docs/garmin-openapi.json`); `token_expires_at` is the
  24h JWT's real, auto-refreshed expiry (always ~24h out after a successful sync), while
  the Settings-screen date field the task asked for is a new user-entered reminder
  (`garmin_key_expires_on`) for a fact only the athlete knows. See `docs/analytics.md` §14.
- **Weekly zone volume falls back to a whole-duration estimate** for any session without
  per-sample HR (every Garmin-only activity, as of this session's live account — 0
  Concept2 results exist there) — flagged `"estimated": true` per week rather than silently
  mixing exact and estimated seconds with no indication.
- **The offline shell was never exercised against `?mock=` fixtures** (mock mode never
  calls `fetch`, so there's nothing for a service worker to intercept) — verified instead
  against a real, disposable backend instance in `/private/tmp` (throwaway password/
  Fernet key/DB, never touching the real `.env`/`data/catch.db`), logged in and driven
  through Playwright, confirmed offline-reload renders real cached data with zero console
  errors. That scratch instance and its DB were discarded after verification.
- **Secure-context requirement not yet relevant, but will be on the Pi**: service workers
  (and installability) only work on `localhost` or HTTPS. A bare `http://<pi-lan-ip>:8000`
  deployment won't install as a PWA or register a service worker at all — noted here as a
  session-6 deploy concern (TLS, even just a self-signed cert on the LAN, or a Tailscale/
  reverse-proxy HTTPS front).

## Next steps (session 5)

- AI coach chat (bring-your-own Anthropic key) + MCP server. The Settings screen's AI
  section is a placeholder card ("Coming in session 5") already wired into the page.
