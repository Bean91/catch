# Analytics — formulas and sources

Pure Python, no pandas/numpy (Pi 3, 1GB RAM shared with PiAware). Everything here lives in
`catch/analytics/` and takes plain numbers/lists in, does no I/O, and returns `{value, band,
components, explanation}` (the "scores") or a plain structured dict (zones, time-in-zone —
not a single score). `catch/sync/scoring.py` is the only place that reads the DB, builds the
inputs these functions need, and caches the output in `daily_scores`. All thresholds below
live in `catch/analytics/defaults.py` and are overridable per-field via `PUT /api/settings`
(unknown keys are rejected); `GET /api/settings` returns the merged effective settings.

## 1. Erg math (`erg_math.py`)

`watts = 2.80 / (seconds_per_meter)^3`, where `seconds_per_meter = pace_per_500m_seconds /
500`. This is Concept2's own published pace↔watts relationship for the RowErg/SkiErg (not
valid for the BikeErg, which has its own power curve — see `docs/concept2-endpoints.md`).
Hand-checked: 1:45.0/500m (105.0s) → 302.3W; 2:00.0/500m (120.0s) → 202.5W, matching the task
spec's own numbers. `pace_from_watts` inverts it. `w_per_kg(watts, weight_kg)` is a plain
division that returns `None` without a weight. `GET /api/erg/results` looks up the nearest
`body_comp` (Withings) row to each activity's start — whichever of the closest row at-or-before
and the closest row at-or-after is nearer in time — and attaches both `weight_kg` and
`w_per_kg` per row; `None` simply propagates through until Withings OAuth is completed (no
`body_comp` rows exist yet as of session 2).

## 2. 2k prediction (`predict.py`)

Paul's law: pace changes 5 seconds per 500m for every doubling of distance. For a known piece
at `(distance, pace)`, the extrapolated 2k pace is `pace - 5 * log2(distance / 2000)`. Hand
check: a 6k at 1:50.0/500m (110.0s) → `110 - 5*log2(3) = 102.08` (~1:42.1/500m), matching the
task spec. Each recent "best piece" (one per distance, picked by the caller — `/api/predict/2k`
uses the fastest Concept2 `rower` result per ~250m-rounded distance bucket, ≥1000m, last 6)
gets its own extrapolation; `value` is their mean, `range` is `[min, max]`, and `band` reflects
how many pieces agreed and how tight that range is (`high`: ≥3 pieces within 2s of each other;
`moderate`: ≥2; `low`: 1). `/api/predict/2k` restricts candidate pieces to continuous workouts
(`JustRow`/`FixedDistanceSplits`/`FixedTimeSplits`/no `workout_type`) within a configurable
`predict_lookback_days` (default 180) — interval/piece sets mix work and rest into
`Activity.duration` while `distance` stays work-only, which would corrupt the pace Paul's law
needs, and the task asks for *recent* best pieces, not all-time ones.

## 3. Training zones (`zones.py`)

5 zones (UT2/UT1/AT/TR/AN), each a lower-bound % of max HR and a separate lower-bound % of 2k
watts (power zones aren't the same percentages as HR zones, because power scales with the
cube of pace while HR scales roughly linearly with effort). **Defaults — confirm with your
coach**, source: commonly published rowing zone tables (British Rowing / Concept2 OTW-style
guidance), not anything specific to this athlete:

| Zone | % max HR | % 2k watts |
|---|---|---|
| UT2 | 60 | 55 |
| UT1 | 70 | 65 |
| AT | 80 | 75 |
| TR | 87 | 85 |
| AN | 93 | 95 |

`max_hr` is a configurable setting, seeded automatically from the Concept2 profile's
`max_heart_rate` on first Concept2 sync if not already set (live-confirmed: 194 for this
account), and never overwritten once set. `watts_2k` isn't stored — callers derive it from
`predict_2k` on demand.

## 4. Session strain (`strain.py`)

**Banister TRIMP** when HR is available: `duration_min * HRr * 0.64 * e^(b * HRr)`, where
`HRr = (avg_hr - resting_hr) / (max_hr - resting_hr)` clamped to `[0, 1]`, and `b = 1.92`
(Banister's male coefficient; exposed as a flat configurable number, not a gender field, since
this is a single-user app — `b = 1.67` is the female coefficient if that's ever wanted).
Hand check: 60 min at HRr=0.5 → `60*0.5*0.64*e^0.96 ≈ 50.14` AU.

**Session RPE fallback** when there's no HR: `RPE(0-10) * duration_minutes`, scaled by
`srpe_to_trimp_scale = 50/300` so a 60-minute RPE-5 session (`sRPE=300`) lands near the same
~50 AU as the Banister anchor above — otherwise a session missing HR would silently distort
the acute:chronic ratio relative to one that has it. The RPE comes from `notes` for that
calendar date (the schema has no per-activity RPE — if two sessions happen the same day, both
get that day's single RPE value; a known simplification).

**0-21 Whoop-style scale**: `min(21, strain_log_a * ln(1 + trimp_like))`, a log-saturation
curve (not exponential decay) so strain climbs quickly from zero but flattens out approaching
21. `strain_log_a = 2.54`, calibrated so a ~1h moderate session (`trimp_like≈50`) lands around
strain 10, and a very hard multi-hour day (`trimp_like≈250`) lands around strain 14 — not
authoritative, just a documented anchor. Bands: light (<10), moderate (<14), high (<18), all
out (≥18). Multiple sessions in a day are **not** summed in 0-21 space (that would double-count
toward "all out"); their `trimp_like` values are summed first, then the combined total goes
through the log curve once.

**Time in zone** needs per-sample HR, which only Concept2 strokes carry (`hr` field). A
Garmin-only session (no linked Concept2 result) has no sample-level HR without parsing the FIT
file — out of scope this session (new dependency) — so `time_in_zone` returns all-zero for
those; it's only meaningful for Concept2 (or Concept2-linked) rowing pieces. Computed on
demand by `GET /api/erg/{id}/strokes` (which already has the strokes loaded) rather than
cached — each stroke's HR-reading duration is `t` minus the previous stroke's `t` within the
same interval (the first stroke of an interval gets its own `t`).

## 5. Load (`load.py`)

Acute (7-day) and chronic (42-day) EWMA of each day's `trimp_like` total (not the compressed
0-21 strain — EWMA needs a linear quantity), `λ = 2/(N+1)` per Williams et al. 2017, series
zero-filled for rest days and seeded with its own first value. `form = chronic - acute`
(positive = fresher, negative = more fatigued — standard CTL-ATL framing). `acute:chronic`
ratio bands follow Gabbett 2016's "sweet spot": `<0.8` undertraining, `0.8-1.3` optimal,
`1.3-1.5` caution, `>1.5` high risk.

## 6. Recovery (`recovery.py`)

0-100%, needs **7 nights of prior HRV history** before it will show a number at all —
otherwise `band = "calibrating"`. Four components, each a 0-100 sub-score, combined by a
configurable weighted average (missing components are dropped and the rest renormalised,
rather than failing outright):

- **HRV** (`weight 0.40`): `z = (today_ln_hrv - mean(last 7 prior nights)) / pstdev(last 60
  prior nights)`, mapped to `clip(50 + 25z, 0, 100)`. Uses `ln(rMSSD)` because HRV is
  log-normally distributed — comparing raw ms values skews the baseline.
- **Resting HR** (`weight 0.25`): same z-score shape but inverted (`baseline - today`, since
  a *lower* resting HR than usual is good, not bad).
- **Sleep vs need** (`weight 0.20`): `clip(sleep_seconds / sleep_need_seconds * 100, 0, 100)`.
  `sleep_need_seconds` defaults to a flat 8h — not Whoop's dynamic sleep-debt model, a
  deliberate simplification.
- **Prior-day strain** (`weight 0.15`): `clip(100 - prior_strain_0_21 * 100/21, 0, 100)` —
  higher strain yesterday lowers today's recovery contribution.

Both baseline/spread windows explicitly **exclude today's own value** (otherwise today would
be judged partly against itself), and a spread of zero (or fewer than 2 history points) drops
that component instead of dividing by zero. Bands: green ≥67, yellow 34-66, red <34 (task
spec's own numbers, kept as the defaults).

## 7. Erg technique per piece (`technique.py`)

Each takes one piece's (or one interval's) stroke list — `catch/api/routes_analytics.py`
groups an activity's strokes by `Stroke.interval_index` before calling these:

- **Split consistency**: bins cumulative `(distance, t)` points into 500m splits (linear
  interpolation at the boundary when a stroke doesn't land exactly on one), then
  `CV = pstdev(split_times) / mean(split_times) * 100`. Bands: consistent (<3%), moderate
  (<6%), variable (≥6%) — illustrative cutoffs, not a validated standard.
- **Watts per stroke**: mean of `watts * 60 / stroke_rate` — work (joules-equivalent) done per
  stroke; higher at the same power usually means a more powerful, less rushed stroke.
- **Rate/power slope**: least-squares slope of watts vs stroke rate (W per stroke/min).
  Illustrative heuristic (bands at 8 and 4 W/spm) for "driving with the legs vs. just rating
  up," not a validated technique score.
- **Fade**: % slower average pace in the last quarter of strokes vs. the first quarter.
  Bands: held pace (≤1%), mild fade (≤3%), faded (>3%).

## 8. Workout classification (`classify.py`), session 4

`workout_category(source, type)` buckets every activity into `erg` / `on_water` / `other`
for the Workouts list filter. **Querying the live DB this session** (`SELECT type,
SUM(raw_json LIKE '%startLatitude%') FROM activities GROUP BY type`) found every real
`rowing_v2` row (29/29) carries GPS fields and every `indoor_rowing` row (2/2) carries none —
the opposite of session 2's `ROWING_TYPE_KEYS = {"rowing_v2", "indoor_rowing"}` comment, which
claimed both were indoor/erg. That comment was written when the Concept2 account had 0
results, so it was never checked against real data. Fixed: `GARMIN_ERG_TYPES =
{"indoor_rowing"}`, `GARMIN_ON_WATER_TYPES = {"rowing_v2"}`; `sync/concept2_client.py`'s
Garmin<->Concept2 link-matching now imports `GARMIN_ERG_TYPES` from here instead of defining
its own (wrong) set. Concept2's documented `type` values split the same way: `water`/`paddle`
-> on_water, `snow`/`rollerski` -> other, everything else (`rower`/`skierg`/`bike`/`dynamic`/
`slides`/`multierg`) -> erg.

## 9. Interval table and chart x-axis (`technique.interval_summary`), session 4

Per-rep average split/rate/watts/HR for the workout-detail interval table — same cumulative
`(distance, t)` points `split_consistency` already builds, just the last point (= this rep's
own total, since both reset to 0 at each interval boundary) instead of 500m bins. `GET
/api/erg/{id}/strokes` adds `drift_vs_rep1_pct` per rep (`(this_rep_split - rep1_split) /
rep1_split * 100`, positive = slower than rep 1) and `distance_cum`/`t_cum` on every raw
stroke (running offset from prior reps' totals), so a distance-based chart doesn't saw-tooth
back to zero at each rep boundary.

## 10. Weekly zone volume (`GET /api/trends/volume`), session 4

Sums `time_in_zone` per ISO week (Monday-start) across every non-duplicate activity in range.
Real per-sample HR only exists for Concept2 strokes; a session with none (every Garmin-only
activity, or a Concept2 result with no paired HR strap) instead puts its *entire* duration
into the zone for `avg_hr` — coarser, so any week that used this fallback is flagged
`"estimated": true`. Queries only `(t, hr, interval_index)` per Concept2 activity, not whole
`Stroke` rows, to stay memory-bounded.

## 11. Personal bests (`GET /api/pbs`), session 4

Best (fastest) continuous `type=="rower"` piece within a tolerance band per distance (500m/
1k/2k/5k/6k, tolerance `max(25m, 2%)`) and best (furthest) piece within ±30s of each duration
(30/60 min) — same `workout_type` continuity restriction `_predict_2k` uses, and `rower` only
so a SkiErg/BikeErg 2k never counts as a rowing PB. `null` for any bucket with no match yet.

## 12. Body weight smoothing (`body.smooth_weight`), session 4

Same-day readings averaged first (multiple Withings syncs in a day), then a trailing
7-calendar-day rolling **median** (not mean) over whatever readings actually fall in that
window — median is what keeps a single-day outlier (bad scale reading, a post-long-row
dehydration dip) from moving the smoothed line, which a mean would. Used by the Body screen's
smoothed weight line; `GET /api/trends?metric=weight` itself still returns the raw points.

## 13. Predicted-2k trend vs. the Today-screen estimate, session 4

`GET /api/trends?metric=predicted_2k` is **not** the same number as `/api/predict/2k`/Today's
`predicted_2k`: the trend is one point per qualifying piece, each extrapolated to 2000m on its
own (same Paul's-law formula, single piece); Today's headline number averages several recent
best pieces into one ensemble estimate. Documented here specifically so the two numbers next
to each other don't look like a bug.

## 14. "Garmin key expiry," session 4

`docs/garmin-openapi.json` has no key-expiry field (the only "expir" hit is an unrelated
profile-image URL's `expirationTimestamp`) — Garmin's personal-API-key program doesn't expose
how long a key is valid for via this API. `GET /api/sync/status`'s `token_expires_at` is a
*different* thing: the 24h JWT re-exchanged automatically on every sync (see
`docs/garmin-endpoints.md`), not the underlying key's own validity window. The Settings screen
shows both, separately labelled: `token_expires_at` as "token valid until" (real, API-derived,
always ~24h out), and a new user-entered `garmin_key_expires_on` setting (date, optional, with
a warning inside 14 days) for the key's real expiry, which only the user — not this API —
knows.

## 15. Endpoints

`GET /api/today`, `GET /api/trends?metric=...&from=...&to=...` (whitelisted metric names —
`daily_wellness` columns, `recovery`/`strain`/`load_acr` from cached `daily_scores`, plus
session 4's `weight`/`w_per_kg`/`predicted_2k`), `GET /api/trends/volume?weeks=...` (session
4, weekly zone bars), `GET /api/pbs` (session 4), `GET /api/erg/results`, `GET
/api/erg/{id}/strokes` (raw strokes + per-interval technique + session 4's per-rep
`interval_summary`/drift/cumulative offsets), `GET /api/predict/2k`, `GET`/`POST /api/notes`
(session 4), `GET`/`PUT /api/settings`. Workouts list/detail (`GET /api/activities[/{id}]`,
cursor-paginated, category-filterable, per-activity strain, zones) live in
`catch/api/routes_activities.py`, not this router — see §8 above for the category logic.

`GET /api/today` is the Today screen's single call (session 3): alongside `recovery`/
`strain_today`/`load`/`recommendation` it adds `sleep_last_night` (stage seconds +
`need_seconds`), `strain_target_range` (a `[lo, hi]` 0-21 band from the new
`strain_targets` setting, keyed by today's recovery band — illustrative coaching defaults,
not validated, same caveat as the zone table), `hrv`/`resting_hr` (today's value, a 14-day
`sparkline_14d` from `daily_wellness`, and a `baseline_band` — reusing the `baseline_7d*`/
`spread_60d` already computed by `recovery_score` rather than re-deriving it, exponentiated
back out of ln-space for HRV), `latest_erg` (most recent Concept2 activity, `raw_json`/
`intervals_json` stripped, with `weight_kg`/`w_per_kg` same as `/api/erg/results`), and
`predicted_2k` (same logic `/api/predict/2k` uses, factored into `_predict_2k()` so both
routes share it).

## 16. Caching

`catch/sync/scoring.recompute_scores()` runs after every sync (any source), every
`PUT /api/settings`, and (session 4) every `POST /api/notes` — since RPE feeds the no-HR
strain fallback — and recomputes **every** day from the earliest known
`daily_wellness`/`activity` date through today into `daily_scores` — simpler and safer than an
incremental path (a settings change or backfilled day would otherwise leave stale cached
numbers), and cheap at single-user scale (plain-Python arithmetic over a few thousand days at
most). Guarded by a module-level lock so two syncs finishing close together don't recompute
concurrently. It also sweeps for any Concept2 result that's still unlinked to a Garmin
activity and retries the link — linking is also attempted at Concept2 insert time, but the
scheduler runs sources in whatever order (with jitter), so if Garmin hasn't synced that
session yet when Concept2 does, the first attempt finds no match and would otherwise double-
count the session in strain/load forever (Concept2's `updated_after` cursor has already moved
past it, so it's never re-listed).

A day's activities are bucketed by the **system's local calendar date** (converting local
midnight to UTC via `datetime.astimezone()`, which assumes a naive datetime is in the system
timezone) to match `date.today()`, Garmin's `calendarDate`, and `notes.date`, all of which are
local — this only lines up correctly if the Pi's system timezone is actually set to the
athlete's own.
