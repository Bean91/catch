# Catch — build plan

Self-hosted, single-user rowing training app. Whoop-style recovery/strain from Garmin +
Withings + Concept2, with an AI coach later. Runs 24/7 on a Raspberry Pi 3 (1GB RAM, ARM)
alongside PiAware.

## Roadmap

1. Scaffold + Garmin + Withings sync
2. Concept2 sync + rowing analytics engine
3. Design system + Today screen
4. Workout detail, trends, body comp, settings, installable PWA
5. AI coach chat (bring-your-own Anthropic key or local Ollama) + MCP server
6. Real coach verification against a live local Ollama instance (Pi deploy, Tailscale,
   backups, and Whoop were descoped by the user at the time — see that session's notes below)
7. **Real Raspberry Pi deployment: systemd, Tailscale HTTPS, nightly backups, Garmin-key
   banner, then a live click-through on the deployed Pi** ← this session. The session-6 scope
   decision above was explicitly superseded by the user asking for exactly those items.
   Whoop (originally "part C," contingent on a yes") was offered again at the end of this
   session — see that section for the outcome.

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

## Session 5 checklist

- [x] **Shared tool layer** (`catch/coach/tools.py`): one registry of 16 tools (`get_today`,
      `get_wellness`, `list_workouts`, `get_workout`, `get_trends`, `get_body_comp`,
      `get_load`, `predict_2k`, `get_zones`, `add_note`, plus the memory tools `remember`/
      `add_event`/`update_event`/`set_goal`/`forget`/`recall`) with Anthropic- and
      Ollama-shaped JSON schemas generated from one source, dispatched through a single
      `call_tool(session, name, args, ctx)`. The in-app coach, `GET/POST /api/coach/tools*`,
      and the MCP server's in-process backend all call this same function — no duplicated
      tool logic anywhere. Every range tool (`get_wellness`/`get_trends`/`get_body_comp`) is
      capped at 180 rows, evenly downsampled if wider; `get_workout`'s stroke data is capped
      at 100 points plus the interval table. No tool touches `OAuthToken`/`CoachCredential`/
      `ApiToken` at all, by construction — covered by a test that seeds secrets into those
      tables and greps every read-only tool's JSON output for them.
- [x] **In-app coach** (`catch/coach/`, `catch/api/routes_coach.py`): `chat.py`'s manual
      tool-calling loop (not the Anthropic SDK's beta Tool Runner — needed fine control over
      SSE events, the exact `usage` object for cost accounting, and parity with a second
      provider that has no tool-runner equivalent) streams normalized events over
      `POST /api/coach/conversations/{id}/messages` (`text/event-stream`), capped at 8
      tool-iterations per turn, checking the daily spend cap before *every* provider call
      inside the loop, not just once per user turn. Conversations/messages persist in a
      provider-neutral block shape (`text`/`tool_call`/`tool_result`), not either provider's
      wire format, so a conversation can switch providers mid-stream. Prompt caching: one
      `cache_control` breakpoint on the static system-prompt block (covers it plus the tool
      definitions, per the render order `tools -> system -> messages`); the per-turn memory
      block (events/goals/facts with days-to-go) sits in a second, uncached system block so
      it can change every turn without busting the cache. Cost uses all four Anthropic usage
      fields (input/output/cache-write/cache-read) against user-entered `$/1M` rates in
      Settings — never hardcoded; Ollama's rates are always `{}`, which correctly prices every
      local turn at exactly `$0`. Coach screen: streaming message bubbles, tool calls as
      small expandable chips (`catch/coach/chat.py`'s `_tool_label` templates, mirrored in
      `web/src/lib/toolLabels.ts` for persisted history that doesn't carry the live label),
      the three suggested prompts plus a Morning brief button, a conversation-history dialog,
      and a $spend/$cap pill that refreshes after every turn.
- [x] **Settings**: Anthropic key Fernet-encrypted server-side in its own `coach_credentials`
      table (never round-trips to the browser — `GET` returns only `{configured, last4}`),
      test-connection button (`models.list()`, zero token cost), model picker populated live
      from the API and defaulting to the newest id containing "sonnet" (resolved once, then
      cached into `coach_settings.anthropic_model` so it isn't re-resolved every turn), daily
      spend cap. Ollama: base-URL + model fields, models filtered to tool-capable ones via
      `/api/show`'s `capabilities` list (not `/api/tags`, which doesn't report them), a
      2.5s-timeout health check before every chat so a sleeping laptop fails fast with an
      "offer to switch to Anthropic" action in the Coach UI rather than hanging. Device
      tokens (create/list/revoke) for the MCP server, shown once at creation. A new Memory
      page (`/settings/memory`) lists/edits/deletes every event, goal, and fact — including
      expired facts, flagged rather than hidden, since `recall()` only filters them at read
      time and never deletes.
- [x] **Coach memory** (`catch/coach/memory.py`): `events`/`goals`/`athlete_facts` tables;
      `remember`/`add_event`/`update_event`/`set_goal`/`forget`/`recall` tools, with `forget`
      taking a prefixed ref (`fact:12`/`event:3`/`goal:5`, disambiguating across three
      tables) as `recall` returns them. `GET /api/today` gained `next_a_race` (name,
      days-to-go, a `taper` flag for the last 14 days before an A-priority race) — computed
      once in `routes_analytics.today()` so both the tool and the Today screen's new
      recommendation-card line share one code path. System prompt (`catch/coach/
      system_prompt.md`, user-editable) tells the model to save memory on its own, confirm
      in one line, never invent a fact the athlete didn't say, and ask rather than guess a
      vague date.
- [x] **MCP server** (`catch/mcp_server/`): official `mcp` Python SDK (2.x — `FastMCP` was
      renamed `MCPServer` in this version, a real drift from the name used in most
      documentation and training data; caught by letting the first import fail and reading
      the SDK's own redirect error rather than guessing). One `build_server()` registers all
      16 tools (schemas inferred from type hints/docstrings — `Literal[...]` unions produce
      real JSON-schema enums) plus 2 prompts (`daily_check_in`, `weekly_review`) against a
      swappable backend: `RestBackend` (real `httpx` calls to `POST /api/coach/tools/{name}`
      with a bearer device token) for the stdio transport Claude Desktop uses, and
      `InProcessBackend` (dispatches straight into `catch.coach.tools.call_tool`) for the
      optional `/mcp/` streamable-HTTP mount, since an HTTP call from inside Catch's own
      single-worker uvicorn back to itself would deadlock. The HTTP mount is off by default
      (`CATCH_MCP_HTTP_ENABLED=0`) so the Pi never imports `mcp` unless Tailscale access is
      actually wanted; its tool calls go through the same `require_tool_auth`-equivalent
      bearer check as everything else. `uv run catch token create --name <device>` mints a
      device token (sha256-hashed at rest, raw value shown once). `docs/mcp.md` has the exact
      `claude_desktop_config.json` snippet and the Inspector commands.
- [x] Tests: 62 new (131 -> 193 total) — the tool layer (incl. the no-secrets-leak sweep and
      the stroke-downsample cap), memory CRUD/recall/expiry/next-A-race, the chat loop (a
      `FakeProvider` drives it — tool-call-then-text, cache-token cost math, the cap blocking
      a request before any provider call *and* mid-loop between tool iterations, the
      too-many-iterations guard, provider-resolution errors), both providers (Anthropic via a
      fake `anthropic` module injected into `sys.modules`, asserting the exact `cache_control`
      placement and the Anthropic<->provider-neutral block conversion; Ollama via
      `httpx.MockTransport`, incl. synthesized tool-call ids and the "laptop asleep" path),
      coach settings/credential masking, cost math, and the coach API routes (bearer-vs-cookie
      auth scoping, SSE event parsing end-to-end with the chat loop mocked).
- [x] PLAN.md + CLAUDE.md (layout/commands) updated + commit.

## Real verification (2026-10-31/11-01)

- **MCP, stdio**: ran a disposable Catch instance (fresh password/session-secret/Fernet key,
  scratch SQLite DB under `/private/tmp`, deleted after — never the real `.env`/
  `data/catch.db`, matching sessions 1/2/4's precedent) and the real `@modelcontextprotocol/
  inspector@latest` (v2.13.0) CLI against `catch-mcp`. `tools/list` returned all 16 tools
  with correctly-inferred schemas (enums came through from `Literal[...]` hints);
  `prompts/list` returned both prompts; a real `tools/call --tool-name get_zones` round-
  tripped stdio -> `RestBackend` -> `POST /api/coach/tools/get_zones` (confirmed in the
  request log) -> the tool registry -> the same JSON a direct `curl` with the same device
  token returns.
- **MCP, HTTP mount**: a second disposable instance with `CATCH_MCP_HTTP_ENABLED=1`, tested
  with raw `curl` (the Inspector's `--transport http` assumes full OAuth, which this
  deliberately isn't). Found and documented a real gotcha: `POST /mcp` (no trailing slash)
  405s, because Starlette's `Mount("/mcp", ...)` doesn't match a bare prefix, so the request
  falls through to the SPA catch-all route instead — `POST /mcp/` (trailing slash) is
  required and works (`401` with no token, `200` + a correct `initialize` handshake with
  one). The server log's `StreamableHTTP session manager started` line confirmed the session
  manager is actually running inside Catch's lifespan, not silently absent (the specific
  failure mode of a mounted sub-app's lifespan never firing).
- **Frontend**: Coach, Memory, and the Settings AI-coach card screenshotted at 390px/1280px
  in both themes via Playwright MCP against `?mock=1` (incl. a full scripted streaming turn
  — tool-call chip, tool-result, streamed text, attribution line). Two real bugs found and
  fixed this way: the provider-toggle buttons had a stray `capitalize` class turning
  "Anthropic (bring your own key)" into jarring mid-sentence title case, and the page-level
  sticky "Save settings" button — once the AI-coach card grew long enough — floated an
  invisible full-width hit-box over the "Test connection" button a few cards up, silently
  swallowing its clicks; fixed with `pointer-events-none` on the row and `-auto` on the
  button itself, then re-verified with a real Playwright click that the test-connection
  result actually appeared.
- **Pre-existing bug found and fixed along the way** (not a session-5 regression — confirmed
  by reproducing it against an unmodified `main`): `catch/sync/scoring.py`'s `_earliest_date`
  took `Activity.start`'s *UTC* calendar date instead of its local one. For a window each
  evening in a negative-UTC-offset timezone (triggered here: EDT, ~8pm-midnight local), the
  newest activity's UTC date is already "tomorrow" while `date.today()` (local) is still
  "today" — when that activity is also the *earliest* one in the DB (a fresh instance, or
  `tests/test_api_notes.py::test_post_note_triggers_recompute_affecting_strain`'s scenario),
  `recompute_scores`'s `day <= today` loop silently processed zero days. Fixed with
  `.astimezone().date()`, matching every other local-day computation in the file.

## Gotchas / deviations from the literal task spec

- **No `mcp-builder` skill exists in this environment's skill listing** (named in the task,
  same situation as session 3's missing `frontend-design`/`webapp-testing` skills) — the MCP
  server was built directly against the installed `mcp` SDK, introspected with Python
  (`inspect.signature`) rather than guessed, since `mcp` 2.x renamed `FastMCP` to
  `MCPServer` and restructured several APIs from what's commonly documented.
- **Coach settings and the Anthropic key live in their own tables** (`coach_settings`,
  `coach_credentials`), not folded into the existing `settings` JSON blob — a per-model price
  dict would trip `settings_store`'s unknown-nested-key validation, and every `PUT /api/
  settings` triggers a full `recompute_scores`, which has nothing to do with the coach.
- **Device bearer tokens are scoped to the shared tool endpoints only**
  (`GET/POST /api/coach/tools*`) via `require_tool_auth`, which accepts the session cookie
  *or* a token; every other coach route (settings, the key, conversations, tokens
  themselves, memory) stays on cookie-only `require_auth`, so a stolen laptop token can read
  training data and write memory but can't read the Anthropic key, browse chat history, or
  mint more tokens.
- **No markdown rendering added for coach replies** (`whitespace-pre-wrap` plain text) —
  consistent with session 4's "no new chart library" call: the model's answers are
  conversational prose, not formatted documents, and a markdown dependency isn't worth it
  for that.
- **`anthropic` and `mcp` are both lazy-imported** (inside `AnthropicProvider.__init__` and
  behind `CATCH_MCP_HTTP_ENABLED`/the `catch-mcp` entry point, respectively) and both checked
  against PyPI before adding, per CLAUDE.md's Pi/ARM rule: both packages themselves ship as
  pure-Python wheels, and their compiled transitive deps (`jiter`, `pydantic-core`) publish
  both `aarch64` and `armv7l` wheels — safe on a 32- or 64-bit Pi OS either way.
- **The `/mcp` HTTP mount needs a trailing slash** (`/mcp/`) — see Real verification above.
  Documented in `docs/mcp.md` and `.env.example` rather than worked around with a redirect,
  to avoid depending on every client following a 307 on a POST.

## Session 6 checklist

Scope, set by the user: Pi deploy, Tailscale, backups, and Whoop are all **out of scope**
for this session (backups will be added via GitHub later; the others deferred indefinitely).
The one thing session 5 flagged as unverified — the in-app coach's actual provider turns —
was in scope, with a real local Ollama instance on the user's laptop (no Anthropic key
available) instead of Anthropic.

- [x] **Confirmed SSH access to the real Pi** (`ssh opensky-pi`, no deploy performed) — a
      real aarch64 Debian box, matching the ARM-wheel check from session 5.
- [x] **Live-verified the full in-app coach pipeline against a real local Ollama server**
      (`http://localhost:11434`, reached directly since this session runs on the user's own
      laptop via Remote Control) — on a disposable throwaway Catch instance (fresh secrets,
      scratch SQLite DB under `/private/tmp`, deleted after; same pattern as every prior
      session's live checks, never the real `.env`/`data/catch.db`), seeded with 15 days of
      realistic `DailyWellness`/one `Activity`/one A-priority `Event` so the coach's answers
      would be grounded in real-looking numbers, not nulls:
  - `POST /api/coach/test-connection` and `GET /api/coach/models` against real Ollama —
    correctly listed only the 9 of 11 installed models that report `"tools"` capability.
  - A real `POST /api/coach/conversations/{id}/messages` turn: the model (first `qwen3:14b`,
    then `gemma4:e2b-nvfp4`) correctly emitted a native Ollama `tool_calls` block for
    `get_today`, `OllamaProvider` parsed it into the shared tool registry, `get_today` ran
    against the real seeded data, the tool result was fed back, and the model's final answer
    correctly cited the real HRV/resting-HR/baseline/sleep numbers and the seeded A-race's
    name, date, and days-to-go — confirmed by reading the persisted conversation back via
    `GET /api/coach/conversations/{id}`, not just eyeballing the stream. Usage/cost events
    reported `cost_usd: 0.0` on every turn, as expected for a local model.
  - A real memory-tool turn: telling the coach about a hamstring issue made it call
    `remember(category="injury", ...)` on its own (per the system prompt's instruction,
    unprompted), which created a real `AthleteFact` row, visible afterward via
    `GET /api/coach/memory`.
- [x] Two real bugs found by this verification were fixed and live-reverified against the
      same repro (`catch/api/sse.py`, `catch/coach/providers/ollama_provider.py`) — see
      "Findings," below. 6 new tests (193 -> 200 total).
- [x] PLAN.md + commit.

## Findings from live Ollama verification (2026-11-01), and the two fixed afterward

The user asked for both real findings below to be fixed before moving on, rather than just
documented — both were fixed, then **re-verified live against the real failure repro**, not
just covered by new unit tests.

- **Tool-calling reliability varies a lot by model, even among models Ollama itself tags
  `"tools": true`.** `gemma4:e2b-nvfp4` and `qwen3:14b` both correctly used Ollama's native
  `tool_calls` field. `qwen2.5-coder:14b` — also tagged tool-capable — instead streamed the
  tool call as literal text in `message.content`, token by token, which
  `OllamaProvider.stream_turn` had no way to distinguish from a real answer: a user picking
  that model would see raw JSON leak into the chat instead of a tool chip. Worse, the same
  model wasn't even consistent with itself: one turn emitted bare `{"name": "get_today",
  "arguments": {}}`, a later turn wrapped the identical shape in a ```` ```json ```` fence —
  two different malformations from one model, found by actually re-running the live repro
  rather than trusting the first fix. **Fixed**: `OllamaProvider.stream_turn`
  (`catch/coach/providers/ollama_provider.py`) now holds content back instead of streaming it
  live the moment it opens with `{` or ` ``` ` , and once the turn ends, `_parse_raw_tool_call`
  (via `_strip_code_fence`) tries to parse the buffered blob as `{"name": <a real tool>,
  "arguments"/"parameters": {...}}`; a match becomes a normal `tool_call` event, a non-match
  (real prose that happened to start with `{`) is flushed as one text block rather than
  silently dropped. Normal answers are unaffected — the one-chunk lookahead cost is only paid
  by content that opens with `{` or a code fence. Covered by two new tests replaying the exact
  chunk sequences captured live (`tests/coach/test_provider_ollama.py`), and live-reverified:
  re-asked the identical question against the fenced-JSON failure case, which now produced a
  clean `tool_call` SSE event and a real coached answer instead of leaked markdown+JSON.
- **`qwen3:14b` (a "thinking"-mode model) took ~88 seconds to answer even a trivial,
  tool-free "say hello" once loaded with all 16 tool schemas** — almost entirely spent on
  invisible `<think>`-style tokens the model emits as empty `content` deltas before any
  visible text (measured directly: 149 empty chunks, then real text). `gemma4:e2b-nvfp4`
  answered a tool-requiring question in ~14 seconds. This is a real hardware/model
  characteristic, not a bug — not fixed, since there's no code issue to fix, but worth a
  per-model "typically slow" hint in Settings someday so a user's first message doesn't
  silently hang for a minute and a half with no explanation.
- **A client disconnect did not stop the server-side turn.** Killing the `curl` client
  mid-stream (simulating a closed browser tab) did not stop `chat.run_turn` — the Ollama
  call, the tool execution, and the persisted messages all completed normally ~90 seconds
  later, confirmed by them showing up in the conversation history afterward. Low-risk for a
  single-user app on a free local model, but for the Anthropic path this means a user who
  navigates away mid-answer still pays for the full generation. **Fixed**: a new
  `catch/api/sse.py::stream_until_disconnected` wraps the SSE generator in
  `routes_coach.py`'s `post_message`, polling `request.is_disconnected()` every second while
  waiting for the turn's next event (not just once per event — the gap while a "thinking"
  model generates nothing is exactly where the old per-event check would've missed it) and
  cancelling the in-flight call the moment a disconnect is seen. The first version of this
  fix had its own live-caught bug: it also called `source.aclose()` on the generator it had
  just cancelled, which raises `RuntimeError: aclose(): asynchronous generator is already
  running` — removing that redundant close (the cancellation alone already unwinds the
  generator's own `async with`/`finally` blocks, including the underlying HTTP connection)
  fixed it. Re-verified live twice: first confirming the turn stopped early but hit that
  RuntimeError, then confirming a clean stop (user message persisted, no assistant message,
  no error in the server log, cancelled within seconds instead of ~90) after the real fix.
  New tests in `tests/test_sse.py` cover normal exhaustion, mid-wait cancellation (asserting
  the source's own cancellation and cleanup actually ran), and exception propagation.

## Session 7 checklist

Real deploy to the user's actual Raspberry Pi 3 (`opensky-pi`, aarch64, Debian 13 "trixie"),
which also runs `piaware`, `fr24feed`, and `tar1090` 24/7. Every step below was verified live
against that real box, not just read for plausibility.

- [x] **Inspected before changing anything**: aarch64 (so the 32-bit uv-build stop condition
      never applied), ~676MiB RAM available of 905MiB total, 9.9GB disk free, ports 80/
      30001-30006/30104-30106/8504/8754 already claimed by PiAware/fr24feed/lighttpd — 8000
      (the `.env.example` default) was free. Tailscale was already installed and running, no
      `serve` config yet. No passwordless sudo and no TTY for a non-interactive one — this
      shaped everything that follows.
- [x] `deploy/pi-bootstrap.sh` — one root script, written to be re-run (the user ran it three
      times total, each idempotent): creates a dedicated `catch` system user (no login shell,
      no home dir), `/opt/catch/app` (code, world-readable, no secrets) and `/var/lib/catch`
      (DB/FIT/secrets/backups, `750`, `.env` at `600`) kept **outside** the code directory so
      `deploy.sh`'s `rsync --delete` can never touch them, installs `sqlite3`, the systemd
      units below, a journald `SystemMaxUse=50M` drop-in (caps disk use system-wide without
      touching `Storage=`, which PiAware's own logs also use), a sudoers rule scoped to
      exactly `systemctl restart/is-active/status catch.service` (nothing else — verified
      passwordless `sudo -n systemctl is-active catch.service` works, while a journalctl/
      backup-service start attempt correctly still prompts), and `tailscale serve --bg 8000`
      for tailnet-only HTTPS.
- [x] **Real secrets/DB/FIT handoff without the password or secret values ever appearing in
      chat or logs**: the laptop's `.env` and a fresh `sqlite3 .backup` snapshot of the real
      DB were rsynced file-to-file into an opensky-writable staging dir
      (`/opt/catch/.staging`, mode `700`); only the four non-secret fields (`CATCH_ENV`,
      `CATCH_DB_PATH`, `CATCH_BASE_URL`, `WITHINGS_REDIRECT_URI`) were edited via `sed`
      matching key *names*, never touching the secret lines. The bootstrap script's second
      run adopted these into `/var/lib/catch` with correct ownership and deleted the staging
      copies — confirmed by listing `/opt/catch/.staging` empty afterward and the adopted
      files' perms (`catch.env` `600`, `catch.db` `640`, both `catch:catch`).
- [x] `deploy/catch.service`: `User=catch`, binds `127.0.0.1:8000` only (not the tailnet IP —
      `tailscale serve` is the only way in), `Nice=10` + `IOSchedulingClass=idle` +
      `MemoryMax=300M`, `Restart=on-failure`, `ProtectSystem=strict` + `ProtectHome=true` +
      `ReadWritePaths=/var/lib/catch` only.
- [x] `deploy.sh` (laptop side): builds the frontend, rsyncs `catch/`/`pyproject.toml`/
      `uv.lock` (never `.env`/data), runs `uv sync` on the Pi with
      `UV_PYTHON_INSTALL_DIR`/`UV_CACHE_DIR` pointed at `/opt/catch/.uv-*` (**not** under
      `/home/opensky`, which is mode `0700` — the `catch` user would otherwise get `EACCES`
      on a symlinked interpreter at service start, a bug caught by reasoning through the
      permission model before it ever happened, not live), restarts via the scoped sudo rule,
      and polls `/api/health`. **Live-verified end to end**: `uv sync` pulled aarch64 wheels
      for every native dependency (cryptography, argon2-cffi-bindings, pydantic-core) — no
      piwheels index needed, no compiling on the Pi. First real deploy's health check failed
      at the original 15s retry budget; the real cold-start was ~18-20s (confirmed via
      `journalctl` timestamps between "Started" and "Application startup complete"), so the
      retry window was widened to 40s — re-verified on the next deploy.
- [x] **Real, verified-live bug: `MemoryMax=300M` was silently unenforced.** `/proc/cgroups`
      showed no `memory` line at all — Raspberry Pi OS ships the kernel's memory cgroup
      controller compiled in but off by default. Caught by checking
      `/sys/fs/cgroup/system.slice/catch.service/memory.max` actually existed, not just
      trusting `systemctl show`'s `MemoryMax=314572800` (which the unit file sets
      successfully regardless of whether a real cgroup backs it — a gap between "systemd
      accepted the setting" and "the kernel can enforce it"). Fixed by adding
      `cgroup_memory=1 cgroup_enable=memory` to `/boot/firmware/cmdline.txt` (backed up
      first) and rebooting — the user explicitly approved the reboot after being told it
      would briefly interrupt PiAware/fr24feed/tar1090 (they're enabled units, so they came
      back automatically). Re-verified post-reboot: `cgroup.controllers` now lists `memory`,
      `catch.service`'s real `memory.current` read ~121MB against the real 300MB cap, and
      PiAware/fr24feed/tar1090 were confirmed `active` again within ~30s.
- [x] Nightly backup (`deploy/catch-backup.service`+`.timer`, `deploy/backup.sh`,
      `deploy/pull-backups.sh`) — **live-verified**, not just read: triggered manually
      (`systemctl start catch-backup.service`, since that's deliberately outside the scoped
      sudo rule — the user ran it interactively), produced a real
      `catch-20261101T125838Z.db` at `640`/`catch:catch` in `/var/lib/catch/backups/`, and
      `./deploy/pull-backups.sh` successfully rsynced it to the laptop — confirming `opensky`
      being added to the `catch` group in bootstrap actually grants the read access it's
      supposed to.
- [x] Withings callback docs updated (`docs/withings-endpoints.md`) for the Tailscale HTTPS
      URL, including the tradeoff that `tailscale serve` (tailnet-only, what's enabled) won't
      satisfy a Withings-side active-fetch validation the way `tailscale funnel` (public)
      would — Funnel was not enabled, since that's a real public-exposure decision the user
      didn't make. `docs/mcp.md` also updated: its Claude Desktop config example previously
      pointed at `http://<tailnet-ip>:8000`, which is now wrong since uvicorn only binds
      `127.0.0.1` — corrected to the HTTPS `.ts.net` hostname.
- [x] **Garmin key-expiry banner — built twice.** First pass added a new `.env`-based
      `GARMIN_KEY_EXPIRES` → `GET /api/garmin/key-status` → a new `GarminKeyBanner`
      component, with tests and a mock fixture. Live Playwright testing against the Settings
      page then surfaced that **this already existed** from an earlier session: a
      `garmin_key_expires_on` field in the `settings` table, editable right there in
      Settings, with its own inline 14-day warning — just missing the link to Garmin's key
      page and not shown outside Settings. Rather than ship two disconnected "Garmin key
      expiry" mechanisms (one `.env`-sourced requiring an SSH edit to update, one UI-sourced
      and user-editable), the `.env`-based endpoint/field/tests were fully reverted
      (`catch/api/routes_sync.py`, `catch/core/config.py`, `tests/test_api.py`, `.env.example`
      all back to their pre-session state — confirmed back to exactly 200 passing tests) and
      the existing `garmin_key_expires_on` mechanism was promoted into a new
      `web/src/lib/garminKey.ts` (shared `daysUntilGarminKeyExpires` + the key-page URL, so
      Settings.tsx's inline warning and the new app-wide `GarminKeyBanner` can't drift from
      each other) with the missing link added to both. Caught entirely by live-testing against
      the real deployed app rather than only unit tests — the kind of bug a fixture-based
      suite alone wouldn't surface, since both mechanisms "pass" in isolation.
- [x] **Live Playwright click-through at 390px against the real Pi deployment with real data**
      (not mocks) — Today, Workouts, a Workout detail, Trends, Body, Coach, Settings, Coach
      memory, plus a light-theme spot check. Login was done by the user typing their real
      password directly (after an earlier plan — them typing it into the Playwright-driven
      browser themselves — turned out to be impossible once they were on phone Remote
      Control with no access to the laptop's screen; they chose to disclose it directly
      instead, after independently confirming login + PWA install worked from their own
      phone browser on the same tailnet). Found and fixed the Garmin-banner duplication
      above; found no other bugs. All `/api/*` requests across the whole click-through
      returned 200 (checked via `browser_network_requests`, not just eyeballing screenshots)
      except the expected pre-login 401 and two transient 404s from a stale cached JS bundle
      mid-redeploy (gone after the next page load). Screenshots in
      `docs/screenshots/pi-live-*.png`.
  - **An attempt to extract the Playwright session's cookie value to disk (to measure
    `/api/today` timing purely server-side via SSH+curl, excluding network latency) was
    blocked by Claude Code's own auto-mode classifier as "Credential Materialization."** Not
    worked around. Measured instead via `fetch('/api/today')` timed with `performance.now()`
    from inside the authenticated page itself (so the real cookie jar is used without ever
    being read out of the browser): **47-63ms per call, ~53ms warm average**, end-to-end over
    real Tailscale HTTPS from the laptop — roughly 10x under the 500ms budget, with enough
    margin that the untested split between network and Pi-side processing time doesn't matter.
- [x] `README.md` written from scratch (local setup, Pi deploy, backups, Withings callback
      re-registration, Garmin key reminder, MCP pointer). `PLAN.md` updated (this section).

## Part C (Whoop) — declined for this session

Offered again at the end of this session per the task's "only if I say yes when you get here"
— the user chose to stop at `v1.0` without it. Nothing Whoop-related was started;
`catch/sync/` still has only `garmin_client.py`/`withings_client.py`/`concept2_client.py`. If
picked up later: OAuth app registration at Whoop's developer portal, a new
`sync/whoop_client.py`, mapping recovery/sleep/cycles/workouts into the existing tables, and a
per-metric source-priority setting (e.g. HRV from Whoop, workouts from Garmin+Concept2) surfaced
in Settings.

## Session 8 checklist

The task that opened this session called it "session 7" — PLAN.md's own numbering already used
that number for the real Pi deployment (above), so this continues the file's own sequence
instead rather than creating a second "Session 7" heading.

Make every time-series chart (Trends, Body, Today's HRV/RHR sparklines, workout-detail erg
chart) interactive: pan, pinch/wheel/button zoom clamped 7d–all-time, a navigator/brush strip,
hover/press-hold crosshair tooltips, 7d/4w/12w/6m/1y/season/all presets with the range in the
URL, linked axes on Trends, coach-memory annotations, keyboard control, and page-level pinch
disabled so only charts respond to it — all against a new downsampled `/api/series` endpoint,
since the Pi has 1GB RAM and can't hand a browser years of raw daily rows.

**This was built in two passes.** The first pass (everything below) was declared done, then an
advisor review of the whole session — prompted by this file's own "verify before claiming
done" habit — re-examined the actual behavior rather than trusting the first pass's screenshots
and self-reported perf numbers. It found six real bugs the first pass had missed, all through
direct empirical checks (reading a chart's real `aria-label` after a cold URL load, dispatching
a real `WheelEvent` and reading `defaultPrevented`, re-deriving the perf numbers with a
corrected test), not from re-reading the code. All six are fixed below, with what was actually
wrong and how it was confirmed — see "Bugs the advisor review caught" below the checklist.

- [x] **`catch/analytics/downsample.py`** (pure functions, no I/O, per CLAUDE.md's analytics
      convention): `lttb_indices` (Largest-Triangle-Three-Buckets), `bucket_value_bounds` (the
      min/max a kept point's neighborhood hid, for an optional band), `downsample_with_bounds`.
      8 unit tests (`tests/analytics/test_downsample.py`): passthrough when `n >= len`, exactly
      `n` points otherwise, first/last always kept, indices strictly increasing, a deliberate
      spike survives (the whole point of area-based downsampling over naive striding).
- [x] **`GET /api/series?metrics=a,b&from&to&points=N`** (`catch/api/routes_analytics.py`):
      refactored `/api/trends`'s per-metric fetchers into one shared `_metric_series`, then
      added an in-process cache (`_series_cache`, keyed by metric name only — the DB scan is
      the expensive part, not the cheap per-request range-filter + LTTB that follows) that
      caches each metric's *full* history. Invalidated from one place, `invalidate_series_cache()`,
      called at the end of `recompute_scores` (`catch/sync/scoring.py`) — already the single
      choke point run after every sync/backfill/settings-PUT/note-POST/coach-memory-write, so
      no call site needed its own "did history change" logic. 8 endpoint tests
      (`tests/test_api_series.py`): unknown-metric 400, passthrough under budget, real
      downsampling over budget (exact `n` back, bounds bracket the value, first/last dates
      kept), `from`/`to` windowing, multi-metric in one call, empty-series shape, and the cache
      actually invalidating after `recompute_scores`.
- [x] **`GET /api/erg/{id}/strokes`** gained optional `points`/`distance_min`/`distance_max` —
      downsamples only the chart's own `strokes` array (LTTB on `distance_cum`→`pace_500m`,
      watts/rate/hr carried through on the same chosen strokes so every line stays x-aligned);
      `technique_by_interval`/`interval_summary` are still computed over every stroke
      regardless, since those were already correct and a downsampled technique calc would be a
      *different*, wrong number, not just a lower-resolution one. The three new params are
      plain `int | None = None`, not `Query(...)` — `catch/coach/tools.py`'s `get_workout`
      calls this function directly (not through a request), and an unresolved `Query()` object
      would otherwise be passed through as the literal value of `points` on that path (a real
      bug caught by the existing coach-tools test suite, not written for this session). 5 new
      tests (`tests/test_api_erg_downsample.py`).
- [x] **`web/src/lib/useChartInteraction.ts`**: the one shared gesture engine for every chart —
      pointer-based pan with direction-lock (first ~6px of movement decides horizontal-pan vs.
      let-the-page-scroll, matching interaction spec #1), two-finger pinch-to-zoom (tracked via
      a `Map<pointerId, {x,y}>`, not a gesture-specific browser API, so the same code path
      handles touch and a trackpad's synthesized pointer events), ctrl/cmd+wheel zoom centered
      on the pointer, keyboard (arrows pan, +/- zoom, Home/End jump to the data's ends, Esc
      resets), tap vs. double-tap/double-click disambiguation, and a press-and-hold vs. drag
      distinction for touch. **Controlled, not stateful**: the hook takes `domain` as a prop and
      calls `onViewChange`/`onSettled` rather than owning its own React state — the only way
      sibling charts can share one pan/zoom position (Trends' linked main-metric-chart +
      weekly-volume-bars, interaction spec #6) is for a common ancestor to own that state and
      hand it down, so the hook had to be built controlled from the start rather than retrofitted.
      `onViewChange` is rAF-throttled internally; `onSettled` (gesture end) is the one callers
      should hook data-fetching/URL-writes to — see the live/settled split below.
- [x] **`web/src/lib/chartRange.ts`**: pure preset↔URL-querystring helpers (7d/4w/12w/6m/1y/
      season/all, "season" reusing `lib/dateRanges.ts`'s existing most-recent-past-September-1st
      definition so the two don't quietly disagree), dependency-free so they're unit-testable
      without mounting a component. 17 Vitest tests (`chartRange.test.ts`) — preset→day-count,
      `presetToDomain` against a fixed `now`, zoom-span clamping, and the full parse→write→parse
      URL round-trip including "a preset always clears from/to and vice versa" and "unrelated
      query params survive a write." `web/package.json` gained a `test` script and `vitest` as a
      devDependency — this project had no frontend test runner before this session.
- [x] **`ChartNavigator.tsx`**: the overview strip (a thin backdrop sparkline of the metric's
      full history, memoized against it rather than the live view domain — see the perf section
      below) with a draggable body (pans) and two draggable edges (re-zooms), plus a background
      click that re-centers the window — its own small pointer-event state machine, not a reuse
      of `useChartInteraction` (a brush drags a rectangle *over* the data, not the data itself).
- [x] **Every chart rewritten onto the shared hook**: `TrendLineChart` (now a real
      date-timestamp x-scale instead of index-based spacing, a min/max band from the
      downsample response, coach-memory annotations — vertical lines for races/2k-tests, A-races
      emphasized, taper windows shaded 14 days out reusing `next_a_race`'s own window so there's
      only one definition of "taper" in the codebase, aria-live range announcements),
      `WeeklyVolumeBars` (time-scaled instead of one-slot-per-week, so it can share Trends' axis
      with the metric chart above it), `ErgChart` (distance-domain pan/zoom, synced with
      `IntervalTable` via `hoveredInterval` lifted to `WorkoutDetailPage` — hovering a rep
      highlights its span on the chart and vice versa, interaction spec #8). `ChartZoomButtons`
      (shared +/- /reset row, 44px touch targets) and crosshair tooltips (nearest-point lookup
      per series, not a shared index — downsampled series don't share x-positions) are common
      to all three.
- [x] **Today's HRV/resting-HR sparklines expand into a full interactive chart in a Radix
      dialog** (`VitalsCard.tsx` + a new `ExpandedTrendChart.tsx`), `React.lazy`-loaded so
      `TrendLineChart`/the interaction hook stay out of Today's eager bundle (Today is the one
      route that isn't code-split, for the offline shell).
- [x] **Trends/Body wired to `/api/series`** with TanStack Query's `keepPreviousData` (never a
      blank chart mid-pan) and a visible-range-plus-one-screen-of-padding fetch window. The
      points budget itself is seeded from a representative constant (600px for Trends/Body,
      640px for the erg chart), not each chart's own `ResizeObserver`-measured width — that
      measurement happens inside the chart component, and the page (which owns the query) would
      need more plumbing to see it. Not wrong — LTTB still returns a valid result either way —
      just not as precisely tuned to the real device width as the task's DATA #3 asked for;
      worth wiring up properly if a narrower/wider-than-600px real device ever makes the
      mismatch visible. Range state lives in the URL (`?range=12w` or `?from=&to=` for a custom
      pan/zoom — mutually exclusive, enforced by `writeChartUrlState`), `replace: true` so
      panning doesn't spam the browser's back-button history.
- [x] **Global pinch-zoom disabled page-wide, chart surfaces excepted**: viewport meta gained
      `maximum-scale=1, user-scalable=no`; `html body { touch-action: pan-x pan-y }` (blocks
      pinch, keeps scrolling) with `button, a { touch-action: manipulation }` and
      `input, select, textarea { font-size: 1rem }` (16px — iOS's auto-zoom-on-focus threshold;
      verified computed-style 16px on all 16 Settings fields); `main.tsx` preventDefaults
      `gesturestart`/`gesturechange`/`gestureend` and a 2+-touch `touchmove` ({passive:false},
      required or preventDefault is silently ignored) — but only when the event target is
      outside a `[data-chart-surface="true"]` element, so charts keep handling pinch themselves.
      See DESIGN.md's new "Chart touch-action" note for why chart surfaces are `pan-y`, not
      `none` — resolves a real contradiction in the task spec (interaction #1's "vertical drags
      must still scroll the page" vs. #11's `touch-action: none` suggestion for chart surfaces).
- [x] **Quality bar**: screenshotted at 390px/1280px, both themes, Playwright MCP, across the
      first pass and again after the advisor review's fixes — the second round caught and fixed
      a real range-picker overflow at 390px ("All" clipped off-screen; see the bug log).
      CPU-throttled (4x, via a raw CDP `Emulation.setCPUThrottlingRate` session) pan frame-time
      measurement, done three times before trusting a number (see the bug log for why the first
      two attempts were wrong, not just imprecise): dispatching `PointerEvent`s directly and
      awaiting one `requestAnimationFrame` per move (not `page.mouse.move()`, whose own
      OS-level dispatch overhead dominates under CDP throttling), panning *backward in time*
      from a genuinely zoomed-in `1y` window into the 3 remaining years of mock history (not
      from `all`, which has zero room to pan in either direction once fully zoomed out — the
      first "4-year chart" number was actually a measurement of a stationary chart). Real
      result: **p50 ≈ 9ms** (typical frame, well inside budget) with **periodic spikes to
      ~80-100ms** roughly every 100-150ms of continuous dragging under 4x throttle — a real,
      confirmed cost (not a `page.mouse.move()` artifact; a control run on a chart-free page
      showed none), tracked to React re-rendering the full chart tree (up to ~1200 points'
      worth of path-string building, plus sibling components) on every settled frame rather than
      only updating a transform during the gesture and re-pathing once on settle. A targeted fix
      (extracting/memoizing the metric and range picker button rows so they at least stop
      re-rendering during a pan) didn't move the number — the real cost lives in the chart's own
      per-frame work, not its siblings — so the deeper fix (the "move a `<g>` via CSS transform
      during the gesture, rebuild the real SVG path only on settle" pattern) is logged as a
      known gap below — a deliberate scope call (a genuine rendering-architecture change, not a
      bug fix) rather than an oversight. In practice this
      means a sustained multi-frame drag through a year+ of history may show brief stutter on a
      genuinely throttled device; a short pan, or the common case of panning within a
      preset-sized window, stays smooth (p50 ≈ 9ms throughout every measurement taken). Bundle
      sizes from a real `npm run build`: initial/eager JS **155.9 KB + 18.6 KB (api.ts/mock.ts)
      ≈ 174.5 KB gzip** (budget 250 KB, ~75 KB of margin left); every chart/interaction file is
      its own lazy chunk, 0.9–5 KB gzip each, loaded only by the route (or Today's dialog) that
      needs it.
- [x] **Tap a workouts-series point to open that workout** (interaction spec #4, added in the
      advisor-review pass — the first pass left `TrendLineChart`'s `onPointTap` prop wired into
      the gesture hook but never actually passed by any page): `_w_per_kg_trend`/
      `_predicted_2k_trend` (`catch/api/routes_analytics.py`) now carry `activity_id` per point
      (`/api/series` already passed through any extra per-point key, so no endpoint change
      needed beyond adding the field); `Trends.tsx`/`Body.tsx` pass `onPointTap` only for those
      two metrics, navigating to `/workouts/{activity_id}`. New backend test asserting the id
      survives downsampling (`test_series_w_per_kg_carries_activity_id_for_tap_to_open`);
      verified live in Playwright (a real click on a W/kg chart point navigated to
      `/workouts/1041`, the mock's deterministic id for that point).
- [x] **Library decision**: extended the existing hand-rolled SVG pattern with the shared
      `useChartInteraction` hook, as the task's fallback plan — no new charting dependency
      needed or proposed. Matches session 4's original reasoning (CSS-custom-property theming
      doesn't translate to canvas) and its explicit "revisit only if hand-rolled SVG can't
      reasonably do zoom/pan over thousands of points" — it could, once downsampling moved
      server-side.
- [x] PLAN.md + DESIGN.md (new "Interaction patterns" section) updated + commit.

## Bugs found in the first pass's own testing, not just read for plausibility

- **A CPU-throttled pan perf test's first run showed real-looking jank** (p95 ≈ 175ms, max ≈
  417ms, via `page.mouse.move()` + a 4x CDP throttle) that traced back to a real bug: `Trends.tsx`
  computed its TanStack Query's `from`/`to` directly from the *live*, every-pan-frame `domain`
  state, so the series query's cache key changed on nearly every pointermove — a new fetch
  attempt roughly once per frame during a drag, not just at the end of the gesture. **Fixed** by
  splitting each page's domain into a live `domain` (feeds the chart's x-scale every frame) and a
  `queryDomain` (only updated from the hook's `onSettled` callback) — applied to `Trends.tsx`,
  `Body.tsx`, `WorkoutDetailPage`, and `ExpandedTrendChart.tsx`, plus a matching
  `onChangeSettled` added to `ChartNavigator` (previously it had no "drag finished" signal at
  all, so a brush-drag never committed to the URL or re-fetched once released). Chasing the
  remainder found two more real inefficiencies — `fullDomain` was a fresh object literal on
  every render in all four places (defeating every downstream `useMemo`/`useCallback` that took
  it as a dependency, including inside the shared hook itself), and `TrendLineChart`/`ErgChart`
  kept rendering Framer Motion's `motion.path` (with real per-frame overhead even for a no-op
  animation) on every pan frame instead of a plain `<path>` once the one-time mount draw-in had
  finished. Fixed both. **The specific numbers reported at the time (max dropping 417ms→160ms)
  turned out to be measuring mostly `page.mouse.move()`/CDP-throttle dispatch overhead, not real
  app cost** — see the advisor-review entry below for the corrected methodology and the real
  number; the underlying fixes in this entry were still real and are kept.
- **`GET /api/erg/{activity_id}/strokes`'s new `points`/`distance_min`/`distance_max` params
  broke two existing coach-tool tests** the moment they were added as `Query(...)`-wrapped
  FastAPI params: `catch/coach/tools.py`'s `get_workout` calls `routes_analytics.erg_strokes()`
  as a plain Python function (not through a request), so the unresolved `Query(...)` object —
  not its default value — was passed through as `points`, then compared with `>` against an
  `int` and raised `TypeError`. Fixed by making the three new params plain `int | None = None`
  with manual clamping in the function body instead of relying on FastAPI's `Query()` validation.
- **A left-edge navigator/bar-chart sliver turned out to be correct, not a bug** — a screenshot
  review flagged what looked like a stray 1px vertical line at the left edge of
  `WeeklyVolumeBars`; `browser_evaluate`-inspecting the actual `<rect>` elements showed its `x`
  was legitimately negative (a week whose start is before the visible domain but whose end is
  inside it, clipped by the viewBox) — accurate partial-bar rendering for an edge week, not a
  positioning bug. Left unchanged, logged here specifically so it isn't "fixed" again later by
  someone trusting a screenshot over the data.

## Bugs the advisor review caught (second pass) — all confirmed empirically, then fixed

The first pass's own PLAN.md entry above already claimed "critiqued and fixed across two
rounds" and a "p50 ≈ 20ms, p95 ≈ 24ms, max ≈ 26ms" perf number on "a full all-time (4-year)
chart." Both claims were false, and an advisor review that treats "I tested it" as a claim to
verify, not a fact to repeat, caught them along with four more real bugs — all six confirmed by
reproducing the exact failure before touching any code, then re-verified live after the fix:

- **Cold-loading `?range=all` (or `1y`/`6m` — anything wider than 84 days) silently collapsed to
  a 12-week window.** `initialDomain` was computed from `earliestMs`, which falls back to
  "now − 84d" until the metric's full-history query resolves — but it only fed a `useState`
  initializer, which runs exactly once, so the real earliest date arriving after mount never
  updated anything. Confirmed by reading a live chart's `aria-label` after `goto('…&range=all')`
  plus a wait: it said "Aug 9 to Nov 1" (84 days), not the real ~4-year mock history. Also meant
  the first pass's own "CPU-throttled pan on a 4-year chart" perf claim was never actually
  measuring 4 years of anything. **Fixed**: a new effect in `Trends.tsx`/`Body.tsx`/
  `ExpandedTrendChart.tsx` re-derives the domain from the URL's preset the moment the real
  `earliestMs` becomes known (guarded so it never fires again, and never fights an explicit pan).
  Re-verified: `?range=all` now shows a real ~1460-day span (`ChartNavigator`'s
  `aria-valuemin`/`-valuemax` confirmed it directly, not just the truncated date label).
- **`WeeklyVolumeBars`' own zoom-clamp silently overrode Trends' "7d" preset back to 28 days.**
  It hardcoded `minSpan: WEEK_MS * 4` while sharing a domain with `TrendLineChart` (7-day
  minimum) — picking "7d" set a 7-day domain, which `WeeklyVolumeBars`' own
  `useChartInteraction` instance then clamped back up to 28 days on its next render, via the
  hook's own out-of-bounds correction effect, fighting the chosen preset. **Fixed**: `minSpan`
  is now a prop (default `WEEK_MS * 4` for standalone use), and `Trends.tsx` passes the same
  `7 * DAY_MS` to both charts. Re-verified: `?range=7d`'s `aria-label` now reads "Oct 25 to Nov
  1" (exactly 7 days) and the URL stays `range=7d` instead of silently rewriting itself.
- **Ctrl/cmd+wheel zoom didn't actually stop the browser's own page zoom.** React's `onWheel`
  prop is registered as a *passive* listener, so `e.preventDefault()` inside it is silently
  ignored — confirmed by Chrome's own console warning ("Unable to preventDefault inside passive
  event listener invocation") the moment a real `WheelEvent({ctrlKey:true, cancelable:true})`
  was dispatched and `defaultPrevented` read back as `false`. A trackpad pinch (which Chrome/
  Firefox synthesize as ctrl+wheel) would have zoomed the whole page right alongside the chart.
  **Fixed**: `useChartInteraction` now attaches wheel handling as a *native*,
  `{passive: false}` listener via `addEventListener` on the chart's own DOM node
  (`surfaceRef`), not React's synthetic prop. Re-verified: the same dispatch now reports
  `defaultPrevented: true`, and the passive-listener console warning is gone.
- **Reset (double-tap/double-click/Esc) always snapped back to 12w, never "the preset you
  actually had selected."** `resetDomain` read `urlState.preset ?? "12w"` — but the URL's own
  preset clears to `null` the instant the user pans/zooms (a custom `from`/`to` takes over), so
  by the time anyone presses Esc after panning, `urlState.preset` is already gone and the
  fallback always wins. A first-pass Esc test against the untouched 12w default "passed" only
  because it never panned away from the thing it was about to reset to. **Fixed**: each page now
  tracks `lastPreset` in its own state, set only on an explicit preset-button click, and reset
  uses that instead. Re-verified: select `6m` → pan via keyboard → confirm the URL is now a
  custom `from`/`to` → press Esc → confirm the URL is back to `range=6m`, not `range=12w`.
- **Crosshair/zoom-center position was off by the left-axis-label margin (`PAD_X`).**
  `pxToDomainValue` divided by the chart surface's *full* `rect.width` (including the ~36px
  label gutter the data doesn't occupy), when the data itself only spans
  `[PAD_X, PAD_X + plotWidthPx]` of that same width — every tap/hover/zoom-center position was
  shifted by roughly that many domain-pixels, worst near the left edge. **Fixed**: the hook now
  takes an explicit `padLeft` and divides by `plotWidthPx` (the actual plot area), not the full
  surface width; all three charts pass their own `PAD_X`.
- **`setPointerCapture` could throw and silently abort the rest of a pointerdown handler.** Found
  while testing tap-to-open with a synthetic `PointerEvent` (which has no real active pointer for
  the browser to capture — a `NotFoundError`), surfaced as an uncaught exception that stopped
  `onPointerDown`'s gesture-state setup partway through. Real user input always has a valid
  active pointer, so this wasn't reachable in practice, but an uncaught throw aborting gesture
  initialization is a bad failure mode regardless — wrapped both call sites
  (`useChartInteraction.ts`, `ChartNavigator.tsx`) in try/catch, cheap insurance either way.

Also addressed in the same pass, lower severity but real: the range-picker row had no
`flex-wrap` and clipped "All" off-screen at 390px (both `Trends.tsx` and `Body.tsx` now wrap,
verified via `scrollWidth === clientWidth`); the aria-live region re-announced the visible range
on every single pan frame instead of once per gesture (now debounced 400ms after `domain` stops
changing); an A-race marker used `--band-red`, which DESIGN.md reserves for recovery/strain
status only (now `--accent`); and extracting/memoizing `Trends.tsx`'s metric/range-picker
button rows (so they stop re-rendering during a pan) was attempted as a perf fix but measured
no improvement — kept anyway since it's a correct, harmless simplification, but logged here so
it isn't mistaken for *the* perf fix.

## A third pass: real bugs in the fixes themselves, plus the first real touch testing

A second advisor review of the second pass's own fixes — again verified empirically, not
re-read — found that the tap-to-open feature added in the second pass (`activity_id` on
w_per_kg/predicted_2k points) had its own real regression, and that a second bug existed in the
metric-switch path the second pass had only partly addressed. It also pushed for the one
category of testing genuinely missing up to this point: real touch gestures, not just mouse/
pointer events assumed to exercise the same code paths.

- **Tap-to-open broke double-tap-reset and press-and-hold-inspect on the same chart.**
  `useChartInteraction`'s tap handling fired `onTap` immediately on any non-moving pointerup,
  with no distinction between a quick tap, a held-then-released press, or the first half of a
  double-tap. On a tappable chart (w_per_kg/predicted_2k) this meant: the first tap of every
  double-tap navigated away before the second tap could ever register, making double-tap-to-
  reset unreachable there; and holding still to read the crosshair, then lifting your finger,
  also navigated away. Confirmed live: a real `page.mouse.dblclick()` on a w_per_kg point
  navigated to `/workouts/…` instead of resetting zoom. **Fixed**: a press held ≥350ms before
  release is now an inspect-hold, not a tap-candidate, at all; a short tap's `onTap` is delayed
  350ms (the double-tap window) before firing, canceled if a second tap arrives in that window.
  Re-verified all three cases live: double-click now resets (URL stays on Trends, aria-label
  back to the 12w default) instead of navigating; a 600ms hold-then-release does nothing; a
  genuine single tap still navigates, just ~350ms later than before (confirmed via two checks
  100ms and 500ms after the click — URL unchanged at 100ms, `/workouts/1041` by 500ms). Also
  added a screen-distance check (tap must land within 20px of the point's actual rendered
  position) — before this, tapping *anywhere* on the chart, including empty space between two
  widely-spaced points, still "found" and opened the nearest one.
- **Switching metric while on a custom (panned) range broke the chart.** While the newly
  selected metric's full-history query is loading, `earliestMs` temporarily falls back to
  "now − 84d" — which can be *more recent* than wherever the user had already panned to.
  `fullDomain` (memoized off `earliestMs`) would briefly shrink past the user's current
  `domain`, and `useChartInteraction`'s own out-of-bounds-correction effect would then silently
  snap the live `domain` back inside the shrunk bounds via `onViewChange` — which updates the
  rendering domain but not `queryDomain` (the fetched data's window), desyncing the two.
  Confirmed live: loading `?from=2024-01-01&to=2024-06-01`, then clicking the HRV tab, produced
  a path with coordinates thousands of pixels outside the SVG's viewBox (the x-scale was
  rendering "Aug 9–Nov 1" while the actual fetched points were still the Jan–Jun 2024 window).
  **Fixed**: `fullDomain`'s lower bound now also includes `queryDomain.min` (the settled, not
  live, domain) in its `Math.min` — so it can never shrink below wherever the user has actually
  settled, even transiently during a metric-switch reload. Applied to `Trends.tsx`, `Body.tsx`
  (no metric switcher, but the same `allQuery`-refetch hazard applies generically), and
  `ExpandedTrendChart.tsx`. Re-verified live: the same repro now keeps the custom Jan–Jun 2024
  window and renders a correct HRV wave, not a broken one.
- **Real touch gestures had never actually been exercised — only mouse/pointer events,
  assumed (not verified) to cover the same `PointerEvent`-based code paths.** Tested via CDP's
  `Input.dispatchTouchEvent` (genuine touch synthesis, not `page.mouse.*`) at 390px:
  two-finger pinch on a chart zoomed it from an 84-day window down to the 7-day minimum clamp;
  a single-finger vertical drag on a chart scrolled the *page* (`window.scrollY` 0→403.5) while
  the chart's own domain stayed unchanged; a single-finger horizontal drag on a chart panned it
  (Aug 9–Nov 1 → May 26–Aug 18) while the page did not scroll. All three match the spec exactly
  and all three are now genuinely touch-verified, not just reasoned about from the Pointer
  Events abstraction. **Not independently re-verified on a real iOS/Android device** — this was
  Chromium's CDP touch emulation, which is a real step up from "never tested" but still not the
  same as a physical phone; see the existing "no real device" gotcha below.
- **A weight-chart tooltip was missing the secondary (smoothed) series value**, visible on
  inspection but not mentioned until checked directly against the spec's "every series' value"
  wording for the Inspect interaction. **Fixed**: `TrendLineChart`'s tooltip now shows the
  `secondaryKey` value (labeled "smoothed") alongside the primary one when present.
- **200%-text-size survival was checked, and failed — but not from anything built this
  session.** Setting `document.documentElement.style.fontSize = "200%"` on `/trends` at 390px
  produces real horizontal overflow (`scrollWidth` 500 vs. `clientWidth` 390); a screenshot
  traced it to the bottom navigation bar's row of icon+label items not wrapping or truncating,
  clipping the last item ("Body") off-screen. This is `AppShell`'s `BottomNav` component from
  session 3/4, unrelated to anything built this session (the metric/range picker pill rows
  wrap fine on their own) — logged here rather than silently left unfixed, but out of this
  session's scope to actually fix.
- **Escape inside Today's expanded-sparkline dialog closes the dialog, not the chart's zoom** —
  confirmed live (focus the chart, pan, press Escape via real `page.keyboard.press`, the dialog
  closes). Radix's `Dialog.Content` owns Escape for accessible-modal-closing before the chart's
  own `onKeyDown` gets a meaningful chance at it. **Deliberately not changed**: overriding
  Escape to reset zoom instead of closing a modal would violate the standard, expected modal
  convention (a user pressing Escape wants *out*), and reset is still reachable in that dialog
  via double-tap/double-click or the explicit reset (⟲) button. Documented as an intentional
  exception to "Esc resets" rather than either silently leaving it unexplained or making the
  dialog harder to close.

## A fourth pass: `ChartNavigator`'s own content didn't fill its own box

Two more concrete, falsifiable claims from a further review, both confirmed with a direct DOM
measurement before touching code (not just plausible-sounding) and both fixed:

- **The navigator/brush strip's visible content didn't actually fill its rendered box, at any
  width.** `ChartNavigator` used `width="100%"` (so the `<svg>` element always rendered at the
  card's real width) but a hardcoded `viewBox="0 0 600 36"` — mismatched aspect ratios, left to
  the default `preserveAspectRatio="xMidYMid meet"`, which *letterboxes* rather than stretches.
  Confirmed by comparing the SVG element's own `getBoundingClientRect()` against its backdrop
  `<rect>`'s: at 1280px the SVG box was 918px wide but its content rendered 600px wide, centered
  with ~159px of dead space on each side (clicking there did nothing useful, since the brush's
  pointer math assumes the full measured width maps to data); at 390px the *whole strip*,
  including its already-narrow resize handles, rendered at roughly 57% scale — about 20px tall
  instead of the intended 36px, confirmed by measurement, not assumed. **Fixed** by giving
  `ChartNavigator` the same `ResizeObserver`-measured-width pattern every other chart already
  uses, so the viewBox's width always equals the SVG's real rendered width — no aspect-ratio
  mismatch left for `meet` to reconcile. Also bumped the (invisible, transparent) resize-handle
  hit area from 10px to 20px for better touch grabbing. Re-verified at both 1280px (backdrop
  rect now exactly matches the SVG's own box: x=293, width=918 either way) and 390px (height
  back to a real 36px, handle hit-area a real 20px).
- **A tap's delayed `onTap` (added last pass specifically to let a second tap cancel it) could
  still fire during or after an unrelated drag started within that same window.** The cancel
  only lived in the double-tap branch of `endGesture`, which a drag never reaches —
  `onPointerDown` never checked for or cleared a still-pending timer from a *previous* gesture.
  Confirmed live: tap a w_per_kg point, wait 100ms (still inside the 350ms window), then drag —
  before the fix this would have navigated away mid-drag or immediately after; after the fix,
  the URL stays on Trends throughout and the pan commits normally. **Fixed**: starting any new
  single-pointer gesture now clears a stale pending-tap timer first.

- **Chart surfaces use `touch-action: pan-y`, not `none`.** The task's interaction #1 ("vertical
  drags must still scroll the page on mobile") and #11 ("chart surfaces `touch-action: none`")
  are in real tension — `none` would mean hand-rolling vertical scroll in JS to get #1 back, and
  losing the platform's momentum scrolling. `pan-y` lets the browser keep native vertical
  scrolling while the pointer-event handlers in `useChartInteraction` claim horizontal drags and
  pinch for themselves (via `preventDefault` once a gesture is direction-locked horizontal, or
  immediately for a 2-pointer pinch) — same net behavior as #1 asks for, verified in Playwright
  (`getComputedStyle` on a live chart's `<svg>` returns `pan-y`; `body`'s is `pan-x pan-y`).
  **Not verified on a real iOS Safari tab or an installed PWA** — only Playwright/Chromium
  emulation this session, consistent with every prior session's "no real device" caveat. A
  5-minute manual check worth doing on a real phone: pinch the page background (nothing should
  happen), pinch a chart (it should zoom), focus a Settings field (no auto-zoom).
- **`/api/series`'s cache is keyed on metric name only, not `(metric, range bucket, N)`** as the
  task's DATA #2 suggested — caches the metric's *full* history once, then does the (cheap,
  pure-Python) range-filter and LTTB-downsample per request against that cached series. Simpler
  than a 3-key cache and just as effective at avoiding the actual expensive part (the DB scan/
  join), since a 1GB Pi only ever holds `len(_ALL_SERIES_METRICS)` series in memory this way,
  not a combinatorial blow-up of every range×points pairing anyone's ever requested.
- **No live Pi/real-device verification this session** — all QA against `?mock=1` fixtures (a
  new ~4-year synthetic daily history and a ~60-minute/1700-stroke piece, added to `mock.ts`
  specifically so pan/zoom/downsampling had something realistic to exercise) via the Vite dev
  server and Playwright MCP, plus the real backend's pytest suite. The live account's actual
  history is still only a few weeks long (sessions 1–2's note), so the interactive-chart
  features most worth stress-testing (a true multi-year pan, the navigator brush over real
  gaps in history) have no real data to test against yet — worth a real walkthrough once more
  history accumulates.
- **`frontend-design` and `webapp-testing` skills still don't exist** in this environment's
  skill listing, same situation as sessions 3 and 5 — Playwright MCP tools were used directly
  for screenshots/critique/perf measurement instead.
- **`fetchTrends`/`mockTrend` (frontend) were deleted, not deprecated** — every caller moved to
  `fetchSeries`/`mockSeries` (this session), leaving them genuinely unused; `GET /api/trends`
  itself stays (still used server-side by `catch/coach/tools.py`'s `get_trends` tool and the
  MCP server), only its frontend client wrapper went away.
- **An upcoming race's marker/taper never appears on a chart, only on Today.** Every page's
  `fullDomain.max` is capped at `now` (so "all"/zoom-out clamping has a real, finite right edge
  to clamp against), which also means a race dated in the future — exactly the case a taper
  window matters for — can never be panned into view on Trends, even though
  `eventsToMarkers`/the taper-shading code would render it correctly if it ever were visible.
  Today's recommendation card already surfaces the next A-race's taper status prominently
  (`next_a_race`, session 5), so this isn't a silent gap in the app's behavior, just in this
  particular chart — worth extending `fullDomain.max` a few weeks forward for annotation
  purposes specifically (while keeping default *preset* views still ending at today) if it
  comes up again.
- **Several task-spec interactions were left unimplemented this session, not silently skipped**:
  - **Notes as small dots, tap for details** (annotation spec #7) — `eventsToMarkers` only maps
    `events` (races/tests) from `/api/coach/memory`, not `notes`. `/api/notes` only takes a
    single `?date=`, not a range, so this needs a new range-capable endpoint before the
    frontend side is even possible.
  - **Animated zoom transitions** (spec #10) — button/keyboard/preset-triggered zooms jump the
    domain instantly; only a live pan/pinch already feels smooth (it's driven by continuous
    pointer input, not a single state jump). Tweening a discrete zoom over ~200ms via
    `requestAnimationFrame`, gated on `prefers-reduced-motion`, is the straightforward fix.
  - **A loading-edge indicator and explicit adjacent-window prefetch** (DATA #3) —
    `keepPreviousData` means panning never shows a *blank* chart, which was the stated bar, but
    there's no visible "fetching more" edge treatment, and nothing explicitly
    `prefetchQuery`s the next padded window on settle (the padding itself gives real slack
    before a fetch is needed, which is most of what this interaction is protecting against, but
    not the same thing as prefetching).
  - **Hover/crosshair isn't linked across Trends' two charts** — panning/zooming them together
    works (one shared domain), but hovering the metric chart doesn't show a crosshair on the
    weekly-volume chart below it or vice versa. `hoverX` lives inside each chart's own
    `useChartInteraction` instance, not lifted to `TrendsPage`.
  - **Tapping an annotation marker for details doesn't work on touch** — races/2k-tests render
    as a `<title>` element (a native SVG tooltip, desktop-hover-only) rather than an actual tap
    target with a popover (name/date/priority/goal/result), so the spec's "tap a marker for
    details" only works with a mouse.
  - **The full "transform via CSS during the gesture, re-path only on settle" pan architecture**
    wasn't built — see the perf entry above. The current approach (re-render React with the new
    domain every settled frame) is adequate for normal use but is the reason periodic frame-time
    spikes remain under heavy CPU throttle on a long pan. Not re-measured under touch input
    specifically (only mouse-equivalent `PointerEvent` dispatch) — touch gestures were verified
    *functionally correct* (see the third pass below) but not re-profiled for frame time.

## Session 9 checklist

The task: session 8's chart touch interactions worked under every test run so far, but did
nothing at all on the user's real iPhone (Safari and the installed PWA, served from the Pi) —
exactly the gap session 8's own PLAN.md entries kept flagging ("Not verified on a real iOS
Safari tab or an installed PWA — only Playwright/Chromium emulation"). Fix it, add real-device
regression coverage, add service-worker update detection so a future fix like this one actually
reaches the phone, deploy, and hand back a verification checklist.

- [x] **Diagnosed by reasoning from a known class of WebKit behavior, not by reproducing the
      failure on a real device** — this session had no iPhone in hand, only the user's report.
      `web/src/lib/useChartInteraction.ts` was correct Pointer Events code, but it depended on
      `touch-action: pan-y` plus a direction-locked `preventDefault()` inside `pointermove` to
      claim horizontal drags/pinch away from native scrolling. That pattern has a real,
      documented gap on iOS Safari specifically: it does not reliably honor `preventDefault()`
      inside `pointermove`/`touchmove` to cancel a native gesture already under way the way
      Chromium does, which would also explain why session 8's Chromium-CDP touch testing never
      caught it. **Changed**: chart surfaces now use `touch-action: none` (full script control
      from the first touch, on every engine, no runtime race depending on when
      `preventDefault()` happens to be called), and the pointer handlers + `touch-action` moved
      off the `<svg>` itself onto its wrapping HTML `<div>` — SVG root elements have their own
      separate history of inconsistent `touch-action` support across engines, and a plain
      HTMLElement is the safer bet regardless. **Not yet verified against the user's actual
      phone** — that's the point of the checklist below; if touch still doesn't work there, the
      next step is a real device + remote debugging, not another round of reasoning from docs.
- [x] **Reimplemented vertical scroll in JS** (`useChartInteraction.ts`), since `touch-action:
      none` means the browser no longer does it for free: `window.scrollBy` per `pointermove`
      while direction-locked vertical, plus a small decaying-velocity fling on release so a fast
      swipe over a ~240px chart doesn't stop dead the instant the finger lifts. Touch-only —
      mouse never loses native scroll, since `touch-action` only ever governed touch.
- [x] **Press-and-hold (~300ms) is now a real third gesture mode**, not inferred from release
      timing after the fact: a stationary touch enters "inspect" at the threshold (crosshair
      follows the finger from then on), and release from inspect never fires a tap or a pan,
      regardless of subsequent movement. Below the threshold, the existing direction-lock (first
      ~6px) decides pan vs. the (now JS-driven) vertical scroll, same as before.
- [x] Two more real, independently-confirmed bugs in the gesture engine, fixed:
      **`setPointerCapture` was called on `e.target`**, which can be a different (and
      possibly-unmounting, e.g. the hover circle) element than the one meant to hold capture —
      changed to `e.currentTarget` everywhere (`useChartInteraction.ts`, `ChartNavigator.tsx`).
      **`onPointerCancel` was routed straight to the same handler as `onPointerUp`**, so an
      OS-level gesture interruption (e.g. an edge-swipe system gesture) could be misread as a tap
      or a double-tap. Given its own dedicated handler that only ever settles an in-progress
      pan/pinch and clears pending timers — never fires `onTap`/`onDoubleTap`.
- [x] **`main.tsx`'s legacy `gesturestart`/`gesturechange`/`gestureend` prevention is now
      unconditional**, not scoped around chart surfaces — a chart's own pinch runs entirely on
      Pointer Events against `touch-action: none` and never relied on these events to begin
      with, so exempting chart surfaces from them (session 8's design) only left room for
      Safari's native page-pinch-zoom to still engage concurrently over a chart.
- [x] **Real touch-device Playwright regression tests** (`web/tests/touch/`, `@playwright/test`
      added as a devDependency — build-time only, consistent with CLAUDE.md's "no Node at
      runtime" rule): a `mobile-gestures` project (Chromium + an iPhone 13 device profile,
      `hasTouch`/`isMobile`) drives real multi-touch via CDP's `Input.dispatchTouchEvent`
      (`tests/touch/cdpTouch.ts`) — Playwright's own WebKit bindings only expose a single-point
      `touchscreen.tap()`, no move, no multi-touch, so pan/pinch/hold needed this instead. A
      `mobile-webkit` project (real WebKit) runs 3 cross-engine tests (`basic.spec.ts`): computed
      `touch-action: none` on every chart surface, the page body still allowing native
      `pan-x pan-y` scroll, and a real `touchscreen.tap()` on a tappable point that asserts
      actual navigation (not just "the chart is still on screen afterward" — that would pass
      even if touches were silently swallowed, the original bug). 7 gesture tests
      (`charts.spec.ts`, Chromium-only — Playwright's WebKit can't drive these): touch-action
      computed style, a horizontal drag pans without scrolling the page, a vertical drag scrolls
      the page without panning the chart, a pinch narrows the visible range, a ~500ms hold shows
      the crosshair tooltip without panning or navigating, a quick tap on a tappable (W/kg)
      point navigates to that workout, a cancelled tap (`touchcancel`) never navigates — run
      against the dev server's `?mock=1` fixtures (no backend needed). Worth noting plainly:
      most of these Chromium tests also pass against session 8's original `pan-y` code (CDP
      touch emulation never reproduced the real bug to begin with) — only the computed-style
      assertions and the WebKit tap-to-navigate test would actually catch a revert back to
      `pan-y`/SVG-level handlers. `web/vite.config.ts` gained a scoped `test.include` (Vitest
      would otherwise also try to run these Playwright specs under its own runner and fail
      immediately on `test.beforeEach`'s different signature).
- [x] **A real, reproducible test-infrastructure flake, root-caused as far as it goes**: the
      metric-switch tap tests failed consistently (not occasionally) whenever point-selection
      used `expect.poll`-based waiting, and passed reliably (15+ consecutive runs, including
      bypassing the Playwright test runner entirely with raw `chromium.launch()` scripts) with a
      fixed `waitForTimeout` in its place — confirmed by hand that the underlying tap mechanism
      itself (`pointerdown` -> delayed `onTap` -> `navigate()`) is correct every time regardless
      of which wait strategy was used, isolating the flakiness to something about repeated
      `locator.getAttribute()` polling perturbing timing enough to matter, not a touch-handling
      bug. The exact mechanism wasn't fully pinned down; `selectMetricAndWaitForStableChart` uses
      the fixed wait, and the two metric-switch tap tests also carry Playwright's own per-test
      retry (2) as cheap insurance, logged honestly rather than silently trusted.
- [x] **Service-worker update detection** (`web/vite.config.ts`'s generated `sw.js`,
      `web/src/lib/useServiceWorkerUpdate.ts`, `web/src/components/shell/UpdateToast.tsx`):
      session 8's `sw.js` called `self.skipWaiting()` unconditionally on install, so a new
      deploy silently took over an already-open tab's fetch handling with no warning and nothing
      for a client to ever detect as "waiting." Fixed: install no longer skips waiting; a new
      `message` listener skips only on an explicit `SKIP_WAITING` postMessage. The new hook
      registers with `updateViaCache: 'none'`, watches `registration.waiting`/`updatefound`, and
      shows `UpdateToast` ("New version available — tap to reload", mounted outside the auth
      gate so it's visible even on the login screen) once a worker is installed-but-waiting
      behind an existing controller; tapping it posts `SKIP_WAITING`, and `controllerchange`
      reloads once (loop-guarded). A `visibilitychange` listener calls `registration.update()` —
      an installed iOS PWA resumes from the background without ever navigating, so without this
      it would never re-check for a new `sw.js` until the next cold launch from the springboard
      icon. `activate` now purges the API cache too, not just old shell caches, so a newer
      build's JS can't be handed an older build's cached JSON shape while offline.
      `catch/main.py` gained `_no_cache_headers_for()`: `sw.js`/`index.html` are served with
      `Cache-Control: no-cache` (the two files a client needs a genuinely fresh copy of to
      notice a new deploy at all), everything under `/assets/*` stays normally cacheable (hashed
      filenames already bust cache per build). New test (`tests/test_main_static.py`).
- [x] **A visible build ID**, so the phone checklist below can tell "the fix didn't reach this
      device yet" apart from "the fix didn't work": `vite.config.ts` computes one `BUILD_ID` per
      build, used for both `sw.js`'s `VERSION` and a `define`d `__BUILD_ID__` the client bundle
      embeds; Settings shows it as small muted text at the page bottom.
- [x] **A real bug in the update flow itself, caught by an advisor review before this ever
      reached a phone**: `useServiceWorkerUpdate.ts`'s `controllerchange` listener had no way to
      tell a genuine update apart from a brand-new install — `clients.claim()` fires
      `controllerchange` on the very first install too (no previous controller), which would
      have reloaded the page unprompted on anyone's first visit, or after clearing site data,
      possibly mid-password on the login screen. Fixed with a `weRequestedSkipWaiting` flag set
      only inside `reload()` (the toast's own tap handler) — `controllerchange` now only acts on
      a reload *we* asked for.
- [x] **A second real bug from the same review**: the momentum fling on vertical-scroll release
      used `lastMoveVelocityPxMs` unconditionally, including when a finger had stopped moving
      before lifting (common) — flinging a swipe that had already come to rest. Fixed: zeroes
      the fling if the last recorded move is more than ~50ms stale.
- [x] **`ChartNavigator.tsx`'s handlers were still on its `<svg>`**, inconsistent with the "move
      handlers + touch-action onto a wrapping HTML div" fix applied everywhere else this
      session, for the same WebKit-SVG-touch-action-gap reason. Wrapped it the same way; pointer
      capture (set per-handle-rect, unchanged) still bubbles up through the new wrapping div
      exactly as it did through the `<svg>` before.
- [x] `DESIGN.md`'s "Chart touch-action" note rewritten for the `pan-y` -> `none` reversal and
      the new press-and-hold-as-a-mode behavior, with the "diagnosed, not reproduced on a real
      device" caveat stated plainly. `CLAUDE.md` layout/commands updated (chart/shell/lib
      additions, the new `web/tests/touch/` tree, `npm run test:touch`, `./deploy.sh`).
      PLAN.md + commit.
- [x] **Deployed to the real Pi** (`./deploy.sh` against `opensky-pi`) — see "Real verification"
      below. **Note**: the working tree also carried pre-existing, unrelated uncommitted changes
      from an earlier session (icon/favicon regeneration, a Memory-page date-field style tweak)
      that this session didn't touch, didn't commit, and deliberately left alone rather than
      stash or discard — `deploy.sh` builds from the working tree, so those shipped to the Pi
      too. The Pi is therefore not sitting at exactly this commit; it's this commit plus that
      uncommitted frontend work.

## Real verification (2026-11-01)

- Confirmed via `ssh opensky-pi` before touching anything that session 8's interactive-charts
  commits were already the live deployed build (`grep -l data-chart-surface
  /opt/catch/app/catch/api/static/assets/*.js` matched), ruling out "stale build" as the
  explanation for "does nothing on my phone" before spending any time on code.
- `uv run pytest` — 223 passed. `cd web && npx tsc -b && npm run build` — clean, initial bundle
  still ~489KB raw / ~156KB gzip (within the 250KB gzip budget). `cd web && npm run test`
  (Vitest) — 17 passed, now cleanly separated from the Playwright specs. `cd web && npx
  playwright test` — 13 of 20 run (7 correctly skipped: WebKit can't drive the 7 multi-touch/move
  tests), all 13 passing, reconfirmed across 9 repeated full runs this session (several under
  `--workers=1`) with zero flakes once the `expect.poll` fix above landed — including 3 full runs
  after the second (advisor-caught) round of fixes below, so those didn't just trade one flake
  for another.
- `./deploy.sh` against the real Pi, twice (once per round of fixes): frontend build, rsync,
  `uv sync --frozen` (aarch64 wheels, no compiling — same as session 7), `systemctl restart
  catch.service`, health check passed both times. Confirmed live afterward, not just assumed
  from the script's own "Healthy" line: `curl` from the Pi itself to `127.0.0.1:8000/sw.js` and
  `/` both show the new build's real `VERSION`/no-cache headers (`cache-control: no-cache`, vs.
  no such header on a hashed `/assets/*.js`), and the new build's `TrendLineChart` chunk contains
  `touch-none`.
- **Not yet verified against the user's actual iPhone** — this session had no access to one.
  [Fill in after the phone checklist below is actually walked: real Safari-tab and
  installed-PWA touch results, and whether the build ID on the phone's Settings page matches
  this deploy's.]

## Session 10 checklist

The task: two real bugs reported from the live Pi deployment (session 9's touch fix had
nothing to do with either). (1) Today shows "looks like you're offline" while fully online with
fresh data. (2) the installed iPhone PWA keeps running an old build, despite session 9 having
apparently already built correct-looking skipWaiting/clients.claim/update-toast logic.

- [x] **Bug 1's real cause, and why it has nothing to do with connectivity**: Today.tsx compared
      `/api/today`'s `date` field against `new Date().toISOString().slice(0, 10)` — the server's
      own-timezone `date.today()` versus the browser's *UTC*-sliced date string. Those two
      strings disagree for several hours a day whenever the client and the Pi aren't in the same
      timezone, which is unrelated to whether the network is actually up — exactly the "online
      with fresh data" report. **Confirmed, not just reasoned from the code**: `ssh opensky-pi
      'timedatectl'` shows the Pi runs `America/New_York`, 5 hours behind UTC — so for roughly
      5 hours out of every day (evening in New York, already past midnight UTC), the server's
      `date.today()` and the browser's UTC-sliced date string name two different calendar days,
      regardless of connectivity. **Fix**: deleted the date-string comparison outright.
      `/api/today` now also returns `generated_at` (a real UTC timestamp,
      `routes_analytics.py`), and Today shows real data age from that instead of inferring
      staleness from a date mismatch.
- [x] **A real online/offline signal** (`web/src/lib/useOnlineStatus.ts`): `navigator.onLine`
      only reflects whether a network interface is up at all — true on a LAN with no route to
      the Pi, true behind a captive portal — so it's used only as a trigger to re-probe
      (`refetchOnReconnect`), never as the answer. The actual signal is a direct `/api/health`
      probe (`cache: 'no-store'`, a 4s `AbortController` timeout), re-run on mount, on a 15s
      interval, and on window focus/reconnect. Only a rejected/timed-out fetch counts as
      offline; any response that actually arrives (even a 5xx) means the network path to the Pi
      works. The service worker routes `/api/health` network-only with **no cache fallback at
      all** (see Bug 2 below) specifically so this can never be answered by a stale cached `"ok"`
      while genuinely offline — without that, the old network-first-with-cache-fallback routing
      every other `/api/*` route used would have silently defeated this exact fix. Verified that
      routing actually matters, not just reasoned from reading the code: a Playwright test
      (`web/tests/update/update.spec.ts`) fetches `/api/health` once while a real registered
      service worker is controlling the page, then has `server.mjs` destroy the socket on the
      next request and asserts the fetch now rejects — and, as a mutation check, temporarily
      removing `/api/health` from `sw.js`'s `NEVER_CACHE` list made this specific test fail (the
      fetch resolved instead of rejecting), confirming it actually exercises the fix rather than
      passing regardless (session 9's "vacuous test" lesson). Also requires **two consecutive**
      probe failures before reporting offline, not one — a single slow request (e.g. a sync job
      briefly pegging the Pi 3's one core) flipping the banner would just be moving the original
      complaint to a flakier trigger, not fixing it; `?mock=offline` bypasses this debounce
      (it's a deterministic scenario, not network flakiness, and waiting out two real poll
      intervals would make that test unnecessarily slow).
- [x] **Confirmed, not just assumed, that a single source's sync failure was already a per-card
      notice and not routed through the global banner**: `RecommendationAndSync.tsx`'s sync-status
      list already renders a red dot + "failed" per source (e.g. Concept2), independently of
      Today's banner, and `run_sync` (`catch/sync/scheduler.py`) already catches every sync
      exception internally and always returns 200 — so a failed source can never throw out of
      `triggerSync`'s sequential loop either. Nothing needed changing here; worth recording so a
      future session doesn't "fix" something that was already correct.
- [x] **`?mock=offline`** added to `MockScenario` (`mock.ts`) — real device data, just hours old,
      so the banner's "real data age" text has something to demonstrate without a backend.
- [x] **Bug 2's actual fix: dropped session 9's whole waiting-worker/SKIP_WAITING-message design**,
      not patched it. That design's update *detection* depended on `registration.waiting`/
      `updatefound`/`controllerchange` firing in a specific order and on a specific timeline —
      session 9's own code looked correct and still left the user's phone stuck on an old build,
      which is the whole reason not to keep trusting that timing as the only signal on real
      WebKit. The service worker's **caching** behavior (which still matters) is now a separate
      concern from update **detection** (which is now a plain poll):
      - `install` calls `self.skipWaiting()` unconditionally; `activate` deletes every cache
        except the current build's `SHELL_CACHE`/`API_CACHE` (both now versioned per build —
        `API_CACHE` used to be a fixed `'catch-api-v1'` name) and calls `self.clients.claim()`.
      - Fetch routing: `/api/health` and `/version.json` are **network-only**, no cache write, no
        cache fallback — ever. `/api/*` (everything else) is network-first with a cache
        fallback. Navigation requests are network-first, and now also keep the cached `'/'`
        offline-fallback fresh on every successful online load (it used to be frozen at whatever
        HTML existed the moment the SW was first installed, never refreshed again even though
        every online navigation took the network-first path). `/assets/*` (hashed, immutable) is
        cache-first. Everything else same-origin — manifest, icons, favicons, not content-hashed
        — is now network-first with a cache fallback; it was wrongly bucketed in with the hashed
        assets as cache-first before.
      - **Update detection is now `web/src/lib/useServiceWorkerUpdate.ts` polling
        `/version.json`** (written by `vite.config.ts`'s `serviceWorkerPlugin` alongside `sw.js`,
        served with the same `Cache-Control: no-cache` as `sw.js`/`index.html` —
        `catch/main.py`'s `_no_cache_headers_for`) on mount, a 60s interval, `visibilitychange`,
        and the `online` event, comparing its `build` field against the client bundle's own
        `__BUILD_ID__`. This is completely independent of whatever the service worker's
        install/waiting state happens to be doing — a version mismatch shows the toast
        regardless. `reload()` is now just `window.location.reload()`, not a
        postMessage-and-wait-for-controllerchange dance; the new SW (already active and
        controlling, having skip-waited on its own) serves the fresh reload correctly either
        way.
      - Settings shows `Build {__BUILD_ID__} · {__COMMIT__}` — `__COMMIT__` is a new
        `vite.config.ts`-time `git rev-parse --short HEAD`, `-dirty`-suffixed when the tree has
        uncommitted changes (which it did on this session's deploy too — see the note at the
        bottom of this checklist — so seeing `-dirty` on the Pi is the honest label, not a bug).
        `CATCH_BUILD_ID` env var can override the build id (used by the Playwright test below to
        get two deterministic builds instead of racing `Date.now()` across two fast builds).
      - A `vite:preloadError` listener triggers one guarded reload (a `sessionStorage` flag, not
        the in-memory one `reload()` itself uses, since it has to survive the reload) — Vite's
        lazily-imported route chunks are content-hashed, and `deploy.sh` rsyncs with `--delete`,
        so an already-open tab referencing an old hash can 404 once a new build has shipped over
        it.
- [x] **A real, honestly-documented migration gap for this one upgrade only**: the phone's
      *currently* running JS is session 9's message-based design, which expects a worker to sit
      in `registration.waiting` and only reload once *it* sends `SKIP_WAITING`. This new
      `sw.js`'s `install` skip-waits on its own instead, so by the time the old JS's toast shows
      up and the user taps it, the `controllerchange` that old code is waiting for has usually
      already fired on its own (the new worker activated and claimed clients without waiting for
      anyone to ask) — the tap can do nothing. If that happens on this one deploy, a manual
      force-quit/relaunch (or a plain pull-to-refresh) still picks up the new build correctly
      regardless, since any fresh load is served by whichever SW is actually active. Every
      update *after* this one won't have this gap, since both sides will be running the new
      version-poll design.
- [x] **Playwright update-flow test** (`web/tests/update/`, its own `playwright.update.config.ts`
      — separate from the touch suite's, since the dev server never emits `sw.js`/`version.json`
      at all, only `vite build`'s `writeBundle` does): `globalSetup.mjs` builds two real
      production bundles with distinct `CATCH_BUILD_ID`s into gitignored scratch dirs; a small
      in-process static server (`server.mjs` — deliberately not `catch.main`, which would start
      APScheduler against the real `.env` and violate "no live network calls in the suite")
      serves whichever one a test currently points it at, swappable without a restart so an
      already-open tab can be "deployed over." Four tests, one worker (shared mutable server
      state): a first-ever load shows no toast; swapping the served build and firing
      `visibilitychange` shows the toast, and tapping it actually lands on the new build *and*
      leaves only that build's cache names in `caches.keys()` (confirms versioned-cache deletion,
      not just the toast); the offline-mock scenario shows the banner with real data age while
      the healthy one shows nothing; and (added after an advisor review — see below) a real
      registered service worker lets a destroyed-socket `/api/health` request actually reject
      rather than resolving from cache, mutation-checked against `NEVER_CACHE`. Ran the full
      suite 3 times in a row with no flakes.
- [x] `uv run pytest` — 224 passed (223 at the end of session 9, +1 for `generated_at`'s
      freshness; the no-cache-headers test was renamed, not added, to cover `version.json` too).
      `cd web && npx tsc -b && npm run build` — clean. `cd web && npm run test` (Vitest) — 17
      passed, unchanged. `cd web && npx playwright test` (touch suite) — unchanged, 13 run / 7
      correctly skipped, all passing — this session's changes don't touch any of that code.
      `cd web && npm run test:update` — 4 passed.
- [x] `CLAUDE.md` updated (new `useOnlineStatus.ts`/`useServiceWorkerUpdate.ts` descriptions,
      `?mock=offline`, `web/tests/update/`, the new `npm run test:update` command). PLAN.md +
      commit.
- [x] **Deployed to the real Pi** — see "Real verification" below. Walking the checklist on the
      actual iPhone is still outstanding; that part of "Real verification" is a placeholder.

## Real verification (session 10)

- `uv run pytest` — 224 passed. `cd web && npx tsc -b && npm run build` — clean. `cd web && npm
  run test` (Vitest) — 17 passed. `cd web && npx playwright test` (touch suite) — unchanged, 13
  run / 7 correctly skipped, all passing. `cd web && npm run test:update` — 4 passed, including
  the real build-A→build-B detect-and-reload-and-cache-churn assertion and the destroyed-socket
  `/api/health` test, which an advisor review flagged as missing (the `?mock=offline` test
  bypasses the service worker entirely and can't exercise `NEVER_CACHE`'s actual effect) and
  which this session mutation-checked: temporarily dropping `/api/health` from `NEVER_CACHE`
  made exactly that one test fail, confirming it isn't vacuous.
- Also per that review: `ssh opensky-pi 'timedatectl'` confirmed the Pi runs `America/New_York`
  (not UTC) before PLAN.md stated the timezone-mismatch diagnosis as fact above, and every URL
  in the deployed `sw.js`'s `PRECACHE_URLS` was curled directly against the Pi's FastAPI and
  returned 200 (a single 404 there would make `install`'s `cache.addAll` reject, meaning the new
  service worker never installs at all and the phone silently keeps running session 9's).
- `./deploy.sh` against the real Pi, twice (once before the advisor-review follow-up commit
  above, once after — the second is what's actually live). Confirmed live afterward via `ssh
  opensky-pi`, not just the script's own "Healthy" line: `/api/health` returns `{"ok":true}`;
  `/version.json` returns `Cache-Control: no-cache` and
  `{"build":"mvyn2y3s","commit":"e3b4df4-dirty"}` (the `-dirty` suffix is correct — the
  pre-existing, unrelated uncommitted icon/favicon/`Memory.tsx` changes noted at the top of this
  session are still sitting in the working tree `deploy.sh` builds from, same as session 9);
  `/sw.js` and `/` both also show `Cache-Control: no-cache`; a hashed `/assets/*.js` request
  shows no such header (left to normal heuristic/ETag caching, correct per design since the
  filename itself changes per build); every `PRECACHE_URLS` entry in the deployed `sw.js` was
  re-curled against the Pi's FastAPI after this final deploy and returned 200; the deployed
  `sw.js` was grepped directly on the Pi and contains the versioned `API_CACHE`, the
  `NEVER_CACHE` list, the unconditional `skipWaiting()`, and `clients.claim()`.
- **Not yet verified against the user's actual iPhone** — this session had no access to one.
  [Fill in after the phone checklist is actually walked: whether the offline banner stays hidden
  while genuinely online, whether it appears with a sensible data age when the phone is actually
  offline, whether the update toast appears and a tap on it actually lands on the new build
  id/commit in Settings — including whether the one-time migration gap documented above (old
  JS's dead tap, since the phone's currently-running JS predates this session) actually happens,
  and if so whether a force-quit/relaunch resolves it as expected.]
