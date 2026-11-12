# WHOOP API — what we confirmed and what Catch imports

Source: developer.whoop.com (overview, OAuth, rate limiting, support/app approval, the recovery / cycle / sleep /
workout / user pages, pagination, the v1→v2 migration guide, webhooks, the API changelog to 2026-09-23 and the
OpenAPI document). Read 2026-11-12. Two caveats: the OpenAPI JSON was truncated when fetched, so the **score
object field names** below come from the per-resource pages and should be re-confirmed against the live OpenAPI
before relying on an unusual one; and **nothing here has been exercised against a real Whoop account** — the
fixtures in `tests/fixtures/whoop/` are synthetic, shaped from these docs.

## Access and approval

- Every new app starts in the **Sandbox** tier: up to **10 connected members**. Tiers go up one at a time (Build 100,
  Growth 1,000, Scale 5,000, Production unlimited); each step is a manual request, and from Build onward needs at least
  50 % of the current limit connected. Fine for a personal install; a **blocker for a public app** until approved.
- Whoop membership and a Whoop device are required to have data at all.
- Redirect URLs must be registered in the developer dashboard exactly.

## OAuth 2 (authorization code)

| | |
|---|---|
| Authorize | `https://api.prod.whoop.com/oauth/oauth2/auth` |
| Token / refresh | `https://api.prod.whoop.com/oauth/oauth2/token` |
| API base | `https://api.prod.whoop.com/developer` (v2 under `/v2`) |
| Scopes | `read:recovery`, `read:cycles`, `read:sleep`, `read:workout`, `read:profile`, `read:body_measurement`, and **`offline`** |

- `offline` is required to receive a refresh token, and is sent again on refresh.
- **Refresh tokens rotate**: using one invalidates it, the response carries the new one, and a second concurrent
  refresh fails. Catch serializes refreshes behind a lock, re-reads the stored token after taking it, and commits
  the new pair before returning (`catch/sync/whoop_client.py`). A refused refresh (400/401) raises
  `WhoopReconnectNeeded` instead of retrying.
- Access tokens last about an hour (`expires_in`); the docs state no refresh-token lifetime.
- `state`: the docs say it must be eight characters if you generate it yourself (6 random bytes → 8 URL-safe chars).
- Not documented (unconfirmed): whether the token endpoint wants credentials in the body or HTTP Basic. Catch sends
  `client_id`/`client_secret` in the form body. **If the first real connection fails at the token step, this is the
  first thing to change** (`catch whoop check` / Settings → Whoop → Test connection will say).

## Endpoints Catch uses (all v2, all GET unless noted)

| Path | Scope | Maps to |
|---|---|---|
| `/v2/activity/sleep` | `read:sleep` | `wellness_readings` sleep_seconds (+ stage seconds, wake time) and sleep_respiration |
| `/v2/recovery` | `read:recovery` | `wellness_readings` hrv_rmssd, resting_hr, spo2, skin_temp_c |
| `/v2/activity/workout` | `read:workout` | `Activity(source="whoop")` |
| `/v2/user/profile/basic`, `/v2/cycle` | `read:profile`, `read:cycles` | connection test only (existence, never contents) |
| `DELETE /v2/user/access` | — | revoke on disconnect (204) |

Collections: `limit` ≤ 25 (default 10), `start` (inclusive) / `end`, request param **`nextToken`**, response
**`records`** + **`next_token`**, newest first. The docs' pagination page contradicts itself (a "limit header", v1
paths); the OpenAPI definitions were followed.

## Fields

- **Recovery** `score` (only when `score_state == "SCORED"`): `recovery_score` (0–100), `resting_heart_rate` (unit not
  stated; bpm assumed), `hrv_rmssd_milli`, optional `spo2_percentage` and `skin_temp_celsius` (4.0+),
  `user_calibrating`. Carries `cycle_id` and `sleep_id`.
- **Sleep**: `id` (UUID), `start`, `end`, `timezone_offset`, `nap`, `score_state`, `score.stage_summary`
  (`total_light_sleep_time_milli`, `total_slow_wave_sleep_time_milli`, `total_rem_sleep_time_milli`,
  `total_awake_time_milli`, …), `score.respiratory_rate` (unit not stated).
- **Workout**: `id` (UUID), `start`, `end`, `timezone_offset`, `sport_name`, `score.{strain, average_heart_rate,
  max_heart_rate, kilojoule, distance_meter, percent_recorded, zone_durations.*_milli}`. `sport_id` and `v1_id` are
  legacy.
- **Cycle**: `strain`, `kilojoule`, average/max HR, `step_count` (added 2026-09-23).

## How Catch maps them

- **Only `SCORED` records are imported.** `PENDING_SCORE` / `UNSCORABLE` are skipped and picked up on a later sync.
- **Which day a night belongs to.** Garmin keys sleep, HRV and resting HR on `calendarDate` — the wake day. A Whoop
  sleep's date is the **local date of its `end`**, using that record's own `timezone_offset`. A recovery takes the date
  of the sleep it points to through `sleep_id`, never the cycle's `start` (the previous evening). **Naps never feed the
  sleep/HRV/resting-HR signals.** Test: `tests/test_whoop_client.py` (same night from both providers; the
  late-evening/offset cases).
- Sleep duration is light + slow-wave + REM (time asleep), matching Garmin's `sleepTimeSeconds`.
- Workout `kilojoule` → kcal (÷ 4.184). Heart rate is summary only; there is no stream, so strain and zones fall back
  to Catch's average-HR path. Whoop strain and Whoop's recovery score are **never inputs** — the recovery score is
  kept in a reading's `meta` for reference only.
- Cross-source workout matching is the existing engine; `sport_name` maps case-insensitively to a sport family
  (`catch/analytics/whoop.py`), anything unlisted is `other`.

## Not exposed (so not imported)

- **Continuous heart rate** ("not available via the WHOOP API") and any HRV time series — one `hrv_rmssd_milli` per
  recovery only.
- Webhooks exist (v2: workout/sleep/recovery `updated`/`deleted`, HMAC-signed, retried for about an hour) but not for
  cycles, strain or body measurements. Catch polls; webhooks are a possible later optimisation.
- Cycle `step_count` is not imported (it would double-count Garmin's steps).

## Limits

100 requests/minute and 10 000/day by default; 429 on excess; headers `X-RateLimit-Limit`, `-Remaining`, `-Reset`
(seconds until the closest window resets). `Retry-After` is not documented. Catch waits once (≤ 15 s) on the reset
header, otherwise leaves the rest to the next scheduled sync. A 2-hour sync is ~4 requests per run.

## Manual connection test

1. Create an app at developer.whoop.com, register `WHOOP_REDIRECT_URI`
   (`https://<your-host>/auth/whoop/callback`), set `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, `WHOOP_REDIRECT_URI`.
2. Settings → Connected sources → **Connect Whoop**, approve, land back on Settings.
3. **Test connection** (or `uv run catch whoop check`): one request per scope; prints counts only, never tokens, names
   or e-mail addresses.
4. `uv run catch sync --source whoop --days 7`, then look at Today → Recovery details for "Whoop" next to an input.
