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

## Session 11 checklist

The task: the on-chart `+`/`−`/reset zoom buttons (`ChartZoomButtons`, interaction spec #2)
covered real data on a 390px phone — remove them, keep every other control. Also: a range
preset wider than the real history (e.g. "6m"/"All" when data only starts mid-October) should
start the x-axis at the first data point, not show empty months.

- [x] **Deleted `ChartZoomButtons.tsx`** and its usage in `TrendLineChart`, `WeeklyVolumeBars`,
      `ErgChart`. Every other control from the original spec already lived in
      `useChartInteraction.ts` and needed no new code: pinch/ctrl+wheel zoom, drag pan,
      double-tap/double-click reset, the navigator strip, the range presets, and
      `+`/`-`/arrows/Home/End/Esc on a focused chart. Added a keyboard hint to each chart's
      `aria-label` since the buttons were the only visible affordance for the same actions.
      DESIGN.md's "On-chart zoom buttons removed" note documents why, so a future session
      doesn't re-add them for spec-completeness.
- [x] **Fixed-span presets (4w/12w/6m/1y/season) now clamp their start to the real earliest data
      point**, same as "all" already did (`chartRange.ts`'s `presetToDomain` — it only clamped
      the `spanDays === null` branch before). A preset wider than the actual history now starts
      exactly at the first point instead of `now - spanDays`.
- [x] **A second bug in the same area, caught re-deriving this**: `Trends.tsx`/`Body.tsx` each
      have an effect that re-resolves the domain once the metric's real earliest date loads
      (needed because the mount-time `useState` initializer runs once, before that query
      resolves). It was gated on `if (!urlState.preset) return`, but a cold load with *no*
      `range` param also has `urlState.preset === null` — so the single most common entry point
      (no query string at all) never got the corrected domain, even after this session's
      earliest-clamp fix. Changed the gate to skip only on an explicit custom `from`/`to` pair,
      using `urlState.preset ?? "12w"` otherwise. Confirmed via a throwaway Playwright screenshot
      spec (390×844, iPhone 13 touch profile, mock history shortened to 19 days for this check
      only, reverted after) that `/trends?mock=1` with no params, `?range=6m`, and `?range=all`
      all now start at the real first data point.
- [x] **A third, independent bug found while verifying "keyboard +/-/Esc still work" (the user's
      explicit ask, since the removed buttons called the same `zoomIn`/`zoomOut`)**:
      `useChartInteraction.ts`'s `domainRef` mirror line (`domainRef.current = domain`) ran
      unconditionally on every render. Any keyboard action calls `commit(..., {settled: true})`
      outside of a drag, which synchronously fires `onSettled` (e.g. Trends.tsx's URL write) —
      triggering a parent re-render with the *old* `domain` prop before the `commit`'s own
      rAF-deferred `onViewChange` flush had a chance to fire. That re-render's mirror line
      stomped `domainRef.current` back over the just-committed value, so the pending rAF flushed
      the stale domain instead. Net effect: every keyboard zoom/pan silently updated the URL and
      the settled query but never the visible chart or its aria-label — confirmed broken, then
      fixed, via the same throwaway spec (RAF-SCHEDULED/RAF-FIRED tracing plus aria-label
      polling). Fix: skip the mirror write while a commit's rAF flush is still pending
      (`gesture.current.rafPending`). Locked in with two new permanent tests in
      `web/tests/touch/basic.spec.ts` (runs on both the Chromium and real-WebKit touch
      projects, full mock history, no temporary mock.ts edit needed): one presses `=` on a
      focused chart and polls for the aria-label to change, then presses `Escape` and polls for
      it to revert; the other asserts zero "Zoom in"/"Zoom out"/"Reset zoom" buttons exist
      anywhere.
- [x] Checked all four `TrendLineChart` hosts at 390×844 with an iPhone 13 touch profile
      (Playwright, `mobile-gestures`/`mobile-webkit` projects): Trends' main chart + weekly
      volume bars, Body's weight + W/kg charts, WorkoutDetail's `ErgChart` (a concept2-sourced
      workout, since a Garmin-only one has no per-stroke data to chart at all), and Today's
      `ExpandedTrendChart` dialog (VitalsCard's HRV/resting-HR expand). No zoom buttons visible
      on any of them; all data fits without the buttons' former screen real estate.
- [x] New unit tests in `chartRange.test.ts` for the clamp-to-earliest behavior (wider-than-
      history clamps to the first point, narrower-than-history is unaffected, never clamps below
      the 7-day minimum zoom).
- [x] `uv run pytest tests/ -q` — 224 passed, unchanged (this session never touched the
      backend). `cd web && npx tsc -b && npm run build` — clean, and the `ChartZoomButtons`
      chunk no longer appears in the build output. `cd web && npm run test` (Vitest) — 20
      passed (17 + 3 new `presetToDomain` cases). `cd web && npm run test:touch` — 17 run / 7
      correctly skipped (WebKit can't do multi-touch/move), including the 2 new permanent tests
      above. `cd web && npm run test:update` — 4 passed, unaffected.
- [x] `CLAUDE.md` (charts/ list, `ChartZoomButtons` removed) and `DESIGN.md` ("On-chart zoom
      buttons removed" note) updated. PLAN.md + commit.

## Session 12 checklist

The task that opened this session called it "session 8" — PLAN.md's own numbering already
used that number for the interactive-charts work (above), so this continues the file's own
sequence instead, the same resolution session 8 itself used for an identical collision with
"session 7."

Cross-source activity matching, Peloton rides, activity editing, body composition from any
scale, and real per-sample zones/strain (Parts A-E of the task). The single largest session
so far — summarized by part below, with the real-data verification and an advisor review's
findings after.

### Part A — matching engine

- [x] **Data model**: every `Activity` (a source record) gets a `canonical_id` immediately at
      upsert time, pointing at its own new `CanonicalActivity` row — a 1:1 relationship until
      the matching engine merges two. New tables: `canonical_activities` (resolved display
      fields, `field_sources_json`, `overrides_json`, cached `zones_json`/`strain_trimp`/
      `strain_method`/`session_label`/`auto_trimmed_tail_s`), `match_decisions` (natural
      `(source, external_id)` pair key, not row ids — survives a resync), `merge_log` (one row
      per merge/split, "log every auto-merge"). The old session-2 `linked_activity_id`
      Garmin<->Concept2 mechanism is fully superseded; kept only as a column a one-time
      migration (`catch/core/db.py::_migrate_linked_activities_to_canonical`) reads to carry
      existing pairs into one canonical, never read by any other code after that.
- [x] **Matching rule** (`catch/analytics/matching.py`, pure): same `sport_family`
      (rowing/cycling/running/strength/other) + start within 3 min OR overlap >=70% of the
      shorter record + duration ratio in [0.8, 1.25] makes a *candidate*; a continuous score
      decides auto-merge (>=0.82) vs. flagged "possible duplicate" (>=0.45). Indoor vs. outdoor
      is a hard block on auto-merge regardless of score. `catch/sync/matching.py` is the
      DB-facing half — `run_matching()` (idempotent; run after every sync and as the backfill
      report below) finds and merges candidates, writing a `MergeLog` row per merged member.
- [x] **Field priority** (`catch/sync/canonical.py::resolve_canonical`, task's defaults):
      power/cadence/title prefer Peloton > Concept2 > Garmin; distance for an indoor bike
      prefers Peloton > Garmin; HR prefers whichever member has `hr_source_type ==
      "chest_strap"` (or is a Concept2 result — a PM5 has no wrist sensor to confuse it with)
      else the Garmin watch else any member with HR. Configurable via
      `Settings.field_priority`/`body_comp_priority` (Settings page: "Cross-source matching" /
      "Body composition sources" cards). Shown per-field next to each metric in workout detail
      (the "Sources" panel: which record, which fields it won).
- [x] **Manual control**: `POST /api/activities/{merge,split,not-duplicate}` (raw per-source
      activity ids, matching what the Duplicates screen displays) and the coach tool
      `merge_activities` — a manual split survives a resync via the `MatchDecision` row
      `split_activity` writes. `/workouts/duplicates` lists flagged (not auto-merged) pairs
      side by side with Merge / Not a duplicate actions.

### Part B — Peloton

- [x] **Checked with real data first, per the task's own instruction**: no Peloton-pushed
      activity exists in this account (see the real-data section below) — detection is
      implemented per the documented FIT-spec mechanism (`file_id.manufacturer`, not
      `device_info`, which legitimately lists third-party *paired accessories* like this
      account's real Cardiosport HR strap on an otherwise watch-recorded ride — using it
      would have false-positived on that) but is unverified against a real Peloton-origin
      file. Full findings in `docs/peloton.md`, including the specific "neither real
      indoor-cycling FIT file has a power or cadence field" finding that drove the "use
      whatever the watch recorded" fallback.
- [x] Peloton-origin activities forced to `sport_family="cycling"`, treated as indoor by the
      matching engine, title prefers a real (non-generic) `title_hint` — Garmin's
      `activityName` — confirmed live that a plain recording's is exactly the generic
      per-type label, so nothing in this account's real history ever produces a fake "real"
      title.
- [x] **Cycling strain** (`catch/analytics/cycling_load.py`): power-based TSS
      (`100 * hours * (avg_power/FTP)^2`, the standard simplified formula) when the canonical's
      power-source member has power samples, FTP from `Settings.ftp_watts` or estimated
      per-ride as best-20-minute-power x 0.95 (flagged via `CanonicalActivity.strain_method`).
      HR Banister trimp otherwise. Fed into the same 0-21 strain scale as every other sport —
      a documented approximation (docs/analytics.md §18), unverified against any real
      cycling-power data since none exists in this account. Today's `load` card gained a
      `rowing_load` line (rowing-only EWMA load, parallel series) so cycling volume never
      inflates the number the athlete actually trains rowing against.

### Part C — activity editing

- [x] `title`/`sport_family`/`notes`/`rpe`/`exclude_from_totals`/`tags` are Catch-side
      overrides (`CanonicalActivity.overrides_json`) layered over resolved source values,
      surviving every re-sync; `POST /api/activities/{id}/revert` drops one field's override.
      `exclude_from_totals` is honored everywhere totals are computed (`scoring.py`'s
      `_day_activities`, `routes_analytics.py`'s `trends_volume`).
- [x] Inline title edit (tap to rename) + a full Edit card (sport/tags/exclude/sources) on
      workout detail; Workouts-list "Select" mode for bulk retype/tag/exclude-from-totals
      (`POST /api/activities/bulk`).
- [x] Auto-titles when no source/override title exists: `"Erg N x Dm"` (Concept2 structured
      workout), `"Peloton N min Just Ride"`, `"Steady state N'"` (continuous Garmin row), else
      a generic per-sport-family noun.
- [x] Coach/MCP tools: `rename_activity`, `tag_activity`, `merge_activities` (preview-then-
      `confirm=true`, per the task's explicit "asks me to confirm in chat before merging") —
      all three take canonical ids like every other workout tool, *not* raw per-source ids (an
      advisor-review fix below explains why that distinction matters).
- [x] Garmin's Personal API is read-only — `edits_push_back_to_source: false` on every
      canonical payload; the UI never implies otherwise.

### Part D — body composition from any scale

- [x] **Checked the Garmin swagger spec, then live**: `/weight-service/weight/range` is real
      and now synced (`GarminClient.sync_weight`) — **live-verified weight is reported in
      grams, not kilograms as the OpenAPI schema's own description claims** (two real entries:
      `58967.0`/`54431.0` for ~59kg/~54kg readings). `bodyFat` maps to `fat_pct`;
      `muscleMass`/`boneMass`/`bodyWater` are left unmapped since this account's real entries
      have them all `null` — no live value to confirm their unit against, and guessing wrong
      would silently corrupt a number rather than just being absent.
- [x] `catch/sync/body_comp.py::resolve_daily`: one resolved value per day per metric
      (weight/fat_pct/muscle_kg), Withings first/Garmin second by default
      (`Settings.body_comp_priority`), **never averaged**, each tagged with its winning
      source. `GET /api/body` now returns this instead of raw interleaved rows.
- [x] `POST /api/body/manual` + a form on the Body page — the app works with no scale
      connected at all; "manual" always sorts last regardless of configured priority order.

### Part E — zones and strain from the full HR stream

- [x] **Samples**: `catch/sync/fit_parse.py` streams FIT `record`/`lap` messages (`fitdecode`
      — pure-Python, universal wheel, checked against PyPI before adding) into a 1Hz grid
      (<=10s gaps forward-filled, longer ones are real dropouts); Concept2 strokes resampled
      the same way (`catch/sync/samples.py`). Packed as zlib'd uint16 arrays
      (`catch/analytics/samples_codec.py`) into one `ActivitySamples` row per source record —
      a few KB per session, not thousands of rows (the Pi-memory rule).
- [x] **Real time-in-zone and per-sample Banister TRIMP** (`catch/analytics/zones_samples.py`)
      replace the whole-session average everywhere samples exist — light (~5s) smoothing
      with dropout rejection (0s and 30s+ flatlines), never counted as real HR.
- [x] **Session label**: highest zone with meaningful time (>= `min_zone_minutes` OR
      `min_zone_pct` of moving time, both configurable) leads, e.g. `"AN (10 min) + UT2"`.
      Erg/bike also compute a power-zone label when power exists and use the higher-intensity
      reading between HR and power.
- [x] **Auto-trim**: a trailing near-zero-cadence stretch is "likely watch left running" —
      excluded from the zones/strain/label computation and from the HR-graph summary chips,
      never from the stored samples (which the chart still shows, in full, greyed out over
      that stretch).
- [x] **HR graph** (`GET /api/activities/{id}/samples`, `HrChart.tsx` on `useChartInteraction`
      like every other chart): zone-shaded bands, dashed max/avg HR, FIT lap markers (or their
      Concept2 stroke-interval equivalent), the trimmed tail greyed, a power/cadence overlay
      toggle, pan/zoom with `start_s`/`end_s` windowing for full resolution when zoomed in, a
      clean "no heart-rate data" vs. "no per-sample data at all" empty state.
- [x] **Recompute-all-history report**: see the real-data section below —
      **352 of 418 real sessions with samples (84%) changed their primary zone label** under
      this method vs. the old whole-session-average one.

### Quality bar

- [x] Fixture tests for: watch + Peloton-pushed merging into one canonical with correct field
      sources (`tests/test_matching_engine.py`), back-to-back separate rides never merging,
      indoor vs. outdoor never auto-merging, manual split staying split after a re-run of
      matching. The task's own quality-bar fixture (20 min warm-up / 10 min at ~95% max HR /
      25 min cool-down + an idle tail) run twice — once against the pure zone/strain functions
      directly (`tests/analytics/test_zones_samples.py`) and once end to end through
      `store_samples -> resolve_canonical -> day_strain` with the idle tail included
      (`tests/test_canonical.py`) — confirming the label is AN/TR-led (never UT2) and the
      day's strain exceeds a steady UT2 piece of the same average HR, both ways.
- [x] 85+ new/updated tests this session (224 -> 314 total, `uv run pytest` all green),
      including monkeypatched-`fitdecode`-frame coverage for FIT parsing (no real `.fit` file
      committed — it carries a user-profile/serial-number), a real-backoff test for the
      Garmin-429-resilience fix below, and regression tests for every bug the two advisor
      reviews caught (route order over real HTTP, `resolve_all_canonicals`, the
      `drop_dropouts` hang, category-filter pagination, the Pi stale-`fit_path` migration
      bug).
- [x] Frontend: `tsc -b` clean, 20 Vitest tests passing, `npm run build` ~156.5KB gzip eager
      bundle (budget 250KB, `HrChart`/`Duplicates`/the editing UI all land in their own
      per-route lazy chunks). Verified live against a real Vite dev server with Playwright
      MCP (not just the build succeeding) at 390px/1280px, dark/light, on Workouts (Select
      mode), Workout detail (HR graph + Edit card + Sources panel), Duplicates (merge flow
      clicked through end to end), and Settings (the three new cards) — this first pass ran
      against **mock data** (`?mock=1`) and caught two real bugs (below). A second advisor
      review then caught five more real bugs plus several missing requirements, verified with
      a further pass against a **disposable real backend** (a throwaway uvicorn instance over
      a copy of the real local `data/catch.db`, real secrets never touched) — see "A second
      advisor review" below.
- [x] CLAUDE.md (layout: new `sync`/`analytics`/`web` modules, MCP tool count 16->19),
      `docs/analytics.md` (§17-20: matching, Peloton/cycling load, per-sample zones/strain,
      body comp), `docs/garmin-endpoints.md` (the real weight-in-grams finding),
      `docs/mcp.md` (tool count/list), `docs/peloton.md` (new) updated. PLAN.md + commit.

## Real-data verification (2026-11-02)

The local snapshot (`data/catch.db`, last synced 2026-10-31) only covered 30 days and the Pi's
live DB wasn't reachable this session (not on the same network) — so the backfill report
below is a **full, fresh `uv run catch backfill --days 400` against a disposable scratch
SQLite DB** (`CATCH_DB_PATH` override; real `.env` Garmin/Concept2 credentials, read-only API
calls, never the real `data/catch.db`), matching every prior session's disposable-instance
precedent for live checks. Also includes the earlier live checks run directly against the
real account before the backfill (the Garmin weight endpoint, this account's real FIT files).

**Three real bugs found running it, fixed, then re-verified against the same real backfill**:

- **A single FIT download's 429 (rate limit) used to abort the entire backfill.**
  `GarminClient.download_fit` let `resp.raise_for_status()` propagate uncaught, so one rate-
  limited activity killed every later activity in that sync call *and* every later window in
  a multi-month backfill — caught live after several months of real history had already
  synced successfully, then hit a 429 partway through. Fixed in two passes (the first only
  covered FIT downloads; running the real backfill again immediately surfaced the same root
  cause on `/weight-service` too, which wasn't covered): `GarminClient._call_with_backoff`
  now wraps every per-window call (`sync_health`/`sync_activities`/`sync_weight`) with one
  retry after a short sleep on a 429, otherwise logging and treating that window as a 0
  rather than raising. Re-verified live: the second real backfill attempt hit *many* 429s
  (Garmin rate-limits a 400-day historical pull fairly aggressively) but completed all 400
  days regardless, landing 451 real activities instead of aborting after ~80. One
  `sync_health` window (2026-10-05..11-02) still hit the 429 even after the one retry and was
  logged and skipped rather than retried further — `DailyWellness` for that window is backed
  only by whatever Withings covered, picked up on the next scheduled sync.
- **The Duplicates screen's mock "Merge" button didn't actually clear the flagged pair** —
  found live-clicking through the mock UI with Playwright, not by reading the code. Real bug
  in `mergeMockActivities`'s fallback path: the demo Peloton-push duplicate pair isn't
  attached to any pre-existing `MOCK_WORKOUTS` entry (the whole point of the demo — a
  not-yet-merged flagged pair), so the function's happy path never matched and the flagged
  pair was never spliced out of `MOCK_DUPLICATE_PAIRS`. Fixed by always removing the matched
  pair first, before whichever merge path applies.
- **The HR chart's trimmed tail never actually rendered (greyed out) on first load** — the
  frontend's initial view domain was computed from `usable_n_samples` (which *excludes* the
  trimmed tail by definition), so the chart's own window never extended far enough to show it.
  Fixed by defaulting both the backend's `/samples` window and the frontend's initial domain
  to the *full* recording (`n_samples`), with the summary chips still computed over the usable
  range only — the trimmed tail is now visibly greyed, not simply cut off the chart.

**Backfill report** (451 real Garmin activities, 2025-09-28 to 2026-10-31, ~13 months):

| | before | after |
|---|---|---|
| Activity rows | 451 | 451 (unchanged — raw source records are never deleted) |
| Canonical activities | — | 451 |
| Auto-merged | — | 0 |
| Flagged (possible duplicates) | — | 0 |

**Zero merges and zero flags** — a real, somewhat anticlimactic finding, not a bug: this
account has zero Concept2 results (still true every session since session 2 — `GET
/api/users/me/results` returns `total: 0`) and zero Peloton-pushed Garmin activities across
the *entire* 13-month real history (`origin` is `"watch"` for all 418 FIT-parsed activities,
never `"peloton"`), so there is genuinely nothing in this account for the matching engine to
merge yet. The matching logic itself is covered by synthetic fixtures (above) specifically
because real evidence for it doesn't exist here — same situation as session 2's Concept2
fixtures and session 8's Peloton docs.

Other real findings from the same backfill:

- **418 of 451 activities got real per-sample zones/strain** (the rest hit a persistent 429 on
  their FIT download even after the one retry — logged, `fit_path` left unset, picked up by
  the next scheduled sync).
- **84% of real session labels changed** under the new per-sample method vs. the old
  whole-session-average one (352 of 418) — including cases matching the task's exact
  motivating scenario, e.g. a real session that averaged to "AT" relabeled "AN (11 min) + TR"
  once the real 11 real minutes at AN showed up, and one that averaged to "UT1" relabeled
  "AN (7 min) + UT2" (a short hard effort the average had been hiding inside an otherwise easy
  session).
- **Real recovery/strain/load computed correctly end to end**: the most recent day's real
  recovery score (78.9%, green — real HRV/sleep/prior-strain components) and 3 real Garmin
  weight rows (confirming `sync_weight` works live beyond its fixture test) both came out of
  the same backfill run.
- All 45 real `indoor_cycling` activities: `origin="watch"`, `hr_source_type="wrist"`
  uniformly (no chest-strap pairing on any cycling session in this account), and every single
  one's `activityName` is exactly the generic `"Indoor Cycling"` label — the live basis for
  `_is_generic_garmin_title`'s detection logic (docs/peloton.md, docs/analytics.md §17.1).
- This account's real FIT files legitimately pair a third-party ANT+ HR strap
  (`"cardiosport"`) on an otherwise watch-recorded activity — confirmed why Peloton detection
  must use `file_id.manufacturer`, not `device_info`, or it would false-positive on this
  exact real case.

## A second advisor review: five more real bugs, plus missing requirements

A second advisor pass over the diff above (after the real-data verification, before this
session's commit) caught five more real bugs — none visible to mock-mode or direct-function
tests, all over real HTTP, real settled state, or a real deployment path this account hasn't
exercised yet — and several requirements the task asked for that the first pass had missed.
Fixed, then re-verified with a **disposable real-backend Playwright pass**: a throwaway
uvicorn instance over a copy of the real local `data/catch.db` (real secrets never touched,
cleaned up after).

- **The entire Duplicates feature was unreachable over real HTTP** — `GET
  /api/activities/duplicates` 422'd (`int_parsing` on `"duplicates"`). Root cause: Starlette
  matches routes by registration order, and `GET /api/activities/{canonical_id}` (no `:int`
  converter) structurally matches any path segment first; FastAPI's own type-validation
  failure on that match doesn't fall through to try the next route. Invisible to the mock-UI
  Playwright pass above (which never hits a real backend) and to every existing test (all
  called the handler function directly, never over HTTP). Fixed by moving the `/duplicates`
  route above `/{canonical_id}` with an explanatory comment; added HTTP-level regression
  tests.
- **A changed Settings value (max HR, zone boundaries) silently stopped affecting
  already-resolved canonicals.** `PUT /api/settings` only re-ran matching for orphan/blank/
  newly-merged canonicals, never recomputed the zones/strain of ones that already had cached
  values. Added `resolve_all_canonicals()`, wired into `put_settings` before
  `recompute_scores`.
- **`drop_dropouts` could hang forever** on a sample array that already had a `None` gap
  (true of every real FIT/Concept2 sample array, which always has resample gaps) — the inner
  scan's termination condition (`out[j] is not None and out[j] == out[i]`) can never advance
  when `out[i]` itself is `None`. Found trying to empirically measure the function's real-data
  drop rate per the advisor's own suggestion: a background script hung past two minutes.
  Fixed with an explicit "already a gap" branch; added a regression test; then re-ran the
  real-data measurement once the hang was fixed (0.57% average drop rate across 30 sampled
  real activities, 4.5% worst case — confirms the 30s-flatline threshold isn't overly
  aggressive against real sensor noise).
- **The Workouts category filter (erg/on_water) broke pagination on real data.** Both
  categories map to the same `sport_family=="rowing"` in SQL; the actual erg/on_water split
  only happened in Python *after* the SQL `LIMIT` applied, so with this account's real skew
  (166 on_water vs. 118 erg) a page could come back short or empty. Fixed by persisting
  `category` on `CanonicalActivity` (computed once in `resolve_canonical`) and filtering on it
  directly in SQL.
- **A real latent Pi-deployment bug** — flagged non-blocking by the review, confirmed real by
  reading `deploy/pi-bootstrap.sh` and `catch.service`: that script explicitly supports
  adopting a staged `catch.db` + `fit/` directory copied from the laptop, landing FIT files at
  `/var/lib/catch/fit/`. But rows synced on the laptop store `fit_path` as a path relative to
  `CATCH_DB_PATH`'s parent (`data/fit/<id>.fit`, since the laptop's `.env` uses a relative
  `CATCH_DB_PATH`). On the Pi, `catch.service`'s `WorkingDirectory=/opt/catch/app` (and
  `ProtectSystem=strict`, read-only outside `ReadWritePaths=/var/lib/catch`) means that
  relative path never resolves, and since `sync_activities` only re-downloaded when `fit_path`
  was unset, a migrated row's samples would silently never populate on the Pi, with no error
  logged. Fixed: `sync_activities` now also re-checks `Path(row.fit_path).exists()`, and if
  the expected file already lives in the current run's `fit_dir` (as it does right after the
  bootstrap's `fit/` copy), re-points to it instead of re-hitting Garmin's download-service.
  Added a regression test reproducing the exact migration scenario (stale relative `fit_path`,
  real file already present at the new location, asserts no network call for that activity).
  **The fix only repairs an activity `sync_activities` actually processes** (a scheduled
  sync's window, or an explicit `catch backfill --days N`) — it doesn't retroactively touch
  every row already in a migrated DB on its own. After adopting a laptop DB on a fresh Pi
  install, run `catch backfill --days N` (N covering the real history) once so every migrated
  activity gets re-pointed. This does *not* avoid Garmin API calls in general — `catch
  backfill` still calls the activity-list, health, and weight endpoints for every window,
  the same ones that hit 429s in the real backfill above — only the FIT *download* itself is
  skipped per-activity once the bootstrap-copied file is found at the expected path.
- **Missing requirements, added**: per-activity notes/RPE inline editing on Workout detail
  (distinct from the existing per-day note/RPE journal entry); a stacked time-in-zone
  `ZoneBar` (Workouts list, compact, and Workout detail, with a legend); a second y-axis on
  `HrChart` for the power/cadence overlay (previously sharing the HR axis, making an overlay
  unreadable); live/settled-domain windowed refetch on the HR chart so zooming in actually
  requests full-resolution samples for the zoomed range instead of just stretching the same
  downsampled points.
- **`HrChart`'s y-axis always started at 0**, making a typical 120-180bpm session plot
  half-empty (non-blocking, flagged against an earlier screenshot) — changed to start at the
  lowest observed HR minus a small margin, floored at 0. That fix itself then had two bugs,
  caught by a follow-up advisor pass over the diff before commit: the trimmed-tail grey region
  was computed from `points` (the *zoom-windowed* sample array, since the live/settled
  windowed refetch above), so panning or zooming greyed the wrong stretch of the chart instead
  of the real idle tail — fixed to derive it from `fullDomain` instead. And the new non-zero
  axis floor let a zone's configured `hr_lo`/`hr_hi` fall outside `[hrMin, hrMax]`, drawing
  that zone's band and label past the plot edge over the x-axis time labels — fixed by
  clamping each band to the visible range and skipping a zone that clamps to nothing. A third
  issue surfaced live-checking the fix with Playwright at 390px (not from a review comment):
  with the power/cadence overlay on, its own right-gutter axis labels could land at the same
  height as a zone-name label and visually collide — fixed by hiding the inline zone-name
  labels whenever an overlay is active (the `ZoneBar` above the chart already names each
  zone). Also made the axis bounds themselves stable across pan/zoom by computing them from
  the full-recording points (a new `allPoints` prop) rather than the zoom-windowed ones, so
  the y-axis no longer visibly rescales on every refetch.
- **`resolve_all_canonicals` runs synchronously on every `PUT /api/settings`** — a real Pi-3
  cost worth checking per the review. The first timing pass (~1ms/canonical, 34 canonicals
  against a disposable copy of the real local `data/catch.db`) measured the wrong thing: that
  DB predates session 12's schema, so nothing had ever ingested its `ActivitySamples`, and
  every canonical hit `_resolve_zones`'s cheap early-return for "no HR or power." Re-timed
  properly — same DB copy, but with every real FIT file actually parsed into samples first
  (`GarminClient._ingest_fit_samples`, no network calls) — gives **~6.5ms/canonical**, i.e.
  ~3s for this account's real 451-activity history *on this laptop*. The Pi 3's single ARM
  core runs pure-Python work an assumed 10-20x slower single-threaded, so call it **roughly
  30-60s** there, not measured directly. `def put_settings` being sync means FastAPI runs it
  in the threadpool, so a slow request doesn't fully block the one uvicorn worker's event
  loop, but it does compete for the GIL and tie up a threadpool slot — other requests slow
  down for that whole stretch, on *any* settings save, not just one that changes zones/strain.
  First fix attempt only skipped the work when the incoming *patch* omitted every
  zones/strain-affecting key — wrong, since `web/src/pages/Settings.tsx` has exactly one Save
  button that always PUTs its whole `form` state (every field, every time), so that check
  never actually skipped anything for a real save. Fixed properly (in `1d282f9`): compare
  `get_settings`'s *values* before and
  after `update_settings`, not which keys the patch happened to include, and only re-resolve
  if one of `max_hr`/`ftp_watts`/`field_priority`/`zones`/`trimp_exponent`/`min_zone_minutes`/
  `min_zone_pct`/`auto_trim_enabled`/`auto_trim_min_idle_s` actually changed value. When it
  has, the work now runs as a FastAPI `BackgroundTasks` job (its own DB session) instead of
  inline, so the PUT itself returns immediately. That background function takes the request
  session's bound engine explicitly (`db.get_bind()`) rather than importing
  `catch.core.db.engine` directly — the first version did that, and failed on its first test
  run (`OperationalError: no such column`, not something that ever passed and later broke),
  because tests only override the `get_db` *dependency*, not that module-level global, so it
  would have silently run against a stale real local DB file instead of the test's in-memory
  one had the test suite not caught it before commit. The key-presence skip and the ~1ms
  timing both shipped in `53263c3`; both were corrected in `1d282f9`, the very next commit, by
  the same kind of follow-up advisor pass as the HrChart bugs above. Added regression tests
  for the skip/run branches (using a full-form-shaped payload, matching the real UI) and
  confirmed the existing cache-staleness test still passes with the background task in place.
  **Trade-off this introduces, worth knowing**: after a save that changes max HR, zones, or
  FTP, `Today`/`Trends`/`Workouts` keep showing the *old* zones and strain until the
  background job finishes (up to ~60s on the Pi per the estimate above) — nothing pushes a
  refresh to the frontend when it completes, so a page open at that moment needs a manual
  reload or a later natural refetch to pick up the corrected numbers.
- **A second, real write path to `max_hr` bypassed this fix entirely**: a review question
  ("are there other settings writers besides `put_settings`?") turned up
  `catch/sync/concept2_client.py`'s `_seed_max_hr`, called from every Concept2 sync
  (scheduler, CLI, and the `POST /api/sync/{source}` endpoint) — it seeds `max_hr` from the
  Concept2 profile the *first* time it's unset, calling `update_settings` directly, never
  through `put_settings`. On a fresh install where Garmin syncs before Concept2 is ever
  connected, every Garmin canonical gets resolved with `max_hr` unset, and this seed step
  would otherwise leave their cached zones stale forever once a real `max_hr` exists. Fixed
  by calling `resolve_all_canonicals`/`recompute_scores` synchronously right after the seed —
  safe here, unlike `put_settings`, since this already runs inside an already-long sync (never
  a routine request's hot path). Added a regression test.

## Gotchas / deviations from the literal task spec

- **"Activity sources" is `Activity`+`canonical_id`, not a new table** — the task's wording
  ("`activity_sources` table") was weighed against reusing the existing `activities` table
  (already has the unique `(source, external_id)`, `fit_path`, `raw_json`, the `strokes`
  foreign key) plus a new `canonical_activities` table for the resolved side. Chose reuse:
  less migration risk, no behavior change for any code that already reads `Activity` for
  source-specific fields (raw FIT path, Concept2 strokes/workout_type/drag_factor).
- **Match-score thresholds (0.82 auto-merge / 0.45 flag) are code constants, not a Settings
  knob** — only field priority is explicitly asked to be configurable in the task; tuning the
  thresholds against zero real duplicate pairs in this account (see above) would have been
  guessing, not configuring.
- **Erg power-zone time (Part E.5) is implemented but unexercised by real data** — a real
  `watts_2k` threshold is threaded through (`catch/sync/rowing_predict.py`, shared with
  `GET /api/predict/2k`), but with 0 real Concept2 results this account has never produced a
  value to sanity-check it against. Revisit once real erg data exists.
- **Cycling TSS-vs-Banister-trimp equivalence (feeding both into the same 0-21 scale) is a
  documented approximation**, not a validated one — no real cycling-power data exists in this
  account to tune it against (docs/analytics.md §18).
- **FTP estimation is per-ride (best 20 minutes in that one ride x 0.95), not all-time** — a
  true FTP estimate would scan every ride's power history for the best-ever 20 minutes, which
  this doesn't do; a reasonable scope cut given there's zero real cycling-power data to tell
  the difference against either way.
- **"Instructor" (task Part B.2) has no field to map** — no Garmin summary field for it has
  ever been observed, live or otherwise; only the class-name-equivalent `activityName` is
  used. Revisit if a real Peloton-pushed activity's real shape ever becomes available.
- **The Pi needs a full-history `catch backfill` after its next deploy** — the scheduler's own
  3-day sync window will never retroactively parse FIT samples for older activities, so the
  real Pi's zones/strain/matching won't reflect this session's new method until a backfill
  (like the one this session ran against a scratch DB) runs against the Pi's real database.
  Deploying and running it was intentionally left for the user rather than done automatically
  this session (a real, hard-to-reverse action against the live device).

## Session 13 checklist

The task that opened this session called it "session 9" — PLAN.md's own numbering already
used that number (the real Pi deployment work, above), so this continues the file's own
sequence, same resolution session 8/12 used for their own identical collisions.

Two independent parts: daily non-exercise activity as a small, capped strain component
(Part A), and a full nutrition-logging feature — barcode scan, Open Food Facts/USDA lookup,
photo-estimate, targets that follow training load, and a calm under-fuelling note (Part B).

### Part A — daily activity in strain

- [x] **New fields from Garmin's `dailysummaries`** (already present in the real recorded
      fixture, `tests/fixtures/garmin/usersummary_range.json` — checked before writing any
      code, per CLAUDE.md's "never invent a Garmin field" rule): `DailyWellness` gains
      `steps`, `active_kcal`, `total_kcal`, `bmr_kcal`, `moderate_intensity_minutes`,
      `vigorous_intensity_minutes`, `floors_climbed`, `floors_descended`; `Activity` gains
      `steps`/`bmr_kcal` per workout (from the activity-list response, not the daily
      summary) so a workout's own contribution can be subtracted out. One-time idempotent
      migration (`catch/core/db.py::_migrate_garmin_activity_fields`) backfills `steps`/
      `bmr_kcal` for Garmin activities synced before this session from their already-stored
      `raw_json`, so a re-sync isn't needed just to populate the two new columns.
- [x] **Non-exercise load**: `catch/sync/scoring.py::_day_garmin_activity_totals` sums each
      canonical activity's own steps/active-kcal (its Garmin member's time window) and
      subtracts from the day's whole-day totals — a workout never counts twice.
- [x] **Strain component** (`catch/analytics/strain.py::daily_activity_strain`): a log1p
      curve on non-exercise steps/2000 and active-kcal/150, averaged, then capped (default
      1.5 of the 0-21 scale) and weighted — both configurable in Settings
      (`daily_activity_strain_cap`/`_weight`). **Additive on the final 0-21 `value`, never
      mixed into `trimp_like`** — an explicit advisor call-out: folding it into the load-
      bearing TRIMP figure would have inflated the acute:chronic ratio every time the athlete
      went for a long walk, exactly the "25k steps looks like a training session" failure the
      task asked to avoid.
- [x] **UI**: StrainGauge rewritten as a tap-to-open dialog (mirrors RecoveryRing's pattern)
      showing session components plus a "Daily activity" row with its % share of the total;
      Today gets a small, secondary steps/active-kcal line below strain/recovery.
- [x] Settings card ("Daily activity in strain") for the cap/weight knobs.
- [x] Tests: a rest day with 15k steps stays low-strain (the task's explicit check); fixture
      coverage for the new Garmin fields, the subtraction math, the capped curve, and the
      migration.
- **Recomputing the *strain formula* against already-synced data needed no separate backfill
  script** — `recompute_scores` already runs on every sync/note/settings change and applies
  the new formula live. But that's a different thing from having the *new Garmin fields
  themselves* on old days: `DailyWellness` has no `raw_json` column (unlike `Activity`, which
  is why `_migrate_garmin_activity_fields` could backfill `steps`/`bmr_kcal` for existing
  activities from already-stored data) — `steps`/`active_kcal`/etc. on any day the scheduler
  hasn't re-fetched stay `NULL` until a real `catch backfill` run hits Garmin's
  `/v2/dailysummaries` again for that day. The scheduler's own sync window is only a few
  days (same limitation session 12's PLAN.md notes for FIT-sample zones/strain), so the
  daily-activity strain component will silently read as 0 for every day before this session
  on the real Pi until a backfill covering that history is run against it. **Verified**: `uv
  run catch backfill --days N` (`catch/cli.py::cmd_backfill` ->
  `GarminClient.backfill`) internally windows any `N` into 30-day chunks regardless of size
  (`docs/garmin-endpoints.md`: "no documented max range — start with 30-day windows"), and
  each window's `sync_health` call reaches `_sync_usersummary` — so a single explicit `--days`
  run genuinely covers full history in one command, not just the 30-day
  `BACKFILL_DAYS` default plain `catch backfill` (no flag) would use. **Run `uv run catch
  backfill --days 400` on the Pi** (the same figure session 12's own full-history backfill
  used) to repopulate `steps`/`active_kcal`/etc. for the real account's whole history — not
  automatic, and not done this session (a live-device action left for the user, same
  call session 12 made for its own backfill).

Commit: `1618418`.

### Part B — nutrition

- [x] **Tables**: `Food` (source/barcode/name/brand/serving/per-100g macros/`verified`),
      `FoodLog` (ts/meal/food_id/quantity+unit/computed macros/`estimated`), `MyFood`,
      `SavedMeal` (items as JSON), `NutritionTarget` (one row, id=1 — mirrors the existing
      `Settings`/`NutritionTarget` singleton-row pattern), `AiUsageEvent` (a second cost
      ledger alongside `CoachMessage.cost_usd`, specifically so photo-estimate spend counts
      against the same daily cap as chat — an advisor call-out that this would otherwise
      silently bypass the cap).
- [x] **Barcode lookup** (`catch/sync/nutrition.py::lookup_or_fetch_barcode`): local `foods`
      cache -> Open Food Facts (`docs/nutrition-endpoints.md`: 15 req/min/IP, OFF's own
      documented limit, enforced in-process since a single uvicorn worker makes module-level
      state safe; negative-cached misses for 24h) -> USDA FoodData Central by GTIN (only if
      `USDA_FDC_API_KEY` is set) -> `None` (manual-entry form prefilled with the barcode). A
      found external hit is cached into `foods` immediately.
- [x] **Free-text search** (local cache, ranked by recency/frequency of use in `food_logs`,
      then USDA free-text, deduplicated by barcode against what's already in the results).
      **A first pass wrongly concluded OFF had no free-text search at all**, having checked
      only the v2 API's own surface; an advisor review's "verify, don't assume" prompt led to
      actually fetching OFF's current docs and the live endpoint, which confirmed
      `/cgi/search.pl?search_terms=...&json=1` works today and is what OFF's own docs still
      point to for full-text search (v2 doesn't have it; v3 doesn't either; a newer
      "Search-a-licious" service is referenced as the future but exposed no documented public
      API at the time of this check). **Second correction, same review thread**: the first
      wiring attempt reached OFF search from the debounced search box itself — still
      search-as-you-type by OFF's own definition (the trigger is every keystroke pause, not
      an explicit action) despite the 250ms debounce, and OFF's docs explicitly warn against
      exactly that ("you would be blocked very quickly"), on top of making nearly every search
      wait on OFF's slowest endpoint since local+USDA rarely fill a 20-result page on their
      own. Fixed by making it **opt-in**: `search_foods(..., include_off=False)` — the search
      box never passes it, and surfaces an explicit "Also search Open Food Facts" button the
      athlete taps once per query to opt in; the coach's `log_food` tool always passes
      `include_off=True` (one call per tool use, never as-you-type — the one place this app
      does hit OFF search automatically, and legitimately so). `OpenFoodFactsClient.search`
      still keeps its own separate 10/min/IP budget (distinct from product-read's 15/min) and
      fails open (empty list, never raises) as a backstop even for opted-in calls. See
      docs/nutrition-endpoints.md for the verified field shapes (same nutriment-key convention
      as the v2 product-read endpoint, a different top-level wrapper, a `fields=` param that
      isn't a strict whitelist).
- [x] **Scanner** (`web/src/components/nutrition/BarcodeScanner.tsx`,
      `web/src/lib/barcodeScan.ts`): native `window.BarcodeDetector` when present (confirmed
      by forcing the fallback in a real page — `addInitScript` deleting
      `window.BarcodeDetector` before load — and checking the wasm request's `initiator`: it
      genuinely only fires once `createBarcodeDetector()`'s fallback branch runs, and from
      this app's own origin, not jsDelivr), else the `barcode-detector` ponyfill over a
      **self-hosted** ZXing-wasm binary (Vite's `?url` import serves it from `/assets`,
      instead of the package's default jsDelivr-CDN fetch — this app runs offline-first on a
      Pi with no reason to depend on an external CDN for a core feature). **Correction**: the
      wasm is *not* actually cached by the service worker, despite living under `/assets/*` —
      checked by grepping the built `sw.js`'s precache list, which only ever includes `.js`/
      `.css` chunks (`writeBundle` in `vite.config.ts` only pushes those two extensions), and
      by reading the SW's own `/assets/*` fetch handler, whose cache-first branch
      (`caches.match(req).then((cached) => cached || fetch(req))`) has no `cache.put()` on a
      miss — unlike every other branch in that file, which explicitly writes back. A pre-
      existing gap (the font files have the exact same characteristic), not something this
      session introduced or fixed; revisit if the wasm's repeat-fetch cost on a slow
      connection ever becomes a real complaint. It *is* still genuinely lazy — confirmed via
      the production build's chunk list (`BarcodeScanner-*.js`, its own chunk separate from
      `Nutrition-*.js`) and via the SW's precache list itself not containing it — so a user
      who never opens the scanner never downloads it, which was the actual goal. Python's
      stdlib `mimetypes` table already maps `.wasm` -> `application/wasm` (checked — no fix
      needed in `catch/main.py`'s static file serving). Rear camera (`facingMode: {ideal:
      "environment"}`), feature-detected torch toggle (iOS Safari doesn't expose `torch` in
      `getCapabilities()` at all — never assumed present), every camera track stopped on
      close/unmount.
- [x] **Photo estimate** (`catch/coach/nutrition_vision.py`): one-shot Anthropic vision call
      against the athlete's own configured model (never hardcoded — this is bring-your-own-
      key), structured output via an auto-chosen strict tool rather than forced `tool_choice`
      (newer models 400 on forced tool use, per the claude-api skill). Client resizes to
      ~1500px JPEG before upload. Editable itemized result, labelled "estimate" throughout,
      hidden when no Anthropic key is configured. The photo is never written to disk or
      logged — only its bytes pass through the one API call.
      - A real gap an advisor review caught: the original `/photo-estimate` endpoint only
        *returned* an estimate with no way to *save* an edited one correctly (`create_manual_
        food` hard-codes `source="manual", verified=True`, and each item's macros are
        already absolute for its described quantity, not per-100g). Added
        `POST /api/nutrition/photo-estimate/save` + `nutrition.save_photo_estimate`, which
        gives each item a `serving_size=100`/`serving_unit=<quantity description>` `Food` row
        so logging "1 serving" reproduces the item's exact estimated macros, tagged
        `source="estimate", verified=False`, `FoodLog.estimated=True`.
- [x] **Targets** (`catch/analytics/nutrition.py` — pure math; `catch/sync/nutrition.py` — DB
      gathering): protein g/kg x latest resolved body-comp weight (any source, never
      Withings-only despite the task's literal phrasing — this account's Withings OAuth may
      be incomplete); carbs g/kg x weight, tier (`rest`/`moderate`/`double_day`/`pre_race`)
      from the day's logged canonical-activity count plus A-race taper proximity (no
      training-plan feature exists to read a *planned* load from instead); kcal from a
      trailing 7-day Garmin total-burn average (today's own partial total excluded); fat as
      the kcal remainder after protein/carbs, never its own knob. All defaults configurable
      in Settings, labelled "starting points, adjust with a coach or dietitian" everywhere
      they're shown (docs/analytics.md §21 has the full formulas).
- [x] **Under-fuelling note**: flags only when the last 3 *logged* days each ran >=25% below
      that day's Garmin expenditure — an unlogged day is never treated as a zero-intake
      deficit day (the task's explicit "no streaks, no shaming" ask). Calm, factual copy; no
      red/"over" state anywhere in the nutrition UI. Surfaced on `GET /api/today` (so the
      coach sees it via `get_today` without a separate call) and the Nutrition week view.
- [x] **UI** (`web/src/pages/Nutrition.tsx` + `web/src/components/nutrition/`): day view
      (macro bars vs. targets — neutral fill, no red, capped visually at 100%; six meal
      sections with quick-add/copy-yesterday's-meal/inline-edit/delete; My Foods and Saved
      Meals quick-pick chips when the search box is empty); week view (energy-in-vs-out and
      protein-consistency bar rows, the under-fuelling note). `AddFoodDialog` is one flow for
      search, scan, My Foods/Saved Meals quick picks, and manual entry — picking anything
      feeds into one quantity-confirmation step before logging.
- [x] **Coach + MCP**: `get_nutrition`/`log_food` added to the shared tool registry
      (`catch/coach/tools.py`), the MCP server (19 -> 21 tools,
      `catch/mcp_server/server.py`), and both chip-label mirrors (`catch/coach/chat.py`,
      `web/src/lib/toolLabels.ts`). `system_prompt.md` documents the nutrition tools and an
      explicit no-medical-claims guardrail (no eating-disorder-adjacent guidance, no calorie
      prescriptions, no supplement dosing).
- [x] **Nav**: added to both `Sidebar.tsx` ("Nutrition") and `BottomNav.tsx` — labelled
      "Fuel" there instead, since 390px/7 items leaves too little width for "Nutrition" at
      the bottom nav's 12px label size (screenshotted at 390px to confirm "Fuel" fits
      cleanly; this was a design risk flagged in review before any code was written).
- [x] **Tests**: fixture-based parsing tests for OFF (missing fields, kJ-vs-kcal, per-
      serving-vs-per-100g, the gram/milligram sodium-unit mismatch) and USDA (search vs.
      detail shape, GTIN matching, SHOUTY-case titles); steps-in-strain math (Part A); target/
      under-fuelling math; the full nutrition REST API (barcode fallthrough and caching,
      manual food creation, logging by grams/serving, the serving-size-unknown rejection,
      day/week summaries, copy-day with and without a meal filter, my-foods/saved-meals
      CRUD, targets round-trip, photo-estimate's 422s and its save path); the two coach
      tools; OFF free-text search's parsing/budget/opt-in fallthrough; a structural
      live-network-call guard (`tests/conftest.py`, patches httpx's default transport to
      raise on any real outbound call) plus its own self-test; a round-trip test logging a
      food found through the opt-in OFF search by its returned id. 396 backend tests total,
      20 frontend (Vitest) unit tests, clean `tsc -b`/`oxlint`/production build.
- A real bug found and fixed mid-session: the test suite was making **live calls to the USDA
  API** whenever a test exercised `search_foods`/`lookup_or_fetch_barcode` without its own
  explicit monkeypatch, because the real dev `.env` has a genuine `USDA_FDC_API_KEY`
  configured and nothing stopped it from being used — a direct violation of CLAUDE.md's "no
  live network calls in the suite" rule, caught because three new tests returned real-looking-
  but-wrong results (5 search candidates instead of the fixture's 2, etc.) rather than
  failing outright. Fixed with an autouse `tests/conftest.py` fixture
  (`_no_live_usda_calls`) that zeroes the key by default; the handful of tests that
  specifically want to exercise the USDA fallback override it back themselves.

**Findings / follow-ups for next time**

- **Real-phone barcode scanning was not verified this session** — same limitation session
  9/10 already noted for other camera/PWA-dependent features: this environment can't drive a
  real device's camera. What *was* verified in a desktop Playwright browser: the scanner's
  chrome (viewfinder, torch toggle, track cleanup); the native-BarcodeDetector path (Chromium
  has one); and, with `addInitScript` deleting `window.BarcodeDetector` to force it, the
  **self-hosted ZXing-wasm fallback path end to end** — `createBarcodeDetector()` correctly
  falls back, the wasm request genuinely goes to this app's own origin (not jsDelivr), and
  `detect()` resolves cleanly (empty result) against a blank canvas rather than throwing. What
  remains unverified is **decode accuracy against a real barcode on a real rear camera** in
  the installed PWA — `getUserMedia` against an actual camera, a real product's barcode in
  frame, real lighting. `web/tests/touch/`-style Playwright coverage with `--use-fake-device-
  for-media-stream`/`--use-file-for-fake-video-capture` (feeding a recorded video of a real
  barcode) would close this specific gap — not attempted this session given the time budget,
  same tradeoff session 8/12 made for the equivalent touch-gesture suite.
- **`USDA_FDC_API_KEY` must be added to the Pi's own `.env` before this ships for real** — the
  dev `.env` here has one, but nothing deploys secrets; `.env.example` documents the key, the
  Pi's copy needs it added by hand (same as every other credential in this app).
- **The Pi needs a `catch backfill` run too, for a different reason than session 12's** — see
  Part A's note above: `steps`/`active_kcal`/etc. are `NULL` on any day the scheduler's own
  short sync window hasn't re-fetched, and there's no `raw_json` column on `DailyWellness` to
  backfill from locally the way `Activity`'s migration could. The daily-activity strain
  component reads as 0 for every pre-session day on the real Pi until that backfill runs. Run
  `uv run catch backfill --days 400` (not the bare `catch backfill`, which only covers the
  30-day `BACKFILL_DAYS` default) — verified this genuinely reaches `/v2/dailysummaries`
  across the whole range via `GarminClient.backfill`'s own 30-day-window chunking loop.
- **The photo estimate's `kcal`/`protein_g`/etc. fields on `Food` are a modeling shortcut**,
  not a real per-100g nutrition fact — `serving_size=100`/`serving_unit=<description>` exists
  so "1 serving" reproduces the estimate exactly, but if this `Food` row were ever logged
  again at a *different* quantity (it currently never is — `savePhotoEstimate` always logs
  exactly 1 serving), the math would silently assume the original estimated amount scales
  linearly with grams, which it was never designed to represent. Revisit if photo-estimate
  foods ever need to be reused rather than treated as one-shot.
- **No deploy this session** — unlike sessions 9/10, nothing in the task text asked for
  `./deploy.sh`; both parts are commit-only, ready to deploy whenever the user asks.

**A final advisor-driven pass (after the above was believed done) found three more real
issues, each verified by actually reproducing it rather than inferring it from code:**

- **CLAUDE.md itself still carried the old, corrected-everywhere-else OFF claim** —
  `openfoodfacts_client.py (barcode-only OFF v2 lookup...)` and `usda_client.py (... used for
  free-text search since OFF has none)`, left over from before the opt-in redesign. A
  targeted grep for the earlier `"debounce is sufficient"`-era wording had missed this
  because the phrasing here predated even that — it was the *original* wrong claim, not a
  later draft of the correct one. Fixed, since CLAUDE.md is loaded as instructions into every
  future session and the stale claim could lead one to "clean up" OFF search as dead code.
- **`searchOff`'s stale-request guard could leave the "Also search Open Food Facts" button
  permanently disabled.** Its own `finally` only clears `searchingOff` when `queryRef.current`
  still equals the query that started the call — exactly right for *that* call, but nothing
  else ever cleared the flag for the *new* query once the athlete typed again before the old
  call resolved. Reproduced live in a browser (not just read): removing the fix and replaying
  tap-button-then-retype via a single Playwright script left the button `disabled: true`
  after the query changed; restoring the fix (resetting `searchingOff` in the same effect that
  already resets `offIncluded`/`error` on query change) made it `disabled: false`.
- **The mock couldn't actually demonstrate the feature it was supposed to showcase.**
  `mockFoodSearch` ignored `includeOff` entirely, so `?mock=1` had no way to show the OFF
  fallthrough finding anything local/USDA mocks didn't already have. Added one OFF-only mock
  food; discovered via the same live-browser test that merely *returning* it from search
  wasn't enough — `logFood`'s mock only checks `MOCK_FOODS`, so picking the OFF-only result
  and tapping "Log it" failed with "Couldn't log that food." Fixed by having the OFF branch
  cache its hit into `MOCK_FOODS` on first search, mirroring the real backend's
  `_get_or_create_cached_food` (which already did this correctly — confirmed by reading it
  and adding `tests/test_api_nutrition.py::test_off_search_hit_can_actually_be_logged`, a
  round-trip test: search with `include_off=true` → log the returned id → assert it succeeds).
  This is the general lesson: a clean `tsc`/`oxlint`/unit-test pass only proves the code
  compiles and each piece does what its own test says — it says nothing about whether the
  pieces actually connect into a working end-to-end flow a person would use. That needs
  driving the real UI, mock or not.

## Session 14 checklist

The task: a gym logger (offline-first, equipment-aware load math, exercise library, rest
timer, templates, PRs), merging a Catch lifting session with a Garmin strength activity, and
splitting daily strain into cardiovascular and muscular components. **Numbering note**: the
task's own prompt called itself "session 10," but that slot (an offline-detection bug fix and
a PWA-update-toast rewrite) and session 11 (chart-zoom-button removal) were already taken in
this file, with sessions 12/13 after them — recorded here as **session 14**, the next free
slot, to keep this log's numbering consistent with the repo's actual history; CLAUDE.md's
inline references use "session 8/12"-style dual numbering for exactly this reason elsewhere.

### Part A — pure math + data model

- [x] **Equipment load math** (`catch/analytics/equipment.py`, TS port `web/src/lib/
      equipment.ts`): barbell/smith (plates-added + a per-gym bar weight, Smith's defaulting
      to "unknown, enter once" per the task), dumbbell/kettlebell (per-hand, doubled when
      bilateral), plate-loaded/selectorized machine (a station's own base weight/stack
      calibration), cable (stack number x a 1:1/2:1/4:1 pulley multiplier — compared only on
      the same station, never across gyms), bodyweight/weighted/assisted (the latest resolved
      Withings/Garmin/manual weight, `catch/sync/body_comp.py`), band (an approximate
      light/medium/heavy kg tag, always flagged estimated). A greedy plate calculator.
      `tests/analytics/test_equipment.py` (29 cases) + `web/src/lib/equipment.test.ts` (16).
- [x] **e1RM, PR detection, muscular load** (`catch/analytics/strength.py`): Epley e1RM capped
      at 10 reps; rep-PR (heaviest at that exact rep count) and e1RM-PR, warm-ups excluded
      from both; per-working-set muscular AU = `reps x effective_load x intensity_factor`,
      where `intensity_factor` reuses Epley's own reps-to-%1RM shape over an RIR/RPE-derived
      "reps to failure" estimate (sets far from failure count less, task's explicit ask);
      distributed to primary (full credit)/secondary (half credit) muscles; normalized against
      a 28-day per-muscle baseline, clamped `[0.4x, 2x]`, cold-start-safe. Full formulas in
      `docs/analytics.md` §22. `tests/analytics/test_strength.py` (24 cases).
- [x] **Exercise library seed** (`catch/seed/exercises.json`): yuhonas/free-exercise-db
      (Unlicense/public domain — confirmed via a web fetch of the repo's own README badge,
      the LICENSE file itself 404'd so the Unlicense reading rests on that badge, not the raw
      license text), filtered to strength/powerlifting/olympic-weightlifting/strongman
      categories (678 of 876), vendored JSON only (no images), `movement_pattern`/
      `unilateral` derived by a documented name/force/category heuristic (the source dataset
      has neither field) and always user-editable. Seeded idempotently on every startup
      (`catch/core/db.py`'s `_seed_exercise_library`) — never overwrites an athlete's edit to
      an already-seeded row. Lives at `catch/seed/`, not `catch/data/` — the repo's `data/`
      gitignore rule is unanchored and silently swallowed the file on the first attempt;
      caught before committing, not after.
- [x] **Models** (`catch/core/models.py`): `Exercise`, `Gym`, `GymStation` (per-gym equipment
      config, "one tap next time" — task's explicit ask), `StrengthSet` (every equipment-math
      input snapshotted at log time, `client_id` the idempotent upsert key, `exercise_id`
      nullable only for an unmatched Garmin-draft import), `StrengthTemplate`. No Activity
      schema change needed at all — a Catch lifting session reuses the existing table as-is
      (`source="catch_strength"`). `CanonicalActivity` gained `muscular_load_au`/
      `muscular_by_muscle_json` (cached the same way `strain_trimp`/`zones_json` already are).

### Part B — merging with Garmin

- [x] **A Catch lifting session is an `Activity` row** (`catch/sync/gym.py`'s
      `get_or_create_session`, reusing `catch.sync.upsert.upsert_activity` unchanged) with
      `source="catch_strength"`, `external_id=` the client-generated session UUID — the
      matching engine, canonical resolution, and every "an activity" reader work on it with
      no special-casing beyond what's below. Session window = first set −10min / last set
      +5min, recomputed on every set add/delete.
- [x] **Matching**: `catch_strength`'s `sport_family`/`is_indoor` added to
      `catch/analytics/matching.py`; a dedicated `_match_strength_pair` rule (simple time-
      overlap, scored on overlap fraction) replaces the generic 3-minute-start/duration-ratio
      rule for the strength family — the padded Catch window and a real Garmin
      `strength_training` recording's own duration have no reason to track each other closely,
      which the generic rule's duration-ratio check would often wrongly reject.
- [x] **Field priority** (`catch/sync/canonical.py`): HR/calories/duration/start use
      `["garmin", "catch_strength"]` when merged (Garmin wins when both exist, task's literal
      ask) — `catch_strength` still has to be last in that list, not absent, so a Catch-only
      session falls back to its own computed window rather than every field going `None`.
      Sets are untouched by field priority either way — always `StrengthSet` rows.
- [x] **Garmin-draft import** (task's "if the FIT file contains exercise sets and I logged
      nothing in Catch, import them as a draft I can fix"): `catch/sync/fit_parse.py`'s
      `parse_fit_sets` reads FIT `set` messages (`repetitions`/`weight`/`category`/
      `set_type`) — field *names* confirmed live against this account's one real strength FIT
      file (`data/fit/24650449177.fit`), but that file's single `set` message is the
      unstructured whole-workout wrapper (`set_type="active"`, `repetitions`/`weight`/
      `category` all `None` — the watch never used its own rep-counting feature for that
      session), so the *populated* shape is unverified against live data, same situation
      session 2 documented for Concept2 before any real result existed; synthetic-fixture
      tested instead (`tests/test_fit_parse.py`). `catch/sync/gym.py`'s
      `import_garmin_draft_sets`/`confirm_draft_set`: only imports when no real Catch-logged
      set already exists for that physical session, best-effort exercise-name matching
      against the raw category (no reliable mapping onto Garmin's own ~100-value enum
      exists), `exercise_id=None` left honestly unmatched rather than guessed, counted toward
      nothing (PRs/muscular load) until the athlete confirms it.
- [x] **No-watch sessions still count** (task Part B.3): a Catch-only session has no Garmin
      counterpart to merge with, keeps its own computed window via the field-priority
      fallback above, `category_for_canonical` gives it a dedicated `"strength"` category
      (was folded into `"other"` before this session — `category === "other"` call sites in
      the frontend needed updating to `"strength"` once this changed, caught by `tsc`/the
      mock-data build, not a runtime surprise).

### Part C — cardio/muscular strain split

- [x] **`catch/sync/scoring.py`'s `day_strain`** now combines cardio (existing HR/power
      `trimp_like`, its own log-saturation curve) and muscular (today's per-muscle AU,
      28-day-normalized, summed, its own independent log-saturation curve) **before** summing
      as 0-21 values, with daily-activity (session 13) added last — kept independent
      specifically so a heavy lifting day with zero cardio trimp still registers real strain
      (task's explicit requirement), which one shared curve over a combined number couldn't
      guarantee. New `Settings` keys `muscular_strain_log_a`/`muscular_strain_weight`,
      calibrated (not just asserted) against a heavy-squat-day/light-pump-day/long-UT2-erg
      comparison test. Full curve in `docs/analytics.md` §22.
      `tests/test_scoring.py`: zero-cardio-still-meaningful, heavy > light > erg (erg's own
      muscular share is exactly 0 with no lifting that day), and a repeat-of-a-normal-week
      lands near its own baseline rather than spiking.
- [x] **Cardio's own small muscular share** (erg/bike, task Part C.1.2): time above ~110% of
      threshold power (the existing rowing/cycling threshold resolution) x a small scale
      constant, added to canonical.muscular_load_au directly in `catch/sync/canonical.py`'s
      `_resolve_zones` (generalized to run for rowing too, not just the cycling-only TSS
      branch it used to be scoped inside) — no per-muscle breakdown, no 28-day normalization,
      "default low" per the task.
- [x] **Muscle readiness** (`GET /api/gym/muscle-readiness`, `catch/sync/gym.py`): raw
      (non-normalized — a display of real recent load, not a strain-curve input) per-muscle
      AU over the trailing 72h. Frontend: `MuscleReadiness.tsx` + `MuscleBodyMap.tsx`, a
      schematic (not anatomical) front/back SVG shaded by load (one accent-opacity ramp, same
      idea as `zoneColors.ts`'s training-zone ramp — see DESIGN.md), plus a numeric list
      (never colour alone).
- [x] **UI**: Today's `StrainGauge` shows a three-segment fill (cardio/muscular/daily-
      activity, three opacities of the one accent) plus a text legend; `WorkoutDetail.tsx`
      gained a `"strength"` category branch (muscular-load-per-muscle card + a sets table
      with PR badges and unconfirmed-draft flagging); Workouts' category filter and the
      coach's `list_workouts`/MCP `type` enum all gained `"strength"` alongside erg/on_water/
      other.

### Part D — gym logger frontend + coach/MCP

- [x] **Offline-first** (task's explicit "never lose a set"): `web/src/lib/gymDb.ts`
      (hand-rolled raw IndexedDB — one `sets` object store, no wrapper library, matching this
      app's existing hand-rolled-over-small-dependency precedent) + `gymSync.ts` (every write
      lands in IndexedDB *before* any network attempt; a background flush upserts to the new
      idempotent `POST /api/gym/sessions/sync`, safe to retry/resend freely). **No bespoke
      IndexedDB mirror of the exercise library/gyms/templates/readiness was needed** — every
      GET under `/api/*` already gets network-first-with-cache-fallback from the service
      worker itself (`vite.config.ts`), the same generic mechanism Today/Workouts already
      lean on for offline viewing; building a second, gym-specific cache for the same data
      would have been pure duplication, caught and removed before committing.
- [x] **Sync trigger, a real gap found by the Playwright suite below, not guessed**:
      `useOnlineStatus`'s own 15s-interval probe can go an entire short reconnect window
      without ever toggling its boolean (nothing forces a tick), which left the queue
      genuinely stuck after a `context.setOffline(false)` in testing — not a test-timing
      quirk, a real gap "never lose a set" doesn't cover if sync never resumes. Fixed by also
      listening for the browser's own `online` event directly in `useGymSync.ts`, independent
      of the debounced probe value.
- [x] **Equipment-aware logging UI** (`web/src/components/gym/`): `ExerciseBlock` (equipment-
      type picker with the right follow-on fields per type — bar weight/plate-calc for
      barbell+smith, station+pulley-ratio for cable, bodyweight-missing warning for
      bodyweight/weighted/assisted, a band-tag select), `Stepper` (big tap targets,
      plate-sensible load increments per equipment family), `ExercisePicker` (search the
      cached library or add a custom exercise inline), `RestTimer` (auto-starts, computed
      from a stored end timestamp rather than accumulated `setInterval` ticks — a
      backgrounded PWA suspends JS timers, so an accumulate-based countdown would be wrong by
      however long it was backgrounded; Web Audio beep since iOS Safari has never implemented
      `navigator.vibrate`), `PlateCalculatorDialog`, last-session numbers shown inline
      (`GET /api/gym/exercises/{id}/last`), "same as last set," repeat-last-workout and
      templates to start a session.
- [x] **`Gym.tsx`**: hub (start blank / repeat last workout / templates / muscle-readiness
      link) and active-session logging in one page — resumes today's existing IndexedDB
      session on mount (so a closed-and-reopened app, or a second coach-logged set later the
      same day, lands in the same session rather than fragmenting it), offline-first
      throughout. New `GymIcon`, added to both `Sidebar` and `BottomNav`.
- [x] **Coach/MCP** (`catch/coach/tools.py`, `catch/mcp_server/server.py`): `log_strength`
      (free text via a documented best-effort regex parser — one exercise per call, matching
      the task's own example — or a structured sets list; always previews first, a confirm=
      true call is required to actually save, same two-step pattern `merge_activities`
      already established, since a misparsed exercise/load should never write silently),
      `get_strength`, `get_muscle_readiness`. 24 MCP tools now (was 21); `chat.py`'s tool-chip
      labels and `web/src/lib/toolLabels.ts`'s mirror both updated; `system_prompt.md` gained
      guidance on checking muscle readiness before commenting on lifting and avoiding heavy
      leg work the day before a hard erg session/2k test.

### Quality bar / real verification

- [x] `uv run pytest` — **496 passed** (was 476 before this session's backend-only commit,
      441 before this session at all). `cd web && npx tsc -b && npm run build` — clean,
      `Gym`/`MuscleReadiness` each their own lazy chunk (27.8KB/4.2KB gzip). `cd web && npm
      run test` (Vitest) — **36 passed** (20 prior + 16 new `equipment.test.ts` cases).
      `cd web && npm run test:touch` — unchanged, 17 run / 7 correctly skipped. `cd web && npm
      run test:update` — unchanged, 4 passed.
- [x] **`cd web && npm run test:gym`** — a new Playwright suite (`playwright.gym.config.ts`)
      built specifically for this session's offline requirement: a real disposable
      `uv run uvicorn catch.main:app` backend (scratch SQLite DB in a temp dir, a freshly
      argon2-hashed password and a freshly generated Fernet key, `SYNC_INTERVAL_HOURS=24` so
      APScheduler's own first-fire-after-one-interval behavior means no real Garmin/Withings/
      Concept2 sync job can fire during the run even with every source's key left unset — no
      live-network-call risk per CLAUDE.md's rule), a real registered service worker, real
      IndexedDB. Logs in for real, visits `/gym` once online (populating the SW's own API
      cache), goes offline via `context.setOffline(true)`, starts a session, adds "Barbell
      Squat" from the real seeded library, logs 3 sets with real plate-math effective loads,
      **reloads the page while still offline** (confirms nothing is lost on a closed/reopened
      app, not just a dropped connection), reconnects, confirms the sync-status badge settles
      to "Synced" with no user action, then asks the real backend directly (`GET /api/
      activities?category=strength`, `GET /api/activities/{id}`) that the three sets actually
      landed with the correct effective loads (`[80, 90, 100]` — 60/70/80kg entered + the
      default 20kg bar). Ran 3 times in a row, no flakes. This is the substitute for the
      task's "use the logger on my phone as the installed PWA with airplane mode on" — this
      environment has no real iPhone, same documented gap as session 10's equivalent
      placeholder.
- [x] **Screenshots at 390px, both themes** (Playwright MCP, `?mock=1`): Gym hub, an active
      session with a logged set + running rest timer, the exercise picker, Muscle Readiness
      (front/back map + list), Today's three-way strain-gauge split, and a strength
      `WorkoutDetail` (muscular-load card + sets table with a PR badge) — all reviewed in both
      light and dark. Found and fixed one real layout bug this way, not by reasoning about the
      CSS: adding an 8th bottom-nav item clipped "Workouts" and "Settings" off the right edge
      of a 390px screen (not just visually tight — actually unreadable); fixed with `min-w-0`
      + `truncate` (session 4's established flexbox-overflow fix, applied here too) plus
      shortening "Workouts" to "Log" in the bottom nav specifically, so nothing has to
      truncate in practice. See DESIGN.md's "Bottom nav at 8 items" note.
- [x] **Not attempted this session, by explicit scope choice**: a `GymStation`/`Gym` CRUD
      *page* (stations/gyms can currently only be created/edited via the API directly, or via
      a future Settings addition — `ExerciseBlock`'s cable-station picker reads existing
      stations but there's no in-app "add a gym/station" form yet); Trends gained no new
      muscular-load-over-time chart or weekly-volume-per-muscle-group view (the data exists —
      `CanonicalActivity.muscular_by_muscle_json` — but wiring a new Trends metric + chart was
      judged lower priority than the offline logging core and the strain split, given the
      session's time budget); superset/circuit grouping has a `superset_group` column end to
      end but no dedicated UI for entering or displaying a group as a unit (sets log and
      display individually regardless of the field). None of these block the core loop —
      logging a set, equipment math, offline sync, the Garmin merge, or the strain split —
      flagged here honestly rather than silently left out.
- [x] **Live Pi deployment not attempted this session** — same as several prior sessions,
      nothing in the task asked for `./deploy.sh`; this is commit-only, ready to deploy
      whenever asked. The real strength FIT file's field-name verification above *was* done
      against this account's live data (read-only, via `sqlite3 -readonly` against the real
      `data/catch.db` and `fitdecode` against the real FIT file on disk) — the one piece of
      "real data" verification this session's scope allowed without a live deploy.

## Gotchas / deviations from the literal task spec

- **Session numbering**: this is "session 14" in this file's own sequence, not literally
  "session 10" as the task text called itself — see the checklist's own numbering note above.
- **Exercise category assignment, movement pattern, and the unilateral flag are a documented
  heuristic**, not data the source dataset provides (it has neither field) — see Part A above
  and the seed-build note in this session's own history. Always user-editable; never treated
  as authoritative by anything downstream (muscular-load math reads the *current*, possibly
  user-corrected, row at log time).
- **Smith-machine and cable-pulley conventions have no universal standard**, so this session
  picked one and documented it rather than guessing at "the" right answer:
  `load_kg` for barbell/smith is plates-added, not a total (a separate `bar_weight_kg`
  completes it); a cable's `pulley_multiplier` is the felt-load *fraction* (0.5 for a 2:1
  block that halves the load), not the ratio notation itself. Both are spelled out in
  `catch/analytics/equipment.py`'s module docstring and `docs/analytics.md` §22 specifically
  so a future session doesn't have to re-derive the convention from the code.
- **Muscular-load AU is an arbitrary unit scale**, calibrated only so the relative comparisons
  the task cares about hold (heavy day > light day, lifting > cardio's small share) — not
  validated against any external measure of training load, same epistemic status as
  `trimp_like`/sRPE already had before this session.
- **The coach's `log_strength` free-text parser is a plain regex, not real NLP** — handles
  the task's own example shape (`"3x8 cable row stack 12 on station 2"`) and similar
  one-exercise-per-call phrasings, not arbitrary natural language. This is exactly why the
  tool always previews before `confirm=true` saves, rather than a documentation caveat papering
  over a real gap.
- **No `GymStation`/`Gym` management page** — see the checklist's "not attempted" note. A
  station already in the DB (seeded by hand or via the coach/API) works fully in the logger;
  creating a new one from the app itself needs direct API calls for now.

## Session 15 checklist

The task called itself "session 11" and referenced a future "session 12" — this file's own
numbering already used both (session 11: on-chart zoom buttons removed; session 12: the
task that opened *that* session also mis-numbered itself "session 8," and that session's own
note already established the precedent of continuing this file's numbering regardless of what
the task text calls itself). Continuing that precedent, this is session 15.

The task: a morning check-in (Part A), an illness early-warning signal (Part B), and an erg
test center (Part C).

- [x] **Part A, morning check-in**: `checkins` table (date-keyed, one row/day, editable later
      the same day via upsert), 4 sliders (soreness/stress/mood/sleep quality) + an optional
      niggle (body area + 1-3 severity) + a free-text note. `catch/analytics/checkin.py`'s
      `checkin_recovery_score` feeds a 5th, **additive** recovery-weight component (default
      0.15) — additive, not a slice taken from the other four, specifically so a day with no
      check-in scores *identically* to before this feature existed (locked in by a direct
      test asserting the two calls return the same value). A niggle never touches the number
      at all (`checkin_recovery_score` only reads the 4 sliders); it's purely a flag —
      `GET /api/today`'s `checkin.niggle_flag` after `niggle_flag_min_days` (default 3)
      consecutive days, surfaced unprompted in the coach's per-turn memory block. Trends
      gained the 4 sliders as metrics (`checkin_soreness`/`stress`/`mood`/`sleep_quality`).
- [x] **Part B, illness early warning**: checked Garmin's real OpenAPI spec directly before
      building anything — **no skin-temperature field exists anywhere in the Personal API**
      (the only "skin"/"temp" hit is an unrelated menstrual-cycle-tracking boolean), so that
      planned signal was dropped and documented as a genuine absence, not an unconfirmed
      field (`docs/garmin-endpoints.md`). Nightly respiration *does* exist
      (`DailySleepDTO.averageRespirationValue`, sleep-service) but wasn't wired into the sync
      before this session — now mapped to a new `sleep_respiration_avg` column, distinct from
      the pre-existing whole-day `respiration` column. `catch/analytics/illness.py` scores
      resting HR/HRV/nightly respiration/check-in-mood-and-soreness, each against its own
      30-night baseline (SD floors per signal so an integer-reported metric's small real
      wobble can't read as a multi-SD deviation; a minimum baseline-night count per signal).
      Levels none/watch/likely: "likely" needs 2-night persistence as a hard requirement (not
      just a boost), and is capped back to "watch" when a high acute:chronic ratio alone
      explains resting HR/HRV with no respiration/check-in corroboration — the discriminator
      that keeps a hard training block from ever reading as "likely" while a real 2-night
      illness pattern still does. Wording is fixed and non-diagnostic ("your body is showing
      signs of strain or illness," signals listed) — covered by a test asserting "sick"/
      "diagnos" never appear. Computed output (`daily_scores.illness_json`) is rewritten on
      every recompute like every other score column; user-owned state (dismissed/reason, a
      backtest mark, `first_flagged_at`) lives in a separate `illness_acks` table that
      recompute only ever inserts into, never overwrites. A dismissed-with-reason or
      already-"likely" day is excluded from every later day's baseline. `GET /api/today`'s
      recommendation caps outright at "likely" (no tests, no TR/AN) regardless of what the
      recovery band itself says. `GET /api/illness/backtest` lists every historically flagged
      night with precision over whatever the athlete has actually marked.
- [x] **Part C, erg test center**: no new table for "a test" — it's a `CanonicalActivity`
      whose existing free-form `overrides_json` carries `{"tags": ["test"], "test_type":
      "2000m"}`, confirmed through the existing `PATCH /api/activities/{id}`.
      `GET /api/tests/candidates` auto-detects untagged Concept2 pieces against the 8 standard
      types (distance within 2%, duration within 25s, `30min_r20` additionally gated on
      average stroke rate ≤ ~20.5) — a suggestion to confirm, never auto-applied. Pacing-plan
      generator (`make_pacing_plan`/`POST /api/tests/pacing-plan`): per-500m targets scaled to
      sum exactly to the goal time, 3 illustrative shapes (even/fast-start-settle/negative-
      split); saves to the athlete's next upcoming event of *any* type by default when called
      as a coach tool (deliberately broader than `next_a_race`'s A-race-only filter — a plan
      is just as often for an upcoming test as a race). Pacing analysis: start/middle-1000/
      sprint, deviation from even split, the single worst split, a split-by-split comparison
      against a saved plan (best-effort distance match, documented as a simplification).
      Projection: an OLS trend through this test type's PB history to the next A race's date,
      ±1-residual-SD band, refuses outright below 3 points rather than fitting noise, inputs
      always listed. 3 new coach/MCP tools (`get_tests`/`get_test`/`make_pacing_plan` — 27
      tools total now).
- [x] **Frontend**: a bottom-sheet check-in dialog (auto-opens once/day, date-keyed, editable
      later; gated behind an explicit `?checkin=1` in mock mode so it never blocks the
      existing `test:touch` suite, which runs under plain `?mock=1`), an illness card with
      the fixed wording + dismiss-with-reason, an "Illness detector backtest" card on
      Settings, and the erg test center (`TestCenter`/`TestDetail` pages) reached via the
      Sidebar and a Workouts-header link — **no new bottom-nav slot**, per DESIGN.md's
      existing note that 8 items is already tight. Screenshotted at 390px/1280px in both
      themes; found and fixed two real bugs this way (see Findings below). `npx tsc -b`,
      `npm run build`, `npm run test` (36/36), `npm run test:touch` (17/7-skipped), and
      `npm run test:update` (4/4) all pass.
- [x] Tests: 94 new backend tests (563 total, all passing) — `checkin.py`/`illness.py`/
      `erg_test.py`'s pure math (including the three illness fixtures the task named
      explicitly: a real illness pattern reaching "likely" only on night 2, a single bad
      night after a late party capped at "watch," a hard training block never reaching
      "likely" even with persistence), the full check-in/illness/erg-test API surface, the
      recompute-insert-only-never-overwrites guarantee, baseline exclusion, the coach memory
      block, and the 3 new coach tools. Frontend: 36 Vitest + the existing Playwright suites
      unaffected.
- [x] Deployed to the Pi (`./deploy.sh`) — healthy (`{"ok":true}`), `version.json` confirms
      `"commit":"20513ae"` (this session's frontend commit). PLAN.md + commit.

## Findings from screenshot/test verification (frontend, 2026-11-05)

- **A dialog-vs-bottom-nav z-index gap only a bottom-sheet dialog could expose.** Every
  existing `Dialog.Content` in this app was centered (`top-1/2`) and never reached the
  viewport's bottom ~52px; the new check-in sheet is a bottom sheet on mobile specifically
  for thumb reach, and without an explicit `z-30` its Save/Skip buttons painted *underneath*
  `BottomNav`'s `z-20` — two `position: fixed` siblings, one with an explicit z-index beats
  one without regardless of DOM/portal order. Fixed with `z-30`, matching the nutrition
  dialogs' existing (until now, never actually exercised at that edge) convention.
- **Trends' metric picker growing 4 buttons taller at 390px pushed the chart's tap point
  under the bottom nav** — a real regression in `test:touch`'s drag/pinch/press-hold tests
  (confirmed against `main` via `git stash`), not just a cosmetic shift. Fixed by collapsing
  the new check-in metrics behind a "More metrics" toggle rather than adding them inline,
  keeping the picker's default height — and the chart's position — unchanged.
- Two mock-data bugs caught by screenshot review: `fetchTodayCheckin()`'s mock ignored the
  scenario param, and a workout mock-tagged "2000m" actually carried a random 6000m distance
  from the generic fixture generator.

## Gotchas / deviations from the literal task spec

- **Session numbering** — see the checklist's own note above; this is session 15, continuing
  the file's own sequence.
- **No skin-temperature signal** — a hard absence in Garmin's Personal API, not an
  unconfirmed field with a column waiting. See Part B above and `docs/garmin-endpoints.md`.
- **The illness backtest's real precision over this account's actual history was not
  reported here** — reporting a number requires logging in as the athlete to mark nights
  right/wrong (`POST /api/illness/{date}/mark`), which this session correctly declined to do
  on the athlete's behalf (no access to the real password, and marking backtest ground truth
  is a judgment call only the athlete can make). The illness detector *is* live on the
  deployed Pi and will score the real history on the next sync (automatic within the
  scheduler's 2h interval, or immediately via "Sync now" on Today) — open Settings'
  "Illness detector backtest" card afterward to review and mark it.
- **A pre-existing, unrelated, uncommitted fix to `catch/sync/withings_client.py`/
  `docs/withings-endpoints.md`** (the `getmeas` endpoint's URL path — no `/v2/` prefix,
  confirmed against Withings' own spec, dated today) was sitting in the working tree at the
  start of this session, left over from unfinished prior work. It was never touched, staged,
  or committed as part of this session's own commits — `git stash`ed only for the duration of
  `./deploy.sh` (which rsyncs the whole local `catch/` tree, uncommitted changes included) so
  it wouldn't ship silently alongside session-15 code, then restored immediately after. It's
  still sitting uncommitted in the working tree, exactly as found, for whoever picks it up.
- **The erg test center's pacing chart is a small static bar chart (`SplitBarChart`), not an
  `ErgChart` extension** — `ErgChart`'s pan/zoom/domain-state machinery exists for long, dense
  per-stroke recordings; a test's pacing view is at most ~12 bars. The full interactive
  stroke/HR chart for the same activity stays one tap away via a link to workout detail
  rather than being duplicated on the test page.
- **No dedicated "confirm a candidate as a different type than suggested" or
  "mark as not a test" UI** — `TestCenter` confirms a candidate as its suggested type; a
  misclassified candidate can still be tagged correctly via the existing generic workout-edit
  tag UI, just not from the test-candidates list itself. Flagged honestly rather than
  silently narrowed in scope.

## Session 16 checklist

The task called itself "session 12." This file's numbering already used sessions 11 and 12
(see session 15's own note above) — continuing that established precedent, this is session
16. Session 15's `IllnessAck` docstring had already anticipated this exact session
("a future notifier... whichever session adds notifications") by leaving `first_flagged_at`
in place for it.

The task: push notifications (Part A), monitoring (Part B), and CI (Part C).

- [x] **Part A, push notifications**: Web Push implemented directly on `py-vapid` +
      `http-ece` + `httpx` (`catch/notify/push.py`) rather than the full `pywebpush` package,
      which transitively pulls in `requests` *and* `aiohttp` (plus aiohttp's compiled deps)
      for a `.send()` method this app never calls — the real POST goes through `httpx`
      directly, so the existing live-call guard covers it for free. VAPID keys generated and
      written to `.env` (see "Secrets" below). Round-trip tested for real: encrypt with
      `push.py`, decrypt with `http_ece.decrypt` using a fake browser subscriber's own
      private key — the actual security property Web Push depends on, not just a mocked HTTP
      call. `PushSubscription`/`NotificationLog` tables; `catch/api/routes_push.py`
      (vapid-public-key served at runtime — never baked into the build, since the laptop that
      builds doesn't necessarily have the Pi's `.env` — subscribe/unsubscribe/list/per-device
      test-send, prunes a subscription on 404/410). Five notification types
      (`catch/notify/triggers.py`, full trigger/dedup table in `docs/notifications.md`):
      morning brief (wake time from Garmin sleep data via a new `DailyWellness.
      wake_time_minutes`, syncs Garmin first so it's never describing yesterday), illness
      (hooks the `first_flagged_at` session 15 left waiting, re-checks the *current* level in
      case a later recompute downgraded it), Garmin-key-expiry (14/3/1 days), sync-broken
      (edge-triggered on `SyncState.consecutive_failures` crossing 3, or 36h with no
      successful sync), test-center day-before reminder. Quiet hours + per-type toggles live
      in the existing settings JSON blob. Frontend: `lib/push.ts` (iOS's user-activation
      ordering constraint — `Notification.requestPermission()` must be the tap handler's
      first call, so the VAPID key is fetched separately on mount), `NotificationsCard`
      (enable/disable, per-device test-send, toggles, quiet hours, an "add to home screen
      first" message for un-installed iOS Safari), and `push`/`notificationclick` handlers in
      the generated service worker (`App.tsx` navigates via a `postMessage`, not
      `WindowClient.navigate()`, which has real gaps on iOS standalone WebKit).
- [x] **Part B, monitoring**: `GET /api/status` + its own Status page (`/settings/status` —
      not a Settings card, so the sync-broken/Garmin-key push notifications have an
      operational screen to deep-link to): per-source sync health, Garmin key expiry, backup
      status, disk/DB size, uptime, build/commit. Dead-man's-switch pings to healthchecks.io
      — the app itself pings after every successful individual-source sync (the three
      sources run as independent scheduler jobs, not one combined "cycle"); the nightly
      backup pings separately from `deploy/backup.sh`, since that runs entirely outside the
      Python app via its own systemd timer. `deploy/backup.sh` gained a `PRAGMA
      integrity_check` on the local copy, an off-Pi scp copy to a laptop over Tailscale
      (`BACKUP_SCP_TARGET`) when it happens to be reachable right now — skipped silently, not
      alerted, when it isn't, since the task asks for "when reachable," not guaranteed
      delivery — remote 30-backup retention (scp can't delete, so this prunes over the same
      ssh connection), and a `status.json` (temp file + `mv`) the Status page reads.
      `deploy/pi-bootstrap.sh` now generates the `catch` user's own SSH key for this and
      prints the laptop-side setup steps. ntfy.sh as an optional second ops-alert channel for
      sync-broken specifically. Dry-run tested by hand against a scratch SQLite file (a real
      backup + prune-to-14 run, and a deliberately corrupt DB exercising the integrity-check
      failure path) — `backup.sh` has no CI coverage (dash, Pi-only tools: `sqlite3`, real
      SSH), so this is the extent of pre-deploy verification possible from here.
- [x] **Part C, CI**: `.github/workflows/ci.yml` — Python (`uv sync --locked`, `ruff check`,
      `pytest`) and frontend (typecheck, lint, Vitest, production build, a 250KB-gzip
      bundle-size check, `node --check` on the generated service worker, then the full
      Playwright suite — now three projects: the two existing iPhone-profile ones plus a new
      `desktop-mouse` project for the task's "mouse ... profile" requirement — against that
      real build via `vite preview`) as two parallel jobs, nothing needing secrets. `ruff`
      added (minimal ruleset — F + a few E7xx logic checks, no stylistic churn); 18
      pre-existing unused-import/variable findings fixed, zero behavior change. `Makefile`'s
      `make check` runs the exact commands CI does. `deploy.sh` refuses a dirty working tree
      or a failing `make check`, and prints the build/commit actually live on the Pi after a
      successful deploy. README badge + a short "before pushing" note.
- [x] Also fixed, pre-existing but unrelated, found along the way: `catch/sync/
      withings_client.py`'s `getmeas` URL (`/v2/measure` → `/measure`, confirmed against
      Withings' own spec) — this was sitting uncommitted in the working tree at the start of
      this session (noted, but not touched, by session 15's own writeup); committed first,
      separately, before any session-16 work.

## Bugs an advisor review caught before this session's work was declared done

- **The test suite had a hidden dependency on the real `.env`'s `CATCH_FERNET_KEY`/VAPID/
  ntfy/healthchecks values** — 17 tests calling `security.encrypt`/`decrypt` had no fixture
  setting a Fernet key at all, silently riding on whatever real key happened to be in
  whichever machine's `.env`. Invisible locally (563/563 passing) until the very first real
  GitHub Actions run (no `.env`, by design) turned it into 17 failures. Fixed with one
  autouse fixture giving every test a fixed, test-only Fernet key — then, when the same
  pattern threatened to bite again for the new VAPID/ntfy/healthchecks settings (this
  laptop's `.env` now has real-looking values for those too), fixed generally: those fields
  are blanked once, directly on the shared `Settings` singleton every module's own `from
  catch.core.config import settings` already points at (`object.__setattr__`, bypassing the
  frozen dataclass — `monkeypatch.setattr` hits the same frozen guard a plain `setattr` call
  does). Both are real, load-bearing reasons to stand up CI now rather than later: a passing
  local suite was never proof the suite would pass anywhere else.
- **`check_illness` would have fired one push per historical "likely" night on first
  deploy.** `recompute_scores` is insert-only on `IllnessAck` (by design — see its
  docstring), so session 15's already-live DB has any number of `first_flagged_at`-set rows
  with `notified_at` still NULL, simply because the notifier didn't exist yet when they were
  flagged. Fixed: only today's/yesterday's flag is ever considered; anything older (or a
  flag a later recompute has since downgraded away from "likely") is marked handled without
  ever sending.
- **`check_morning_brief` would have described yesterday most mornings** — built straight
  from whatever `GET /api/today` already had cached, which at "wake + 30 minutes" is usually
  still yesterday's sync (the regular job runs on a 2h interval, not on waking). Fixed: calls
  `run_sync("garmin", days=1)` first (non-blocking — a no-op if the regular job happens to
  already be mid-run).
- **Verified, not assumed, that a real auth failure actually reaches `record_error`** — the
  task's own "break a source on purpose" quality-bar check depends on this. Concept2's
  `_check()` raises `Concept2AuthError` on a 401 (confirmed by reading the code, then locked
  in with a test); Garmin's regular per-call `_get()` does the same. The one place that *does*
  fail open — `garmin_client.py`'s `_call_with_backoff`, which swallows a persistent 401 into
  "0 rows for this window" — is backfill-only (`uv run catch backfill`), never used by the
  regular scheduled sync this feature actually watches.
- **The app's own `.env` parser doesn't support inline `"KEY=value  # comment"` trailers** —
  two of this session's own new keys (`VAPID_SUBJECT`, `NTFY_TOPIC`) were written that way in
  the real `.env` and silently picked up the comment text as part of their value (confirmed:
  `NTFY_TOPIC` came back as the literal string `"# optional, long random topic name"`, and
  `VAPID_SUBJECT` would have failed `py_vapid`'s `sub`-claim validation the first time a real
  push was attempted). Fixed those two lines directly. Deliberately did **not** change
  `load_dotenv`'s parsing behavior — `CATCH_SESSION_SECRET`/`CATCH_FERNET_KEY` already use
  the same inline-comment style and currently "work" only by luck (HMAC accepts any bytes as
  a key; Python's `base64.urlsafe_b64decode` silently discards non-alphabet characters before
  decoding, and the comment text's own letters happen to still assemble into something that
  decodes to 32 bytes). Changing the parser now would re-derive a *different* Fernet key than
  whatever key already encrypted any real OAuth tokens sitting in the live DB — flagged here
  for the user to decide whether to clean up those two lines' formatting themselves, rather
  than silently fixed by a session that can't verify what's already encrypted with the old
  (accidental) value.
- **A stuck CI run** — "Install Playwright browsers" hung for 30+ minutes on one push mid-
  session (an apparent GitHub-runner-side flake, nothing in this repo) while two later
  pushes' runs completed normally in ~1.5 minutes each, because no `concurrency` group
  existed to cancel the stale one. Added one.

## Secrets

- **VAPID keys were generated this session and written directly into the laptop's `.env`**
  (never printed to chat — only the public key, which isn't sensitive, was ever surfaced in
  conversation) — see `.env.example` for the regeneration one-liner if the user wants to
  rotate them. No device has subscribed yet as of this writeup, so rotating is still free;
  once a real phone subscribes, rotating means re-subscribing every device.
- **This session's `Read` of the real `.env`** (to append the VAPID values alongside the
  existing keys, matching session 2's `.env`-handling precedent) put every secret already in
  that file into this session's own transcript, the same category of exposure session 2
  flagged for a leaked Concept2 token. Nothing was echoed to chat or to any external service,
  but the user should decide for themselves whether any of those values are worth rotating
  given that exposure.

## Not yet done — needs the user

The task's own quality bar asks for live checks this environment cannot complete alone:

- **A real push notification to an installed phone PWA, confirming it arrives and deep-
  links.** Everything up to "the browser successfully subscribed and the server successfully
  POSTed an encrypted, VAPID-signed payload to the real push service" is built and testable
  from here; whether it actually surfaces on a lock screen and taps through to the right
  screen needs a real device.
- **Breaking a source on purpose (bad Concept2 token) and confirming the alert fires once,
  not repeatedly, then clears on fix** — safe to do live (Concept2 vs. Garmin specifically,
  since Garmin's token lives behind an OAuth exchange, Concept2's is a single stored static
  value — see `docs/notifications.md`), but it touches the real stored access token and
  should be a deliberate, watched action, not something run unattended.
- **A healthchecks.io account + its two check URLs** (sync, backup) — setup steps are in
  `.env.example`; both pings no-op harmlessly until they're filled in.
- **The off-Pi backup's laptop-side setup** (macOS Remote Login, adding the `catch` user's
  public key to `authorized_keys`) — `deploy/pi-bootstrap.sh` prints the exact steps and the
  key itself at the end of a run; nothing on the backup side depends on this being done
  immediately, the local 14-backup rotation runs regardless.
- **The actual Pi deployment** — `./deploy.sh`, after the two steps above (or without them;
  both are optional and no-op cleanly) and after copying this session's new `VAPID_*`/
  `HEALTHCHECKS_*`/`NTFY_TOPIC`/`BACKUP_SCP_TARGET` keys into `/var/lib/catch/catch.env`.

## Session 17 checklist

The task that opened this session called itself "session 13" — PLAN.md's own numbering
already used that number (nutrition), so this continues the file's own sequence instead, the
same resolution sessions 8 and 12 used for an identical collision.

Adding a piece (a segment of a canonical activity — a 2k inside a longer steady-state row, a
30r20, etc.) from a photo of the PM5 screen or typed/pasted splits, both ending in the same
editable review table that never silently "corrects" a bad reading.

- [x] **Part A — pieces**: new `Piece`/`PiecePhoto` tables (`catch/core/models.py`; the photo
      lives in its own 1:1 table so an ordinary `select(Piece)` — test-center listings,
      `resolve_all_canonicals`, coach/MCP reads — never has to pull image bytes along with
      it). `catch/analytics/piece.py` (pure): `PIECE_TYPES` reuses `TEST_TYPES`'/
      `TEST_SPECS`' exact vocabulary, `default_splits` (piece-type-aware templates),
      `validate_splits` (table-level time/distance-sum checks + per-row rate-plausibility and
      watts-vs-split-implied checks, via `erg_math.watts_from_pace`), `aggregate_from_splits`,
      `parse_time_token`/`parse_splits_paste` (paste support), `find_best_window` (Part D.1's
      auto-align scan). `catch/sync/piece.py` is the DB-facing half — create/update/delete,
      alignment, the Part D.3 power overlay, and Part D.4's Concept2 absorb (see below).
- [x] **Part B — photo**: `catch/coach/piece_vision.py` mirrors `nutrition_vision.py`'s
      strict-tool-use vision call (auto `tool_choice`, never forced — several current models
      400 on forced tool use), with one deliberate difference: every time value comes back as
      the screen's **own display string** (`"1:36.8"`), parsed into seconds in Python, never
      trusted to the model's own arithmetic. `_normalize_splits` handles two other real PM5
      display shapes a screen can show instead of cumulative-distance/per-split-time: a
      per-split distance column (500, 500, 500, 500 — cumulated) and a cumulative-elapsed-time
      column (recognized as strictly increasing with its last value close to the piece's own
      total — differenced). Validated server-side in the estimate response itself (task Part
      B.3's "validate before showing"), not only on save. The photo is attached to the piece
      only after the athlete confirms (`POST /api/pieces/{id}/photo`), hidden behind the same
      `anthropic_key.configured` check Nutrition's photo-estimate entry point already uses.
- [x] **Part C — typed splits**: `parse_splits_paste`/its TS mirror (`m:ss[.t] [rate]` tokens
      separated by `/` or a newline — matches the task's own example exactly), a shared
      pytest/Vitest test-vector fixture (`tests/fixtures/pieces/paste_vectors.json`) so the two
      parsers can't silently drift, and `TimeInput.tsx` — digit entry with auto-format
      (typing "1382" renders "1:38.2") since iOS's numeric keyboard has no colon.
- [x] **Part D — lining the piece up with the watch data**: `find_best_window` auto-suggests
      the window (an O(n) prefix-sum scan over the containing activity's own HR samples,
      tie-broken toward more defined data) whose average HR is highest; a manual drag on the
      HR graph's new band + start handle (`HrChart.tsx`) re-aligns explicitly. Per-split HR is
      derived on every align but never overwrites a typed/photo/Concept2-sourced reading
      (`hr_source` tagging). `power_member_and_samples` (called from `canonical.py`'s
      `_resolve_zones`, before `has_power` is computed) overlays each aligned piece's own
      per-split watts onto its window in the zones/strain pipeline — never a flat average,
      never outside the window — refining, not adding to, the activity's strain (verified
      directly: `strain_trimp` is byte-identical with and without the piece, since rowing
      strain stays HR-Banister-based regardless; the piece only refines the power-zone label
      and the muscular-load split). A later Concept2 sync wins over the typed/photo fallback
      (`absorb_concept2_piece_results`, run from `matching.py`'s `run_matching`) — see the bug
      log below for the real fix this needed.
- [x] **Part E — coach + MCP**: `add_piece` tool (free text like "my 2k was 6:32.4, splits
      1:36.8, 1:38.9, 1:39.0, 1:37.7" or structured splits, preview-then-`confirm=true` like
      `merge_activities`/`log_strength`; defaults to the most recent activity when no
      `canonical_id` given). `get_tests`/`get_test` now include pieces: every `get_tests` row
      carries a `"kind"` of `"test"` or `"piece"` (a piece's own `canonical_id` is the
      *containing* activity, not unique to the piece the way a confirmed test's canonical is),
      and `get_test` takes either `id` (a test) or `piece_id` (a piece) to dispatch to the
      right detail. MCP tool count 27 -> 28 (`docs/mcp.md`).
- [x] **Test center integration**: pieces are first-class rows in `list_tests`/`GET /api/
      tests`, a piece PB counts in `GET /api/pbs` exactly like a standalone Concept2 result,
      and `GET /api/pieces/{id}/test-detail` is a separate route from `GET /api/tests/
      {canonical_id}` (same reason as the `kind`/`piece_id` split above). Frontend: a new
      `/tests/piece/:id` page (`PieceTestDetail.tsx`), an "Add piece" entry point on both
      Workout detail and the test center (the latter gaining an activity-picker first step
      `AddPieceDialog` doesn't need when it already knows which workout), and `PbTable`
      navigating to the right detail route per entry.
- [x] Tests: 62 new backend tests (604 → 666 total — 604 is the real pre-session-17 baseline,
      597 passing + 7 then-failing; see below — `uv run pytest` all green now). Along the way,
      fixed 7 pre-existing failures in `tests/notify/test_triggers.py`/`tests/test_sync_state.py`
      that predate this session (confirmed via a disposable worktree on `1a60d8c`, unrelated to
      pieces): `_gated_notify`'s quiet-hours check uses the real wall clock
      (`triggers._now_local()`), so any test exercising a notification send was flaky by time of
      day — silently swallowed by the default 22:00–06:00 quiet-hours window on a run that
      happened to land inside it (this session's deploy did, at 22:29). Fixed by freezing
      `_now_local` to a fixed daytime timestamp in each affected test, the same pattern the
      morning_brief tests already used — a test-only fix, no production behavior changed.
      Split/total
      (`tests/analytics/test_piece.py`), the warm-up/piece/cool-down alignment fixture (mirrors
      session 12's own fixture shape), the strain-unchanged-with-and-without-the-piece
      guarantee checked directly (not just "a number exists"), the Part D.4 absorb with real
      `Stroke` rows (asserting the *parent* canonical's duration/strain survive byte-identical
      — the exact corruption a second advisor review caught), paste parsing, and the vision
      call's screen-shape normalization + server-side validation (`tests/coach/
      test_piece_vision.py`, a fake `anthropic` module like `test_nutrition_vision.py`). 17
      new Vitest tests (`pieceSplits.test.ts`, incl. the shared paste-vector fixture) + 20/7
      `test:touch` (unchanged pass/skip counts — `HrChart`'s new band/handle didn't regress any
      existing gesture). `npx tsc -b`, `npm run build` (186.3 KB gzip initial JS, budget
      250 KB), `npm run lint`, `ruff check .` all clean.
- [x] Verified live against a real dev server + Playwright MCP (`?mock=1`, 390px and 1280px,
      both themes): the full add-piece flow (paste -> review -> save) on a real on-water
      Garmin-only workout, the resulting band + drag handle on the HR chart, the Pieces card
      with Edit/Delete/Pacing-link, the test center's "piece" badge and Add-piece activity
      picker, and the piece test-detail page's pacing chart. No new console errors (the one
      pre-existing "unsupported MIME type" error is the ZXing-wasm dev-server quirk, present
      before this session's changes too).
- [x] `CLAUDE.md` (layout: new files, MCP tool count), `DESIGN.md` ("Adding a piece" note —
      the band/handle's accent-hue reuse, the handle as a sibling DOM element rather than
      inside the chart's own SVG, the one-dialog-branching-first-step shape),
      `docs/analytics.md` §25, `docs/mcp.md` updated. PLAN.md + commit.

## Two advisor reviews

**Before writing any code**, an advisor review caught five real design problems the task's
own framing didn't surface on its own — all five changed the plan before anything was built:
a naive Concept2 absorb would double-count (the duration-ratio gate that makes a PM5-only
result fail normal merging in the first place); the test center was gated on a Concept2
member everywhere, which would have made "pieces count ... like Concept2 results" structurally
impossible without first-class rows; the power-zone-label overlay would have been a silent
no-op on this real account (zero Concept2 results — session 12's finding, still true) unless
pieces themselves fed the same threshold; the photo blob belonged in its own table, not on
`Piece` itself; and iOS's numeric keyboard has no colon. See `docs/analytics.md` §25 for how
each landed in the final design.

**After the first implementation pass**, a second advisor review caught six real bugs before
any of this shipped:

- **The Concept2-absorb design (as first built) would have corrupted the containing
  session.** Reassigning a PM5-only result's `canonical_id` onto the parent meant
  `resolve_canonical`'s ordinary field priority (Concept2 first for start/duration/distance,
  preferred for HR) would overwrite a 90-minute session's own resolved fields with the
  absorbed 6-minute piece's. Fixed: the short result's own (otherwise-orphan) canonical is
  marked `absorbed_into_piece_id` + `exclude_from_totals` and left exactly where it is —
  never merged, never deleted (it may carry user overrides) — filtered out of `GET /api/
  activities` and the test-center's own-candidate detection by that persisted column (a SQL-
  level filter, not a Python post-filter, for the same pagination-correctness reason session
  12's category-filter fix exists). Caught only because the review asked for an explicit
  before/after assertion on the *parent's* own fields, not just on the piece.
- **An absorbed piece silently lost its power/rate/HR.** `_splits_from_concept2` set them to
  `None` on every row, which (via the Part D.3 overlay) made the power-zone-label refinement
  disappear the moment a piece got absorbed — the opposite of "Concept2 stroke data wins."
  Fixed by bucketing each real stroke by its own cumulative time against the split boundaries
  `actual_splits` already computed, and recomputing real per-split averages.
- **Dragging a piece's window kept the previous window's HR.** `_apply_alignment` only filled
  a row's HR when it was still `None`, so a derived value from the first auto-align survived
  every later re-align untouched. Fixed with an `hr_source` tag (`"typed"`/`"concept2"`
  protected from overwrite; `"derived"`/unset refreshed on every align) — covered by a test
  that aligns, checks the derived value, drags to a different window, and checks it changed.
- **The no-double-counting strain test checked nothing** — it only asserted `strain_trimp is
  not None`, which is true with or without a bug. Fixed to assert the exact same number
  before and after the piece is added, plus that the day's strain has exactly one component
  for that canonical.
- **The strict-tool vision schema's nullable fields were unverified against the real API
  docs** before any photo had been tried against it — fetched the live `structured-outputs`/
  `strict-tool-use` docs (not assumed from training-data familiarity) and confirmed `"type":
  ["string", "null"]` is supported, with an 11-of-16 nullable/union-field budget this schema
  stays under.
- **`update_piece`'s total-time/distance check became tautological after the first edit** —
  it recomputed `distance_m`/`duration_s` from the very splits being validated, so "do the
  splits match the total" always trivially passed on every edit after creation. Fixed by
  adding independent `distance_m`/`duration_s` params that default to the piece's *existing*
  total rather than re-deriving one from the edit itself.

## Gotchas / deviations from the literal task spec

- **Rowing's power-zone label was a real pre-existing gap this feature exposed, not
  introduced** — session 12's `_resolve_zones` computed `threshold_watts` for the rowing
  branch (used only for the muscular-AU split) but never actually built `power_zones` the way
  the cycling branch does. Moot before this session (no rowing session in this real account
  ever had per-sample power — zero Concept2 results), surfaced the moment a piece supplied the
  first real power data a rowing session here can have. Fixed alongside this feature.
- **A new piece's power data shifts the global `rowing_watts_2k` threshold**
  (`rowing_predict.py`'s predicted-2k, now fed by pieces too — see below), but only the
  canonical a piece was just added to or aligned on gets re-`resolve_canonical`'d. Every
  *other* rowing canonical's own `power_zones`/`session_label` keeps whatever threshold was
  current the last time *it* was resolved, so two rowing sessions synced on either side of
  adding a piece can end up labelled against two different thresholds until each is next
  touched (an edit, a re-sync, a re-merge). Not fixed this session — a full re-resolve of every
  rowing canonical on every piece save would be the correct fix but is real Pi-3 work to pay on
  every save for a threshold that moves rarely; flagging it rather than taking the compute hit
  unasked.
- **A confirmed piece now feeds `rowing_predict.py`'s "recent best pieces" pool**, the same
  one `GET /api/predict/2k` and the Today screen's headline predicted-2k number already draw
  from — a deliberate choice (flagged by the first advisor review, not a scope-creep
  afterthought): this real account's zero Concept2 results mean that ensemble has had nothing
  to draw from at all since session 8/12, so a typed/photo piece is the only way either the
  power-zone threshold or the predicted-2k number can ever reflect anything real on this
  account. Filtered by the containing activity's own date, not when the piece was typed in.
- **No `distance_m`/`duration_s` editing via the frontend's AddPieceDialog paste flow** — the
  typed-entry form exposes "total distance/time, if different" fields (task Part C.1's "enter
  the total and splits and it checks they match"), but the paste box itself only fills splits;
  the athlete types the independent total into those two fields afterward if the pasted splits
  alone don't already sum to it. A small extra step, not a missing feature.
- **No real PM5 photo was tried through the installed PWA** — this environment has no PM5 and
  no camera; the vision call's screen-shape handling is covered by fixture tests (fake
  `anthropic` module responses matching the task's own worked example, plus the two other real
  PM5 display shapes an advisor review flagged) and the strict-tool schema was checked against
  the live Anthropic docs, but never exercised against a real photo end to end. See "Not yet
  done" below.
- **The Pi itself was confirmed healthy this session** (`ssh opensky-pi`: `catch.service`
  active, `GET /api/health` 200 locally, `cloudflared` running) — the Catch MCP connection's
  502 at this session's start was not a sign the Pi or the deployed app is down; most likely
  transient on Cloudflare's side. No deploy had happened yet at the time of that check.

## Not yet done — needs the user

- **A real PM5 photo, through the installed PWA, with a real Anthropic key configured on that
  instance.** Everything up to "the strict-tool schema is valid and the normalization/
  validation logic is correct against every screen shape this session could reason about" is
  built and fixture-tested from here; whether the model actually transcribes a real,
  imperfectly-lit phone photo of a real PM5 screen correctly needs a real photo. Send one (or
  point at an existing one) and this can be checked directly.
- **Live-verify the Part D.4 Concept2-absorb against a real PM5 result**, once one exists —
  this account has had zero real Concept2 results across every session since session 2, so
  the absorb path (both shapes) is covered only by fixtures with synthetic `Stroke` rows.

## Session 18 checklist

The task's own prompt called itself "session 14" — sessions 14-17 (gym logger through pieces)
already occupy that slot in this file, so this continues the sequence instead, the same
resolution sessions 8/12 and 17 used for an identical collision.

Training intelligence: a per-athlete training profile, equivalent-piece performance trends,
training distribution/consistency, a fixed set of correlational insights, and a four-type
recommendation engine (training/recovery/data-quality/overload) that's dismissible, saveable,
rateable, and never claims more certainty than the data supports.

- [x] **Part A — training intelligence service**: `catch/analytics/training_intelligence.py`
      (pure) — equivalence-bucket comparison (`compare_equivalent_pieces`) over rows already
      grouped by a *confirmed* `test_type`/`piece_type` (from `catch/sync/erg_test.py::
      list_tests`, which already unifies confirmed tests and confirmed pieces — see the
      deviation note below), calling `erg_test.py`'s `project_time`/`TEST_SPECS` directly
      rather than re-deriving a trend fitter or a tolerance-based bucketer; the confidence
      ladder (`confidence_level`, capped by the *weaker* of history-days and bucket-points);
      `training_profile` (phase/trajectory/strengths/weaknesses/conflicting-signal synthesis,
      pure, over pre-gathered dicts); `training_insights` (five fixed, gated, correlationally-
      worded pattern checks). `catch/sync/training_intelligence.py` (DB-facing) — the five
      `gather_*` functions, calling `routes_analytics.trends_volume` directly for zone
      buckets rather than refactoring that live endpoint (lower-risk reuse, per an advisor
      review).
- [x] **Part B — recommendation engine**: new `Recommendation` table (`catch/core/models.py`,
      plain autoincrement PK — unlike `IllnessAck`'s date-PK insert-only shape, since the same
      `rule_key` legitimately recurs over time); `DEFAULT_SETTINGS["training_intelligence"]`
      (every threshold this session needs, one flat level deep, documented inline); four pure
      evaluators (`evaluate_training_suggestion`/`evaluate_recovery_suggestion`/
      `evaluate_data_quality_warning`/`evaluate_overload_warning`) — `training_suggestion` is
      the only one suppressed by illness/recovery/niggle/load/upcoming-event state,
      `overload_warning` is deliberately independent of all of that; one new call in
      `catch/sync/scoring.py::recompute_scores`, scoped to *today* only (never inside the
      per-historical-day loop), wrapped in its own try/except + rollback; dedup/cooldown +
      "active" staleness (`last_confirmed_on >= today - 1`) fixing a real risk an advisor
      review caught (see below); `catch/api/routes_training_intelligence.py` — the
      read/dismiss/save/rate routes.
- [x] **Part C — UI**: `/trends/intelligence` (`TrainingIntelligence.tsx`), reached via a
      `<Link>` on Trends' own header — no new Sidebar/BottomNav slot, matching the Tests/
      MuscleReadiness/Duplicates/Status no-nav-slot precedent (both nav lists are already
      documented as tight). Seven new `components/intelligence/` components + `charts/
      PieceTrendMiniChart.tsx` (a `SplitBarChart`-style static best/typical/recent chart, not
      `useChartInteraction`); confidence rendered as plain text, never a colored `BandBadge`
      (DESIGN.md's "Training intelligence" note); every section follows `TestCenter.tsx`'s
      loading/error/empty triad plus the existing `band`+`explanation` idiom for calibrating/
      insufficient-data states — no new empty-state component.
- [x] **Part D — coach + MCP**: 7 tools in `catch/coach/tools.py`'s `TOOLS` (the 6 reads
      delegate to `routes_training_intelligence`'s handlers, `rate_recommendation` is the only
      write tool, a direct mutation with no preview step); 7 hand-written `@mcp.tool()`
      wrappers + a `training_review` prompt in `catch/mcp_server/server.py` (MCP tool count
      28 → 35, prompts 2 → 3) — a parity test asserts `set(TOOLS)` equals the names
      `build_server()` registers, not just a count; `memory.py::memory_block` gained a line
      surfacing the single most severe *active* recommendation, same unprompted shape as the
      illness-level line.
- [x] Tests: 65 new backend tests (666 → 731 total — `uv run pytest` all green): 42 pure-logic
      tests (`tests/analytics/test_training_intelligence.py` — equivalence bucketing, the
      rate-vs-pace/drag-factor notes, the full suppression matrix for `training_suggestion`
      (including the post-advisor-review positive-evidence requirements — a confirmed green
      band, a real *non-null* physiological component, enough history, the yellow-band-must-
      also-suppress case), overload's sustained-not-single-day gate, the structural certainty
      guarantees — confidence capped by the weakest input, `insufficient_data` only ever from
      a data-quality warning, low/medium wording always hedged — plus a narrow banned-phrase
      backstop) and 23 sync/route/MCP tests (`tests/test_api_training_intelligence.py` —
      same-day idempotency, dismissal-doesn't-reopen-cooldown, next-day staleness,
      re-confirming-within-cooldown-refreshes-the-body (not just the date), failure isolation
      around the `recompute_scores` hook, no-recursion, the four CRUD routes (asserting the
      `recommendation_dict` response shape), MCP/coach-tool-registry parity, the exact live-bug
      scenario that used to produce a false `training:add_session`, the consistency/insights
      date-clamping fixes with exact-value assertions (not loose bounds that could pass on
      either the old or new code depending on which weekday the suite happens to run), the
      concentrated-block gate's positive and negative cases using a timezone-safe local-date
      helper, and the nutrition/daily-activity/note context fields). No new Vitest
      tests — unlike `equipment.ts`/`pieceSplits.ts`, none of this feature's math needs an
      offline-capable client-side port, so there's nothing to duplicate into TS this time.
      `npx tsc --noEmit`, `npm run build`, `npm run test`, `npm run test:touch` (20/7, unchanged
      — the Trends.tsx header change didn't regress any gesture test) all clean. Re-confirmed
      after the second advisor-review round's own fixes: `uv run pytest` still 731 passed (42 +
      23 in this feature's two files, recounted via `--collect-only`, unchanged — the round's
      fixes corrected logic inside existing tests rather than adding new ones), `ruff check`
      clean, `tsc --noEmit` clean, Vitest 53/53. Also ran `make check` (the full CI gate —
      ruff, pytest, tsc, oxlint, vitest, `vite build`, the bundle-size check, and the real
      `CI=1 npx playwright test` touch suite) end to end: all green, touch suite still 20
      passed/7 skipped. And `npm run test:gym` — the one Playwright suite that boots the real
      `catch.main` app via real uvicorn + a scratch DB — passed, exercising the real
      `recompute_scores` → `generate_recommendations` hook path end to end on a genuine offline-
      log-then-sync flow, not just a fixture-seeded unit test.
- [x] Verified live against a real dev server + Playwright MCP (`?mock=1`/`?mock=empty`, 390px
      and 1280px, **both themes genuinely toggled and confirmed via `data-theme`/computed
      background-color**, not assumed from ambient state — see the advisor-review note below
      for why that distinction mattered): the full page renders correctly end to end, including
      the expandable performance-trend mini-chart, the expandable insight evidence panels, a
      real dismiss mutation removing a recommendation from the active list, and the new
      nutrition/daily-activity/note context lines on the profile card. The empty-state pass
      showed "Not yet known"/"insufficient data" everywhere rather than any false-confident
      claim.
- [~] **Not a real-data verification — corrected after a second advisor review.** The local
      `data/catch.db` this session pulled from is a stale, session-2-era snapshot (9 tables, 34
      activities, last modified Oct 31) — it predates the matching engine, pieces, and most of
      this app's schema, and is nowhere near the live account's real size (session 12's own
      count was roughly 280 sessions). Running the gather functions against it (after `init_db`
      caught the schema up) exercised real code paths end to end and surfaced the
      `training_suggestion`/recovery-physiological-component bug this session's follow-up
      fixes it, which has standalone value, but it is **not** evidence about the current real
      account's trends/strengths/consistency numbers, and the earlier draft of this bullet was
      wrong to call it that. The real database lives on the Pi (`ssh opensky-pi`,
      `/var/lib/catch/catch.db`, confirmed live and current — 872KB, an active WAL file, last
      write today) — a WAL-consistent read-only pull from there was attempted and blocked by
      this session's own auto-mode permission classifier ("Production Reads"), which this
      session did not attempt to route around. **Needs the user**: either approve a read-only
      pull from the Pi in a future session, or treat the pure-logic + synthetic-fixture test
      suite (731 passing) as the verification this feature has actually received so far.
- [x] `CLAUDE.md` (layout: new files, MCP tool/prompt counts), `DESIGN.md` ("Training
      intelligence" note — confidence as plain text, the two static-chart reuses, no new nav
      slot), `docs/analytics.md` §26, `docs/mcp.md` updated. PLAN.md + commit.

### A deviation from the advisor-reviewed design, found during implementation

The original plan (after an advisor pass) called for extracting a `_qualifying_rows` helper
out of `rowing_predict.py` and adding a sibling `all_rower_pieces_by_bucket` for performance
trends, grouping by a new tolerance-based `bucket_key`. Reading `catch/sync/erg_test.py`
directly during implementation turned up a cleaner reuse: `list_tests` already returns every
confirmed test and confirmed piece tagged with its own `test_type`/`piece_type` — grouping by
that field *is* the equivalence bucket, with no fuzzy reclassification needed at all (that
ambiguity only exists for *un*confirmed candidates, which `detect_test_type` already handles
and this feature never touches). `rowing_predict.py` was left completely unmodified — lower
risk than the originally-planned refactor, and more consistent with this session's own
governing rule ("reuse the existing engines, never re-derive them") than the plan it replaced.

### Decisions recorded (not hidden gaps)

- **No training-plan/calendar subsystem.** "Sessions completed vs. planned" compares against
  one configurable weekly target (`target_sessions_per_week`/`target_minutes_per_week`) — a
  deliberate stand-in, documented in `docs/analytics.md` §26.
- **Single-user.** "Each athlete" means the one user this install serves; no `user_id` column
  anywhere in this schema, so nothing here carries multi-user migration risk.
- **The central risk an advisor review caught**: without a staleness check, a resolved
  overload warning would read as "active" indefinitely, even after acute:chronic dropped the
  next day, and the coach would keep asserting something the data no longer supported. Fixed
  by `last_confirmed_on` (bumped on every re-fire, even during cooldown) — "active" is
  `not dismissed and last_confirmed_on >= today - 1`, not a fixed
  expiry from `created_at`.

## Advisor review after the first implementation pass

A review run against the live smoke-test output (not just the design) caught real correctness
bugs the pure-logic test suite's synthetic contexts hadn't exercised — every fix below is
verified against new, exact-value tests and re-run against the `data/catch.db` local snapshot
(a real end-to-end run, not a verification of the current account's actual numbers — see the
corrected bullet above):

- **`training_suggestion` fired on a "green" recovery reading backed by nothing physiological,
  and contradicted `recovery_suggestion` at the yellow/red boundary.** The smoke run had
  `load.band == "insufficient_data"` and `recovery.band == "green"` from `prior_strain` alone
  (no HRV/resting-HR/sleep component that day) — `evaluate_training_suggestion` still fired a
  "nothing to hold you back" claim. Separately, at `recovery.value ==
  recovery_suggestion_recovery_max` (band `"yellow"`), only a `"red"` band suppressed the
  training suggestion, so both recommendations could fire at once. Fixed:
  `_training_suggestion_suppressed` now requires `recovery.band == "green"` *and* at least one
  physiological component (`hrv`/`resting_hr`/`sleep`) present, `load.band` in
  `{"optimal","undertraining"}`, and `history_days >= data_quality_min_history_days` — positive
  evidence, not merely the absence of a red flag. `generate_recommendations` additionally never
  evaluates `training_suggestion` in the same run as a fired `recovery_suggestion`/
  `overload_warning`.
- **Confidence was hardcoded on three of the four evaluators**, overclaiming certainty a fresh
  account couldn't support. `evaluate_recovery_suggestion`/`evaluate_overload_warning` now
  still fire at reduced confidence on thin evidence (these are caution-direction
  recommendations — understating a real concern is the actual risk, so they're never
  suppressed outright, only hedged harder); `evaluate_training_suggestion`'s confidence is
  capped by history-days alone (`_history_confidence`, the days-only half of the two-factor
  ladder — using the full `confidence_level` would have conflated "sessions this week," an
  unrelated evidence count, with data completeness).
- **Consistency/insights counted days that hadn't happened yet, and gaps that predated the
  account's own history.** `range_end` wasn't clamped to `today + 1` (the not-yet-elapsed rest
  of the current week counted as rest days and inflated the gap/charged a full week's target
  on a Monday), and `range_start` wasn't clamped to the account's earliest real data (a
  24-day-old account with an 8-week lookback reported a ~54-day gap, almost all of it before
  any data existed). Fixed with one shared `_clamped_window` helper both
  `gather_training_consistency` and `gather_training_insights` now call.
- **`concentrated_block` could fire on an ordinary 1-2-session week** — the top-2-days-share
  check is trivially 100% when there are only 1 or 2 sessions all week. Gated on `>= 3`
  sessions in that week.
- **`_missing_hr_pct` counted strength sessions**, which structurally don't carry the same
  cardio HR signal — any athlete who lifts regularly would see a false "HR data is patchy"
  warning. Excluded `sport_family == "strength"` from the lookback query.
- **A UTC-vs-local date-boundary bug in the cooldown check** — `existing.created_at.date()`
  compared a UTC date against a local-calendar `today`, the exact bug class
  `catch/sync/scoring.py`'s own `_local_day_utc_range` docstring already warns about. Fixed to
  `.astimezone().date()`.
- **The dismiss/save/rate routes returned the bare ORM row**, not `recommendation_dict` — a
  different shape than every GET on this feature returns (`evidence_json` instead of a parsed
  `evidence` list, no `active` flag). Fixed so every mutation route returns the same shape its
  sibling GET does.
- **"Saved" had no visible effect** — a saved recommendation still disappeared from the UI the
  moment it went stale (fell out of "active"), since the page only ever queried `status=
  "active"`. Added a "Saved" section that queries `status="all"` and filters client-side.
- **Phase `"taper"` could trigger on a training camp or a C-priority race** —
  `next_relevant_event` is deliberately broad (any upcoming event, for the overload-suppression
  check, where that's correct), but `_infer_phase` was reusing the same broad event
  indiscriminately. Fixed to require `priority in ("A", "B")`, matching
  `catch/coach/memory.py`'s own `next_a_race` precedent.
- **`list_recommendations` loaded and filtered every row in Python on every chat turn** (via
  `memory_block`) — fine today, unbounded as the table grows over months/years. Fixed to filter
  `dismissed`/`last_confirmed_on` at the SQL level and cap at 50 rows
  (`_MAX_RECOMMENDATIONS`), the same `_downsample`/`_MAX_ROWS`-style convention every other
  range tool in this app already follows.
- **`rate_recommendation`'s tool description overclaimed** that ratings shape future
  recommendations — nothing reads `rating` for that purpose, so the coach would have repeated a
  false claim to the athlete. Reworded to "for the athlete's own record."
- **`recommendation_valid_days` was a documented, unused setting** — superseded by
  `last_confirmed_on`-based staleness before it was ever wired up. Removed from
  `DEFAULT_SETTINGS` and every doc reference rather than left as dead configuration.
- **`target_minutes_per_week` was also unused.** Wired into `gather_training_consistency`:
  `minutes_completed`/`minutes_target` are now real fields, and the overall `pct_of_target`/
  band take the *more conservative* of the session-count and minutes percentages.
- **Nutrition/daily-activity context and coach notes were in the approved plan but missing
  from the first implementation pass.** Added `gather_training_profile`'s `nutrition`
  (`nutrition.week_summary`, `{"logged": false}` rather than zero when nothing's logged),
  `daily_activity` (today's `DailyWellness.steps`/`active_kcal`), and `recent_note` (the most
  recent `Note` in the last 7 days) — present as context on the profile, not yet factored into
  phase/strengths/confidence (see "Not yet done" below).

## A second advisor review, run against this round's own output

- **A metric name present in `recovery.components` with `value: None` still counted as real
  physiological evidence** — `recovery.py`'s own zero-spread/insufficient-baseline guards can
  leave `hrv`/`resting_hr` in the components list with a null `value` (present by name, didn't
  actually contribute to the score). Fixed with a shared `_physiological_metrics_present`
  helper requiring both the metric name *and* a non-null value, used by both
  `evaluate_training_suggestion` and `evaluate_recovery_suggestion`'s confidence.
- **Re-confirming a recommendation within its cooldown window left the stored `body`/
  `confidence`/`evidence_json` stale** — every body quotes the day's own numbers ("Today's
  recovery score is 30," "today 1.62," "you're at 1 of your 5"), and `_upsert_recommendation`
  only bumped `last_confirmed_on`, so the coach could assert an earlier day's numbers as
  "today's" for up to the whole cooldown window. Fixed to refresh `title`/`body`/`confidence`/
  `evidence_json` on every re-confirm, leaving only `id`/`created_at`/`dismissed`/`saved`/
  `rating` untouched (the row's own identity and the athlete's prior actions on it).
- **`zone_polarization`'s divisor was always effectively 1.0** — `hard_baseline` is already a
  0-1 fraction, so `max(hard_baseline, 1.0)` silently turned "≥30% *relative* drift" (what the
  insight's own title and this doc already claimed) into "≥30 absolute percentage points," a
  much harder bar that almost never fires in practice. Fixed with a small floor (0.05) instead
  of 1.0, plus a minimum-volume gate (≥30 min on both the recent and baseline side) so a
  genuinely tiny sample can't produce a noisy "drift."
- **`recovery_after_high_strain` could fire on a single real data point** — its sample-size
  gate counted total pairs, not how many actually had a non-null `after` value (a pair is
  `after: None` whenever the next day has no `DailyScore` yet). Fixed to gate on the count of
  non-null values specifically.
- **Three of this round's own new tests didn't discriminate old behavior from fixed behavior**
  — the "fresh install" test passed vacuously (`recompute_scores` returns early on a truly
  empty DB, before the hook ever runs, so `all([])` is trivially `True`); the future-days test
  used a `<=` bound the old buggy code could also satisfy on some weekdays; the concentrated-
  block test seeded an activity at literal UTC midnight, which lands on the *previous* local
  day in a negative-UTC-offset timezone and could silently test an empty week either way.
  Replaced with the exact live-bug scenario, exact-value assertions, and a timezone-safe
  `_local_dt` helper (matching `catch/sync/scoring.py`'s own local-day convention) respectively
  — plus the concentrated-block gate's missing positive case.
- **The "real data" verification claim was false** — see the corrected bullet in the Session 18
  checklist above; this session's own auto-mode permission classifier blocked a read-only pull
  from the real Pi database ("Production Reads"), which this session did not attempt to route
  around. Needs the user's explicit approval in a future session, or acceptance that this
  feature's verification so far is the pure-logic/synthetic-fixture test suite plus a run
  against a known-stale local snapshot.

## Not yet done — scope left honest rather than silently implied

- **Recent performance isn't an input to the recommendation engine.** `generate_recommendations`
  deliberately stays cheap (see its own docstring) — no equivalent-piece trend scan runs inside
  the `recompute_scores` hook, so a recommendation can't currently say "your 2k is trending
  down, consider backing off intensity." `training_profile` (the read-only profile tool/route)
  does synthesize performance trajectory from `gather_performance_trends`; the recommendation
  engine itself doesn't read it. Extending it would mean either accepting the cost inside the
  hook or caching the trend-bucket summary from the last time the profile was read — neither
  attempted here rather than built in a way that would blow the "cheap" budget this session's
  own architecture note commits to.
- **No dedicated monthly-volume view.** `get_training_distribution`/`gather_training_distribution`
  take a `weeks` param (1-52) — a caller asking for `weeks=4` effectively gets a monthly view,
  but there's no separate monthly aggregation endpoint or UI toggle. A reasonable reading of
  "weekly and monthly training volume," not a missed requirement, but recorded here rather than
  left to look like a dedicated monthly view exists.
- **`gather_performance_trends`/strengths/weaknesses have never been exercised against a real
  non-empty equivalence bucket** — only fixtures/mocks and the `data/catch.db` local snapshot
  (also empty on this front). Whether the Pi's real, current account has any confirmed
  Concept2 tests or pieces by now (session 17 shipped pieces after this snapshot was taken) is
  unknown — see the corrected real-data bullet above.
