# Garmin Connect Personal API — real endpoint inventory

Source: the OpenAPI 3.0.1 spec embedded in the swagger-docs page's JS bundle at
https://developer.garmin.com/gc-developer-program/personal/swagger-docs (the page itself
is a client-rendered SwaggerUI with no server-rendered endpoint list; the spec is inlined
as a JSON string inside the page's webpack chunk). Full spec saved at
`docs/garmin-openapi.json`. Pulled 2026-10-31. 26 real paths exist — nothing below is invented.

Base URL: `https://personal.connectapi.garmin.com` (China: `.garmin.cn`).
All listed endpoints are `GET` except the token exchange (not part of this spec, see below).
Every request needs `Authorization: Bearer <token>`.

## Token exchange (per task spec, not in this swagger doc)

```
POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token
Authorization: ApiKey <key>
```

**Confirmed against a live response (2026-10-31):** the body is **not JSON** — it's the
bearer token itself, a raw JWT string, with `Content-Type: text/plain`. The JWT's own `exp`
claim gives the real expiry; observed `exp - iat` was exactly 24 hours. Payload also carries
`scope` (e.g. `PERSONAL_API_WELLNESS_READ`), `client_id`, `garmin_guid`. No wrapper object,
no separate `expires_in` field — decode the JWT to find out when it expires.

On `401`: log `"Garmin key expired, create a new one"` — do not retry the same key.

## Activity endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/activitylist-service/activities/search/activities` | List/search. Params: `start`, `limit` (default 99), `startDate`/`endDate` (date), `activityType`, `sortBy`, `sortOrder`, plus many filter params we don't use (distance/elevation/dive filters). This is what backfill pages through. |
| GET | `/activity-service/activity/{activityId}` | Full detail for one activity: `splitSummaries`, `summaryDTO`, `metadataDTO`, etc. Large nested object. |
| GET | `/activity-service/activity/{activityId}/workouts` | Returns `[]` if the activity has no structured workout. |
| GET | `/download-service/files/activity/{activityId}` | **Returns `application/x-zip-compressed`**, not a raw FIT file. Stream to disk, then unzip to get the `.fit` (and possibly other formats Garmin bundles). `fit_path` should point at the extracted `.fit`. |
| GET | `/wellnessactivity-service/activity/summary/range/{fromDate}/{untilDate}` | Auto-detected wellness activities (walks etc. the watch infers), separate from logged activities above. Not used for rowing; noted for completeness. |

Key fields on the activity list response per item (search response, not the detail response):
`activityId`, `activityName`, `startTimeLocal`/`startTimeGMT`, `activityType` (nested
object — needs resolving to a type key, not a plain string), `duration`, `elapsedDuration`,
`movingDuration`, `distance`, `averageHR`, `maxHR`, `avgPower`, `maxPower`, `calories`.
There is no `avgPower` guarantee for rowing specifically — Garmin only populates it when the
device/activity reports power. Also present (session 13, see PLAN.md Part A): `steps` and
`bmrCalories` — used to subtract an activity's own contribution out of the day's wellness
steps/active-kcal totals so non-exercise daily-activity strain never double-counts a logged
workout (`calories` is the activity's *total* including BMR; its active portion for this
purpose is `calories - bmrCalories`). `steps` is genuinely absent (not just unmapped) on a
non-ambulatory activity like indoor cycling — confirmed against the real recorded
`activities_list.json` fixture, both of whose entries have `steps: null`.

## Health endpoints

| Method | Path | Maps to |
|---|---|---|
| GET | `/sleep-service/sleep/dailySleep?date=` | One day. `sleepTimeSeconds`, `deepSleepSeconds`, `lightSleepSeconds`, `remSleepSeconds`, `awakeSleepSeconds`, `averageSpO2Value`, `averageRespirationValue`, `avgSleepStress`, `avgHeartRate`, `sleepScores` (typed only as a bare `object` in the spec; confirmed against a live response to have a nested `overall.value` — e.g. `{"overall": {"value": 92, "qualifierKey": "EXCELLENT"}, ...}`). |
| GET | `/sleep-service/sleep/dailySleepSummariesByDate?startDate=&endDate=` | Range version of the above — use this for backfill, not the single-day one, to cut request count. |
| GET | `/hrv-service/hrv/{calendarDate}` | One day: `hrvSummary.lastNightAvg`, `hrvSummary.weeklyAvg`, `hrvSummary.status`, plus raw `hrvReadings`. Garmin does not label this "rMSSD" explicitly in the spec; `lastNightAvg` is what we map to `hrv_rmssd`, carried over as-is (likely already an rMSSD-derived ms value per Garmin's own HRV status feature, but the spec gives no formula). |
| GET | `/hrv-service/hrv/daily/{fromDate}/{toDate}` | Range version → `{ "hrvSummaries": [...], "userProfilePk": ... }`. Use for backfill. |
| GET | `/usersummary-service/usersummary/daily?calendarDate=` | Single-day version of the aggregate below. We use the range version exclusively. |
| GET | `/usersummary-service/v2/dailysummaries?startDate=&endDate=` | **This is the main per-day aggregate**, and its real shape (confirmed against a live call — the OpenAPI spec types it only loosely) is nested, not flat: `{ "data": [{ "calendarDate", "heartRate": {"minValue","maxValue","restingValue"}, "stress": {"avgLevel","maxLevel","qualifier",...}, "bodyBattery": {"minValue","maxValue","chargedValue","drainedValue","latestValue",...}, "respiration": {"avgValue","maxValue","minValue","latestValue"}, "pulseOx": {"avgValue","minValue","latestValue"}, "hydration": {...}, "movement": {"steps":{"goal","value","distanceInMeters"},"pushes":{...},"floorsAscended":{"goal","value","distanceInMeters"},"floorsDescended":{"value","distanceInMeters"}}, "calories": {"burnedResting","burnedActive","burnedTotal","consumedGoal","consumedValue","consumedRemaining"}, "intensityMinutes": {"goal","moderate","vigorous"} }] }`. This single endpoint gives us `resting_hr` (`heartRate.restingValue`), `stress` (`stress.avgLevel`), `body_battery` (`bodyBattery.latestValue` — the one single "current level" number, despite body battery otherwise being reported as charged/drained), whole-day `spo2` (`pulseOx.avgValue`), whole-day `respiration` (`respiration.avgValue`), and — new in session 13 (see PLAN.md Part A), though the fields were already present in the recorded fixture from an earlier session and simply unused until now — `steps` (`movement.steps.value`), `floors_climbed`/`floors_descended` (`movement.floorsAscended`/`floorsDescended.value`; fractional values are already floored by Garmin per the schema's own description), `active_kcal`/`total_kcal`/`bmr_kcal` (`calories.burnedActive`/`burnedTotal`/`burnedResting` — disjoint active/resting split, `burnedTotal` is their sum), and `moderate_intensity_minutes`/`vigorous_intensity_minutes` (`intensityMinutes.moderate`/`vigorous`). We don't call the separate `bodyBattery/reports/daily`, `spo2acclimation`, or `stats/steps/daily` endpoints at all — this one call replaces all of them for our purposes, which also means fewer requests per sync on the Pi. |
| GET | `/wellness-service/wellness/dailyHeartRate?date=` | `maxHeartRate`, `minHeartRate`, `restingHeartRate`, plus a raw time-series `heartRateValues` (array of `[timestamp, value]` pairs) we don't need for daily aggregates. |
| GET | `/wellness-service/wellness/bodyBattery/reports/daily?startDate=&endDate=&chunks=` | Per day: `charged`, `drained`, plus an intraday `bodyBatteryValuesArray`. **Not called** — `v2/dailysummaries.bodyBattery.latestValue` already gives us the single daily number we need; see above. |
| GET | `/wellness-service/wellness/daily/spo2acclimation/{calendarDate}` | `averageSpO2`, `lowestSpO2`, `avgSleepSpO2`. **Not called** — `v2/dailysummaries.pulseOx.avgValue` covers it. |
| GET | `/biometric-service/heartRateZones/v2?generateDefaults=` | HR zone floors, not a daily metric — not synced into `daily_wellness`. |
| GET | `/fitnessage-service/fitnessage/v2/{calendarDate}` | Fitness age — not in our schema, not synced. |
| GET | `/weight-service/weight/range/{startDate}/{endDate}` | **Now synced** (session 8/12 — see PLAN.md Part D): Garmin's own weight data (a paired Garmin Index scale, or manual entry in Garmin Connect), a `body_comp` source alongside Withings. Real shape confirmed live (2026-11-02): `{"dailyWeightSummaries": [{"summaryDate", "allWeightMetrics": [{"weight", "bmi", "bodyFat", "bodyWater", "boneMass", "muscleMass", "sourceType" ("MANUAL"\|"USER_SETTING"\|likely "INDEX_SMART_SCALE" though unobserved), "timestampGMT", ...}], "latestWeight": {...same shape...}}], "totalAverage": {...}}`. **`weight` is in GRAMS, not kilograms as the OpenAPI schema's own description claims** — confirmed against this account's two real entries (`58967.0` for a ~59kg person, `54431.0` for a ~54kg person); `catch/sync/garmin_client.py` divides by 1000. `bodyFat` (a percentage) is mapped to `fat_pct`. `muscleMass`/`boneMass`/`bodyWater` are left unmapped — this account's two real entries have all three `null`, so there's no live value to confirm whether they follow the same (undocumented) gram convention as `weight`, and guessing wrong would silently corrupt a number rather than just being absent; revisit once a real non-null value exists. |
| GET | `/userprofile-service/userprofile/settings` | Locale/unit prefs, not health data. Not synced. |
| GET | `/goal-service/goal/user/effective/weightgoal/{startDate}/{endDate}` | Weight goals, not synced. |
| GET | `/periodichealth-service/menstrualcycle/...` | Not applicable. |
| GET | `/nutrition-service/food/logs/{date}` | Not applicable (no food logging in this app). |
| GET | `/usersummary-service/stats/{steps,stress,hydration}/daily/{startDate}/{endDate}` | Per-metric range stats; redundant with `v2/dailysummaries` for steps/stress. Not called separately.

## Fields the task asked for that Garmin does not expose (or expose differently)

- Every field the task listed for `daily_wellness` turned out to have a real source once
  `v2/dailysummaries`' actual (nested) shape was confirmed — including a genuine single
  `body_battery` number and whole-day `spo2`/`respiration`, which earlier passes over the
  loosely-typed OpenAPI spec suggested didn't exist. Nothing in the schema is a stand-in for
  a missing field anymore.
- HRV is not explicitly labeled rMSSD by the API; we store whatever `lastNightAvg` is and
  flag the assumption in code comments at the point of use, not duplicated in prose.

## Backfill strategy

Use the **range endpoints** (`dailySleepSummariesByDate`, `hrv/daily`, `v2/dailysummaries`)
in date-window chunks (no documented max range — start with 30-day windows, shrink on a 400)
rather than one call per day. Activities use
`search/activities` with `start`/`limit` paging plus `startDate`/`endDate`, walking backward
until a short page comes back.
