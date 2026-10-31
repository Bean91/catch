# Catch — build plan

Self-hosted, single-user rowing training app. Whoop-style recovery/strain from Garmin +
Withings + Concept2, with an AI coach later. Runs 24/7 on a Raspberry Pi 3 (1GB RAM, ARM)
alongside PiAware.

## Roadmap (6 sessions)

1. **Scaffold + Garmin + Withings sync** ← this session
2. Concept2 sync + rowing analytics engine
3. Design system + Today screen
4. Workout detail, trends, body comp, settings
5. AI coach chat (bring-your-own Anthropic key) + MCP server
6. Deploy to the Pi 3, PWA, backups, optional Whoop

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

## Next steps (session 2)

- Concept2 Logbook API/export integration for stroke-level data into `strokes`.
- Rowing-specific analytics: splits, pace/watts curves, training load.
