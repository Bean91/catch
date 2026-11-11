# Concept2 Logbook API — what we actually confirmed

Source: https://log.concept2.com/developers/documentation/, pulled 2026-10-31 (fetched raw
via WebFetch, then re-verified against the raw HTML with `curl` — the garmin/withings docs in
this repo both note WebFetch losing client-rendered content on other sites, so the full page
text was grepped directly for this one too). This page is live, first-party API reference
with real request/response examples, not a reverse-engineered swagger dump.

**Live-verified (2026-10-31):** `GET /api/users/me` with `CONCEPT2_ACCESS_TOKEN` as a Bearer
token returned `200` with the real profile (`max_heart_rate: 194`, `weight: 7900` decigrams =
79.0kg). `GET /api/users/me/results` also returned `200` but **`total: 0`** — this Concept2
account has no logged results yet. So auth and the base URL are confirmed live; the actual
result/stroke JSON shapes below are **not** independently re-verified against a real result,
only against the documented examples. Revisit `_result_fields`/`_extract_strokes` in
`catch/sync/concept2_client.py` the first time a real result comes back — if the live shape
disagrees with anything below, the live response wins (same policy as the Garmin/Withings
docs in this repo).

## Base URL, auth, versioning

```
Base: https://log.concept2.com
Authorization: Bearer <token>
Accept: application/vnd.c2logbook.v1+json
```

For a personal/single-user integration, Concept2's own docs recommend skipping the OAuth2
Authorization Code dance entirely: **Edit Profile > Applications > Concept2 Logbook API
integration** on the Logbook website generates a long-lived personal access token directly.
That's what `CONCEPT2_ACCESS_TOKEN` in `.env` holds — used as-is as the bearer token, no
exchange/refresh step, unlike Garmin (JWT exchange, 24h expiry) or Withings (HMAC-signed
OAuth2, 3h access tokens). No expiry is documented for this kind of token; a `401` means it
needs regenerating on the Logbook website.

## Pagination

`GET` list endpoints return `{"data": [...], "meta": {"pagination": {"total", "count",
"per_page", "current_page", "total_pages", "links"}}}`. 1-based `page`, `number` sets page
size (default 50, max 250). We page with `number=100` until `current_page >= total_pages`.

## Results

| Method | Path | Notes |
|---|---|---|
| GET | `/api/users/{user}/results` | `{user}` is `me` for the authenticated user. Filters: `from`/`to` (`YYYY-MM-DD`), `type` (rower/skierg/bike/dynamic/slides/paddle/water/snow/rollerski/multierg), `updated_after` (`YYYY-MM-DD HH:MM:SS`, **GMT**). The documented list response example does **not** include `drag_factor`, `stroke_rate`, `heart_rate`, or `workout` (splits/intervals) — only the base fields (id, date, distance, type, time, workout_type, ...). |
| GET | `/api/users/{user}/results/{id}` | Full result. `?include=strokes,metadata` embeds the stroke array (and request metadata) in the same call — this is what we always use instead of the dedicated strokes endpoint below, since the list endpoint doesn't carry enough to skip the per-result fetch anyway. |
| GET | `/api/users/{user}/results/{id}/strokes` | Dedicated stroke endpoint; `404` with `"This workout does not have any stroke data associated with it"` if there's none. Not used directly (see above) — the `include=strokes` embed is assumed to just omit the stroke array rather than error, since it's a different response shape (embedded in `data`, not its own `{"data": [...]}`). |

### Result fields we use

`id`, `user_id`, `date`, `timezone`, `date_utc`, `distance` (meters — **work distance only**
for interval workouts, rest is separate), `type`, `time` (tenths of a second, **work time
only**), `rest_time` (tenths of a second), `workout_type` (`unknown`, `JustRow`,
`FixedDistanceSplits`, `FixedTimeSplits`, `FixedCalorie`, `FixedWattMinute`,
`FixedTimeInterval`, `FixedDistanceInterval`, `FixedCalorieInterval`,
`FixedWattMinuteInterval`, `VariableInterval`, `VariableIntervalUndefinedRest`),
`drag_factor` (int), `stroke_rate` (avg, int), `stroke_count`, `calories_total`,
`wattminutes_total` (avg watts = `wattminutes_total * 60 / time_seconds`), `heart_rate`
(`{average, min, max, ending, recovery}`), `workout` (`{splits, intervals, targets}`).

**`date` is the workout's *end* time** as stored on the monitor (explicit in the docs, under
Add Result), not the start — local time unless `date_utc` is given (then that's authoritative
and `timezone` is ignored) or `timezone` is an IANA zone name (then `date` is localized with
it). If neither is present we fall back to treating `date` as UTC — a documented guess, not
confirmed, since no live result exists yet to check it against. Activity `start` = `date` end
time minus `(time + rest_time) / 10` seconds. (Session 19: `workout.intervals[]` entries — `distance`, `time`, `rest_time` in tenths of a second, `stroke_rate`, `type` — are what the on-demand interval import maps into `piece_intervals`; verified against the synthetic `result_102_detail.json` fixture only.)

### Stroke fields (`stroke_data` / the `strokes` embed)

Each stroke: `t` (tenths of a second), `d` (**decimeters**, i.e. `d / 10` = meters), `p`
(pace, tenths of a second **per 500m** for rower/skierg, **per 1000m** for BikeErg), `spm`
(stroke rate), `hr` (heart rate; **`0` means no reading**, not a real zero HR — mapped to
`None`). Per the docs: **`t` and `d` are cumulative within the current interval and reset to
0 at the start of each new interval/split** — there's no explicit interval id per stroke, so
we detect the boundary ourselves (a drop in `t` between consecutive strokes) and track it as
`Stroke.interval_index`; `Stroke.seq` is the absolute 0-based position for charting the whole
result in order.

The pace→watts formula (`catch/analytics/erg_math.py`) is Concept2's RowErg/SkiErg physics;
BikeErg power doesn't follow it, so per-stroke `watts` (and `Activity.avg_power` when derived
from pace rather than `wattminutes_total`) are only computed when `type` is one of `rower`,
`dynamic`, `slides`, `skierg`.

## De-duplication against Garmin

A Garmin activity with `type` in `{rowing_v2, indoor_rowing}` (both confirmed live from
session 1's own Garmin sync — Garmin logs the same erg session under either key depending on
how it was started) whose `start` falls within 2 minutes of a Concept2 result's computed
start is linked via `Activity.linked_activity_id` on both rows. Concept2 stays the source of
truth for erg metrics; if it has no `heart_rate`, the Garmin row's `avg_hr`/`max_hr` are copied
onto the Concept2 row. `catch/sync/scoring.py` only scores the Concept2 side of a linked pair
to avoid double-counting one physical session in strain/load.
