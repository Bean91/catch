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

### 4.1 Daily activity in strain (`daily_activity_strain`), session 13

A small, capped, diminishing-returns contribution from **non-exercise** steps and active kcal
(Garmin's whole-day `steps`/`active_kcal` totals, minus whatever a logged Garmin activity that
day already contributed — `catch/sync/scoring.py`'s `_day_garmin_activity_totals`: sum of
`Activity.steps` and `max(0, calories - bmr_kcal)` for every Garmin-sourced activity starting
that local day, regardless of a canonical's `exclude_from_totals` flag, since the physical
steps happened either way; Concept2-only sessions are never subtracted — Concept2 never
contributes to Garmin's own daily wellness totals in the first place, so there's nothing of
its to double-subtract).

Both clamp at ≥0 (an activity's own steps/kcal can exceed the day's current Garmin total on an
odd sync window — e.g. the activity synced before that day's usersummary did), then:

```
steps_term = log1p(non_exercise_steps / 2000)
kcal_term  = log1p(non_exercise_active_kcal / 150)
raw        = (steps_term + kcal_term) / 2
value      = min(cap, weight * raw)
```

2000 steps / 150 kcal are illustrative "one unit of noticeable non-exercise activity" scales,
not validated physiological constants — like several other defaults in this file, flagged as a
coaching default rather than a standard. `cap` (default 1.5) and `weight` (default 1.0) are
both `Settings` keys (`daily_activity_strain_cap`/`_weight`), editable in Settings, and changing
either triggers the usual full `recompute_scores` (same as every other settings PUT).

**Added to strain's 0-21 `value` only, after the log-saturation curve — never into
`trimp_like`/`rowing_trimp_like`.** This is deliberate: `load_json`/`rowing_load_json`'s
acute:chronic EWMA is built from the `trimp_like` series (`recompute_scores`'s
`trimp_series`), so a high-step rest day must never inflate training load or look like a
training session there, only nudge the single day's displayed strain number by at most `cap`
points. `day_strain`'s result dict carries the component separately as a `daily_activity` key
(`{"value", "steps", "active_kcal", "explanation"}`), not inside `components` — every reader of
`components` (Workouts list, WorkoutDetail) assumes each entry is a per-canonical session with
a `canonical_id`, so mixing in a non-session entry there would break that assumption. The web
`StrainGauge` breakdown dialog reads `daily_activity` directly and shows it as its own row with
its share of the total `value`.

Two of `day_strain`'s three return paths needed the component added, not just the "normal"
combined-sessions path, both confirmed with tests (`tests/test_scoring.py`):
- **No activities logged that day** (previously a flat `0.0`/`"light"`): now
  `min(21, daily_activity_value)`, banded normally via `strain_band`. The task's explicit
  example — a rest day with 15k steps — stays well under 10 ("light") with the default cap.
- **Activities exist but none had enough data to score** (previously `None`/
  `"insufficient_data"` unconditionally): if the daily-activity component is also 0, that's
  unchanged; but if there's real non-exercise data, the day now reports that value/band instead
  of a flat "insufficient data" — the day's *workout* genuinely couldn't be scored, but there's
  still a real (if small) strain number to show.

Today's small, secondary "N,NNN steps · NNN active kcal" line (task Part A.4) shows the
**whole day's** Garmin totals (`GET /api/today`'s top-level `daily_activity` key), not the
non-exercise-only figure inside `strain_today.daily_activity` — those are two different
numbers by design (the breakdown's is deliberately the smaller, workout-subtracted one).

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
concurrently. Session 8/12 (see PLAN.md): it also runs `catch/sync/matching.run_matching()`
first — the cross-source matching engine (§17 below), which replaced the old
Concept2-only "sweep for an unlinked result and retry the link" step this paragraph used to
describe.

A day's activities (now canonical activities, §17) are bucketed by the **system's local
calendar date** (converting local midnight to UTC via `datetime.astimezone()`, which assumes a
naive datetime is in the system timezone) to match `date.today()`, Garmin's `calendarDate`,
and `notes.date`, all of which are local — this only lines up correctly if the Pi's system
timezone is actually set to the athlete's own.

## 17. Cross-source matching (`catch/analytics/matching.py`, `catch/sync/matching.py`,
`catch/sync/canonical.py`), session 8/12

One physical session can arrive as more than one source record — a Garmin watch recording, a
Peloton-pushed Garmin activity (same source, different external id), and/or a Concept2 PM5
result. Every `Activity` row gets its own 1:1 `CanonicalActivity` immediately at upsert time
(`catch/sync/upsert.py`); the matching engine then merges canonicals that turn out to be the
same session, so **every reader of "an activity" (Trends, Workouts, PBs, coach, MCP) reads
`CanonicalActivity` only** — nothing is ever double-counted.

**Matching rule** (`catch/analytics/matching.py::match_pair`, pure, no I/O): a pair is a
*candidate* only if (a) same broad sport family (`sport_family()` — rowing/cycling/running/
strength/other, from documented Garmin typeKey/Concept2 `type` tables), (b) start times within
3 minutes **or** time overlap ≥ 70% of the shorter record, and (c) duration ratio in
`[0.8, 1.25]`. Among candidates, a continuous score (`0.6 * time_component + 0.4 *
duration_ratio`) decides auto-merge (`score >= 0.82`) vs. "possible duplicate" flagged for
manual review (`score >= 0.45`, below the auto-merge threshold) — both numbers are code
constants, not a Settings knob (only field priority, §17.1, is user-configurable per the task).
Indoor vs. outdoor (`is_indoor()`) is a hard block on auto-merge regardless of score — a
Peloton-origin record is always forced `indoor=True` (`catch/sync/matching.py::_to_match_input`)
since its Garmin-assigned typeKey is unverified (docs/peloton.md).

`catch/sync/matching.run_matching()` (idempotent, run after every sync and as a one-off
backfill): gives every orphaned `Activity` a canonical (`ensure_canonicals`), re-resolves any
canonical a prior migration left blank (`_resolve_blank_canonicals` — see PLAN.md's session 12
bug log), scores every non-blocked candidate pair across different canonicals
(`find_candidate_pairs`, bucketed by local day ±1 for cheapness, not correctness, at this
app's single-user scale), and merges the auto-merge ones (`apply_auto_merges`, logging one
`MergeLog` row per member). A `MatchDecision` row (keyed on the natural `(source, external_id)`
pair, not row ids) records a manual "not a duplicate" or a split, so neither is ever silently
re-proposed by a later run.

Manual control (`catch/sync/matching.py`, `POST /api/activities/{merge,split,not-duplicate}`):
`manual_merge` merges two source activities' canonicals outright (preferring to keep whichever
canonical already carries user overrides, so an edit never gets silently discarded by a
merge); `split_activity` gives one member back its own canonical and writes the
re-merge-blocking `MatchDecision`; `mark_not_duplicate` writes one without merging anything.

### 17.1 Field priority (`catch/sync/canonical.py::resolve_canonical`)

Each resolved field on the canonical is picked by `Settings.field_priority[field]` (a list of
provenance labels — `"peloton"`, `"concept2"`, `"garmin"` — first match with a non-null value
wins), falling back to `["concept2", "peloton", "garmin"]` for any field without its own
configured priority (duration, distance for non-bike, calories, start). HR is a dedicated rule
(not configurable): whichever member has `hr_source_type == "chest_strap"` (or is a Concept2
result, which only ever logs HR from a paired ANT+ strap — no PM5 has a wrist sensor), else
the Garmin watch, else any member with HR at all. The title (Part C.3) prefers a source's own
non-generic `title_hint` (Garmin's `activityName`, when it isn't exactly the generic per-type
label `type.replace("_"," ").title()` — confirmed live that a plain watch recording's
`activityName` is exactly that) in `field_priority.title`'s order, else a synthesized label
(`"Erg N x Dm"` from Concept2's structured workout, `"Peloton N min Just Ride"`, `"Steady state
N'"` for a continuous Garmin row, else a generic per-`sport_family` noun). Every resolved
field's winning source is recorded in `field_sources_json` (`"source:external_id"` or
`"override"`/`"auto"` for the title), shown next to each metric in workout detail.

## 18. Peloton / cycling load (`catch/analytics/cycling_load.py`), session 8/12

See docs/peloton.md for the live-verified Peloton detection mechanism (FIT `file_id`'s own
creator, not a paired accessory's manufacturer) and its real-data findings. Cycling strain
prefers power over HR whenever the canonical's chosen power-source member has power samples:
`TSS = 100 * hours * (avg_power / FTP)^2` (the standard simplified formula — this app has no
lag-filtered "normalized power", a documented approximation), with FTP from
`Settings.ftp_watts` if set, else estimated per-ride as `best_20min_power * 0.95`
(`CanonicalActivity.strain_method` records whether FTP was estimated, so the UI can flag it).
No live cycling-power data exists in this account to tune or verify the TSS-vs-Banister
equivalence assumed by feeding TSS into the same 0-21 log-saturation strain scale as every
other sport (§4) — see docs/peloton.md.

## 19. Per-sample zones and strain (`catch/analytics/zones_samples.py`,
`catch/sync/fit_parse.py`, `catch/sync/samples.py`), session 8/12

**The problem this replaces**: §4/§6's strain and zone numbers used whole-session average HR —
a long warm-up/cool-down, or a watch left running past the end of a hard session, drags the
average down enough that a session with real time at AN/TR reads as UT2 and scores far too low.

**Samples**: `catch/sync/fit_parse.py` streams a FIT file's `record` messages (`fitdecode`, a
pure-Python/universal-wheel package — no Pi/ARM concern) into a 1 Hz grid (gaps ≤10s
forward-filled as "unchanged since the last reading"; longer gaps are real dropouts, left
`None`) for `heart_rate`/`power`/`cadence`, plus FIT `lap` messages as offset/duration pairs.
Concept2 stroke data (`catch/sync/samples.py::store_samples_from_strokes`) is resampled onto
the same 1 Hz grid by forward-filling each stroke's reading (an event stream, not a
fixed-interval one) across its own cumulative time offset, including rest between intervals.
Packed as zlib-compressed uint16 arrays (`catch/analytics/samples_codec.py`, `0xFFFF` =
missing) into one `ActivitySamples` row per *source* record — a few KB for a 90-minute
session, not thousands of SQLite rows (CLAUDE.md's Pi-memory rule).

**Zones/strain** (`zones_samples.py`, pure): `drop_dropouts` removes 0 readings and any run of
the same non-zero value held ≥30s (a real HR doesn't flatline that long — a stuck sensor
does); `smooth` is a ~5s centered moving average (skipping dropouts in its window, not
treating them as 0) to drop sensor spikes without smearing a real 10-minute hard block into
its neighbors. `time_in_zone_seconds` sums actual per-sample seconds in each zone — the direct
fix for the motivating problem. `banister_trimp_from_samples` integrates the same
`duration_minutes * HRr * 0.64 * e^(1.92*HRr)` formula §4 uses, but **per second** (1/60
minute each) instead of once over the session average: since it's convex in HRr, concentrating
the same total HR-minutes into a short intense block scores strictly higher than spreading
them evenly, by construction — no separate "intensity bonus" needed. A quality-bar fixture
(20 min warm-up/10 min at ~95% max HR/25 min cool-down, `tests/test_canonical.py`) runs this
end to end and confirms the label is AN/TR-led (never UT2) and the day's strain exceeds a
steady UT2 piece of the same average HR.

**Session label** (`session_label`): the highest zone with "meaningful" time — clearing
*either* of two configurable floors (`Settings.min_zone_minutes`, default 3; or
`min_zone_pct` of moving time, default 10%) is enough — leads the label, with the
zone holding the most total time appended for context when it differs (`"AN (10 min) +
UT2"`). HR and power (erg/bike, where it exists) are labelled independently and the
higher-intensity one wins, since HR lags a short sharp effort that power/pace already shows.

**Auto-trim** (`detect_trailing_idle`, `Settings.auto_trim_enabled`/`auto_trim_min_idle_s`,
default 120s): a trailing run of near-zero cadence/stroke-rate at the very end of the raw
(unsmoothed) recording is "likely watch left running" — excluded from the zones/strain/label
computation above and from the summary chips on `GET /api/activities/{id}/samples`, but never
from the stored samples themselves, which still return the full recording (greyed out on the
chart) by default.

**Recompute-all-history report**: see PLAN.md's session 12 real-backfill section — 352 of 418
real sessions with samples (84%) changed label under this method vs. the old average-HR one.

## 20. Body composition (`catch/sync/body_comp.py`), session 8/12

One resolved value per day per metric (weight/fat_pct/muscle_kg), across however many of
Withings/a Garmin scale/a manual entry reported one that day — **never averaged**; the metric
list mirrors `field_priority`'s pattern (`Settings.body_comp_priority[metric]`, first source
with a non-null value wins) except "manual" is always forced to sort last regardless of
configured order (a real scale reading should never lose to a manual entry). Garmin's
`/weight-service/weight/range` reports `weight` in **grams**, not kilograms as its own OpenAPI
schema claims — confirmed against two real entries (docs/garmin-endpoints.md); `muscleMass`/
`boneMass`/`bodyWater` are left unmapped since this account's real entries have them all
`null`, with nothing to confirm their unit against.
