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

### 6.1 Subjective check-in (`checkin.py`, `GET`/`POST /api/checkins`), session 15

A fifth, optional component — the morning check-in's four 1-5 sliders (soreness, stress,
mood, sleep quality), averaged into one 0-100 score by `checkin_recovery_score` (soreness
and stress are inverted — a higher value on those two sliders means *worse*, not better —
mood and sleep quality are direct). Default weight `0.15`, but **additive**, not a slice
taken out of the other four's weights: on a day with no check-in logged, this component is
simply absent from `recovery_score`'s `available` list, so the blend over HRV/RHR/sleep/
prior-strain is mathematically identical to before this feature existed (same
`sum(w*v)/sum(w)` ratio — the other four weights are untouched). When a check-in *is*
logged, its real effective share of the blend is `weight / (1 + weight)` ≈ 13% at the
default, not literally 15% — the "~15%" in the task is a target, not an exact guarantee,
and this doc says so rather than silently rounding.

**A niggle (body area + 1-3 severity) never feeds this score at all** — `checkin_badness`/
`checkin_recovery_score` both only look at the four sliders. It's purely a flag: `GET /api/
today`'s `checkin.niggle_flag` turns true once the same `niggle_area` has been logged for
`niggle_flag_min_days` (default 3) consecutive days, and the same streak is surfaced
unprompted in the coach's per-turn memory block (`catch/coach/memory.py::memory_block`) so
it can ask about it without a tool call.

### 6.2 Provider-independent inputs, session 23 (full rules in §30)

The formula above is **Catch's own** and is unchanged. It consumes four named inputs — overnight HRV, resting heart
rate, sleep duration, yesterday's strain — plus the optional check-in, through `RecoveryInputs`
(`catch/analytics/wellness_inputs.py`), and never reads a provider's own recovery score (Whoop's is stored on its
reading for reference and nothing else). Which provider supplied each input is recorded, and the recovery payload now
also carries `calibration` (nights of HRV vs the number required), `data_availability` (per input: present today?
which provider? how many baseline nights? is it in the score at all?) and `baseline_mixed_sources`.

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

## 21. Nutrition targets and under-fuelling (`catch/analytics/nutrition.py`), session 13

**Protein target**: `protein_g_per_kg × latest resolved body-comp weight` (any source —
Withings, a Garmin scale, or a manual entry; `catch.sync.body_comp.resolve_daily`'s most
recent non-null weight, never averaged). `None` when no weight is on record yet — the UI
shows a "log a weight on the Body page" prompt rather than a target computed from nothing.

**Carb target**: `carb_g_per_kg_{tier} × weight`, where `tier` comes from
`today_training_tier` — the day's logged canonical activities plus A-race proximity (the same
`next_a_race`/taper window the Today screen and coach memory already use), since this app has
no separate training-plan feature to read a *planned* load from:

| Tier | Condition | Default g/kg |
|---|---|---|
| `rest` | 0 canonical activities today | 3 |
| `moderate` | exactly 1 | 5 |
| `double_day` | 2+ | 7 |
| `pre_race` | inside an A-race's taper window *and* ≤3 days out (narrower than the 14-day taper window itself, which is lower volume, not yet peak carb need) | 8 |

**Kcal target**: either a manual figure (`NutritionTarget.manual_kcal_target`) or a trailing
7-day average of Garmin's `DailyWellness.total_kcal` over *completed* days only — today's own
still-accumulating total is excluded (at 8am it's a few hundred kcal and would set a nonsense
target). `None` with no recent Garmin data.

**Fat target**: deliberately not its own g/kg knob — it's the kcal remainder after protein
and carbs are costed at 4 kcal/g each: `(kcal_target - protein_g×4 - carb_g×4) / 9`, floored
at 0. This mirrors common sports-nutrition guidance (set protein and carbs to need, let fat
fill the rest of the energy budget) rather than adding a third independently-tunable target
that could silently conflict with `kcal_target`. `None` whenever `kcal_target` itself is
`None`.

All four targets are explicitly labelled in the UI as "starting points, adjust with a coach
or dietitian" — defaults are configurable per-field in Settings, never hard-coded assumptions
the app treats as correct for a given athlete.

**Under-fuelling flag** (`under_fuelling_flag`, used by `GET /api/today`, `GET /api/nutrition/
summary/week`, and the coach's `get_nutrition` tool): flags only when the **last 3 logged
days** (unlogged days are *never* treated as a zero-intake deficit — the task's explicit "no
streaks, no shaming" ask would be badly undercut by flagging a day the athlete simply didn't
open the app) each ran at least 25% below that day's Garmin expenditure. Needs at least 3
logged days with a real expenditure figure to say anything at all; otherwise reports "not
enough logged days yet." The explanation string is calm and factual by design ("worth a look
at fuelling, not a reason to worry alone") — there is no red/"over" state anywhere in the
nutrition UI, consistent with this.

## 22. Equipment load math, muscular load, and cardio/muscular strain split (`catch/analytics/equipment.py`, `catch/analytics/strength.py`, `catch/sync/gym.py`), session 14

**Effective load** — what the lifter actually moved, computed server-side from whatever they
entered plus the equipment's own config, never trusted as typed:

| Equipment | `load_kg` means | Effective load |
|---|---|---|
| Barbell | plates added, both sides | `load_kg + bar_weight_kg` (bar defaults to 20kg) |
| Smith machine | plates added | `load_kg + bar_weight_kg`, `bar_weight_kg` per-gym and **unset by default** (many Smith bars are counterbalanced, often 6-15kg rather than 20kg) — unset uses a flagged-estimated 10kg guess until entered once in gym setup |
| Dumbbell / kettlebell | per-hand weight | `load_kg × 2` if bilateral, else `load_kg` (unilateral exercise + a logged side) |
| Plate-loaded machine | weight on the pin/sled | `load_kg + base_weight_kg` (a station's own carriage weight, default 0) |
| Selectorized machine | the stack number shown | `load_kg × stack_kg_per_increment + base_weight_kg` — stack numbers are only ever compared on the *same* station, never across gyms, since this calibration is per-station |
| Cable | the stack number shown | `load_kg × pulley_multiplier` (1.0 for 1:1, 0.5 for 2:1, 0.25 for 4:1 — the felt-load fraction, not the ratio notation itself) |
| Bodyweight | — | the latest resolved weight (`catch/sync/body_comp.py`'s `nearest_resolved_weight_kg`) |
| Weighted | added weight | bodyweight + added |
| Assisted | assistance amount | `max(0, bodyweight - assistance)` |
| Band | a light/medium/heavy tag | a fixed approximate kg per tag (10/20/35) — always flagged `is_estimated`, since band tension isn't a measured value |

Every one of these is snapshotted onto the `StrengthSet` row at log time (`bar_weight_kg`,
`pulley_multiplier`, `bodyweight_kg_used`, ...), never re-derived later — a later change to a
station's config or the athlete's bodyweight must never silently rewrite a past session's
numbers. The plate calculator (`plates_per_side`) is a separate, purely illustrative helper —
a greedy largest-plates-first split of the barbell/smith `load_kg` across one side.

**Estimated 1RM**: Epley, `weight × (1 + reps/30)`, reps capped at 10 for the estimate (task's
explicit ask) — a 15-rep set is treated as a 10-rep set for this formula only, not extrapolated
further, since Epley's own accuracy degrades past that point.

**Muscular load (AU — arbitrary units, not 0-21)**, per working set (warm-ups contribute 0):

```
reps_to_failure      = reps + (rir, or 10-rpe, or a default of 2 if neither logged)
intensity_factor     = 1 / (1 + reps_to_failure / 30)   # reuses Epley's own reps<->%1RM shape
set_au               = reps × effective_load_kg × intensity_factor
```

Reusing Epley's curve for "how close to failure" (rather than inventing a second constant)
means a near-failure set (low `reps_to_failure`) keeps most of its AU, and a set left a long
way from failure counts for much less — the task's explicit "sets far from failure count
less." Each set's AU is distributed to its exercise's muscles: every **primary** muscle gets
full credit, every **secondary** muscle gets half credit — not divided across how many
muscles are listed, since a compound lift genuinely loads each one, not a fraction of each.

**Normalization against a 28-day baseline** (`normalize_muscle_au`, used only for the *strain*
contribution, never for the muscle-readiness view's raw numbers): each muscle's today-AU is
clamped to `[0.4×, 2×]` its own trailing-28-day daily average — a lifter who already trains a
muscle hard every week isn't penalized for their own normal heavy session, and a one-off spike
well past normal doesn't blow the day's strain out on its own. A muscle with no baseline
history yet (first-ever session) uses its raw today value — there's nothing to normalize
against, and treating that as "0× baseline" would wrongly zero out a real first session.

**Daily strain's cardio/muscular split** (`catch/sync/scoring.py`'s `day_strain`, task Part
C.2): the existing cardio half (HR/power `trimp_like`, §4's log-saturation curve) and a new
muscular half go through their **own independent log-saturation curves**, then sum as 0-21
values, with daily-activity (§4.1) added last:

```
cardio_component    = min(21, strain_log_a * ln(1 + total_trimp_like))
muscular_component  = min(21, muscular_strain_weight * muscular_strain_log_a * ln(1 + Σ normalized_muscle_au))
value                = min(21, cardio_component + muscular_component + daily_activity_value)
```

Keeping the two curves independent (rather than feeding a combined cardio+muscular number
through one curve) is what guarantees the task's explicit requirement: **a heavy lifting day
with low/no HR must still register meaningful strain** — `cardio_component` can be exactly 0
while `muscular_component` alone lands "high." `muscular_strain_log_a` (default 1.1) and
`muscular_strain_weight` (default 1.0) are both `Settings` keys, calibrated so a realistic
heavy squat day's AU total (summed across the several muscle groups a squat loads, each
getting full/half credit — see `tests/test_scoring.py`'s heavy-squat/light-pump/long-erg
comparison) lands around "high" at zero cardio trimp. `day_strain`'s result dict carries
`cardio: {value, trimp_like}` and `muscular: {value, total_normalized_au, explanation}`
alongside the existing `daily_activity` key, for the Today strain gauge's three-way split and
workout detail's per-session breakdown.

**Cardio's own small muscular share** (erg/bike, task Part C.1.2, broadened in session 15):
two tiers against threshold (the rowing erg threshold from `catch/sync/rowing_predict.py`'s
`rowing_watts_2k`, or cycling's FTP — whichever the session already resolves power zones
against) — per-sample power ≥110% of threshold ("sprint", `seconds_above ×
threshold_watts × 0.01` AU) and 55-110% of threshold ("moderate", `seconds_moderate ×
threshold_watts × 0.00025` AU — well under the sprint rate per second, since sustained steady
effort is diffuse/low-force next to a near-max sprint). The moderate tier was added because
≥110%-only meant almost no real session ever registered anything — riding steadily *at* FTP
(100%, by definition already a hard ~20-60min effort) or a hard steady erg piece at
2k-predicted watts both landed at exactly 0 AU otherwise, which read as "cardio never loads
muscle" rather than "default low." Both tiers are summed into one flat addend — deliberately
**no per-muscle breakdown** (there's no exercise/muscle data for a cardio session) and **no
28-day normalization** (the scale constants already keep it small by construction). See
`catch/sync/canonical.py`'s `_MUSCULAR_SPRINT_RATIO`/`_MUSCULAR_MODERATE_RATIO` and
`catch/analytics/strength.py`'s `cardio_muscular_au`.

**Garmin-strength merge field priority** (task Part B.2, `catch/sync/canonical.py`): for a
`sport_family == "strength"` canonical, `start`/`duration`/`calories`/HR use priority
`["garmin", "catch_strength"]` (Garmin wins when both exist) rather than the default
source-priority list — `catch_strength` still has to be last in that list, not absent, so a
Catch-only session (no watch) falls back to its own computed window instead of every field
coming back `None`. Sets themselves are never touched by field priority — they always come
from `StrengthSet` rows, which the merge leaves alone regardless of which Activity they're
attached to. The match rule itself (`catch/analytics/matching.py`'s `_match_strength_pair`) is
simple time-overlap, not the generic 3-minute-start/duration-ratio rule — a Catch session's
window is deliberately padded (first set −10min, last set +5min), which the generic rule's
duration-ratio check would often reject.

## 23. Illness early warning (`catch/analytics/illness.py`, `catch/sync/scoring.py`'s
`day_illness`), session 15

Each night, four signals are checked against their own trailing baseline (default 30-night
window, excluding today, requiring at least `illness_min_baseline_nights` prior nights or
the signal counts as unavailable rather than silently zero):

- **Resting HR** — `z = (today - mean) / max(pstdev, illness_sd_floor_rhr)`; deviates when
  `z >= illness_sd_threshold` (higher is worse).
- **HRV (ln rMSSD)** — same shape, inverted (lower is worse): deviates when `z <=
  -threshold`.
- **Nightly respiration** (`DailyWellness.sleep_respiration_avg` — the sleep-period figure,
  not the whole-day one already used elsewhere) — deviates when `z >= threshold`.
- **Check-in mood/soreness** (`checkin_badness`, §6.1) — deviates when `z >= threshold`,
  gated behind its own, smaller minimum history (`illness_min_checkin_baseline`) since this
  signal is newer than the Garmin ones.

**No skin-temperature signal exists** — checked `docs/garmin-openapi.json` directly; there is
no field for it anywhere in Garmin's Personal API (see `docs/garmin-endpoints.md`'s note).
The task's "newer watches" phrasing was conditional on the field actually existing, which it
doesn't for this account's API surface.

A per-signal **SD floor** (1.5 bpm for RHR, 0.5 breaths/min for respiration, 0.05 in
log-space for HRV) stops a real but tiny day-to-day wobble in an integer-reported metric
(Garmin reports RHR and respiration as whole numbers) from reading as a multi-SD deviation
just because the true variance happens to be small.

**Levels**: `none` (0 deviated signals), `watch` (1+), `likely` (2+ *and* deviated on the
immediately preceding night too — 2-night persistence is a hard requirement for `likely`,
not just a "boost," so a single rough night — alcohol, a late flight, anything — can never
alone read as more than `watch`). A further discount: if the athlete's acute:chronic ratio
(`illness_acr_high_threshold`, default 1.3) is already elevated and neither respiration nor
the check-in also deviated, `likely` is capped back down to `watch` — resting HR/HRV alone
during a hard training block is an expected training response, not an illness signal, and
training load is exactly the kind of thing that can otherwise look identical to the real
two-night pattern.

**Wording is fixed and non-diagnostic** — the only phrase ever used is "your body is showing
signs of strain or illness," followed by which signals deviated. Never "sick," never a named
condition. Covered by a test that asserts the string never appears.

**Storage**: the computed result is `daily_scores.illness_json`, rewritten on every
`recompute_scores` run like every other `*_json` column there. User-owned state —
dismissed/reason, a backtest right/wrong mark, `first_flagged_at` (for a future notifier) —
lives in a separate `illness_acks` table that `recompute_scores` only ever *inserts* into
(the first time a date reaches `likely`), never overwrites; `POST /api/illness/{date}/
dismiss`/`mark` are the only things allowed to change an existing row. A dismissed-with-reason
day (alcohol/travel/late_night/vaccine) is excluded from every later day's baseline window,
same as a day already flagged `likely` — otherwise either would teach the baseline that an
abnormal night was normal.

`GET /api/today`'s recommendation overrides its usual recovery-band text outright at
`likely` ("no tests, no TR/AN work"), regardless of what the recovery number itself says —
a green-looking recovery score the morning these signals deviated doesn't mean it's safe to
go hard.

`GET /api/illness/backtest` lists every historically flagged night with whatever the athlete
has marked right/wrong so far, and reports precision over *marked* nights only (never
assumed over unmarked ones).

## 24. Erg test center (`catch/analytics/erg_test.py`, `catch/sync/erg_test.py`), session 15

A "test" is not a new table — it's a `CanonicalActivity` whose overrides carry `{"tags":
[..., "test"], "test_type": "2000m"}` (the same free-form `overrides_json` dict every other
edit already uses, via the existing `PATCH /api/activities/{id}`). `GET /api/tests/
candidates` surfaces untagged Concept2 erg sessions that look like one of the eight types
(500m/1000m/2000m/5000m/6000m/30min_r20/60min/custom) — a suggestion to confirm, never
auto-applied. Distance-based types match within 2% of the standard distance; duration-based
ones within 25s of the standard duration, and `30min_r20` additionally needs an average
stroke rate at or below ~20.5 so an all-out 30-minute piece at a much higher rate doesn't
also match. "High effort" (the task's own phrase) is approximated by *matching a standard
distance/duration at all* — Concept2 has no RPE field to check directly, and not every
session has per-sample data to derive one from.

**Pacing plan** (`pacing_plan`): per-500m targets scaled to sum to exactly the goal time,
using one of three illustrative shapes (±1-1.5% off even split) — `even`, `fast_start_settle`
(faster first quarter, slower last quarter), `negative_split` (slower first half, faster
second). Not a validated prescription, same honesty as every other illustrative default in
this app. For `30min_r20`/`60min` (duration-based types with no fixed distance ahead of
time), the "goal" is framed as a target *distance to cover* in that fixed duration — the
natural way those two tests are actually planned, and it needs no special-casing in the math.
`make_pacing_plan` saves the plan onto the athlete's **next upcoming event of any type**
(`catch/sync/erg_test.py::next_relevant_event` — deliberately broader than `next_a_race`,
which hard-filters to an A-priority race only; a pacing plan is just as often for an
upcoming `2k_test` as a race) by default when called as a coach tool, off by default over
the plain API (an explicit save action in the UI).

**Pacing analysis** (`pacing_analysis`): actual per-500m splits (linearly interpolated from
the stroke stream's cumulative distance/time — strokes rarely land exactly on a 500m mark),
start/middle-1000m/sprint segment averages, the single worst split vs. the piece's own even
split, and a split-by-split comparison against a saved plan if one matches (best-effort: the
most recently generated plan whose target distance is within 1% of this test's own — a
documented simplification, since nothing ties a specific plan to a specific future test
beyond "the next event").

**Projection** (`project_time`): an ordinary least-squares line through this test type's PB
history, projected to the athlete's next A race (or 90 days out if none is set), banded at
±1 residual SD around the trend line — a prediction interval around *this* line, not a
statement about how confident the slope itself is. Refuses outright (returns `value: None`
with an explanation) below 3 points rather than fitting a line through noise; the raw inputs
are always listed alongside the number so it's checkable, not just trusted.

## 25. Pieces (`catch/analytics/piece.py`, `catch/sync/piece.py`, `catch/coach/piece_vision.py`), session 17

The task that opened this session called it "session 13" — continuing the repo's own
numbering, same resolution sessions 8/12 used for an identical collision. A piece is a
segment of a canonical activity (a 2k inside a longer steady-state row, a 30r20, etc) — a
real `Piece` table, not another `overrides_json` tag like a confirmed test, because a piece
has a real splits table, a window into the activity's own sample stream, and a possible later
link to real Concept2 stroke data: more structure than a free-form dict should carry.

**Two input methods, one review table.** Typed/pasted splits (`parse_splits_paste`, `m:ss[.t]
[rate]` tokens separated by `/` or a newline) and a PM5 photo (`piece_vision.py`, mirroring
`nutrition_vision.py`'s strict-tool-use vision call) both land on the same `splits` list and
the same `validate_splits`/`aggregate_from_splits` functions. The photo path asks the model
to transcribe the screen's own display *strings* (`"1:36.8"`), never to do time arithmetic
itself — a model mis-adding m:ss.t values would otherwise silently corrupt a number this app
then validates as if it were exact. `_normalize_splits` additionally handles two other real
PM5 display shapes a screen can show instead of cumulative-distance/per-split-time: a
per-split distance column (500, 500, 500, 500, repeated — cumulated), and a cumulative
elapsed-time column (1:36.8, 3:15.7, …, recognized as strictly increasing with its last value
close to the piece's own total — differenced into per-split durations).

**Validation never silently corrects** (task's own words) — `validate_splits` checks the
splits sum against the total time (±0.5s/row), the cumulative distance against the total
(±max(1m×n, 0.5%)), each row's rate against a 14-50spm plausible range, and each row's watts
against what its own split/distance implies via `erg_math.watts_from_pace` (tolerance
max(2W, 1%) — PM5 watts are integers and splits are tenths, so a little rounding disagreement
is expected, not a real mismatch). `create_piece`/`update_piece` return `(None, validation)`
when a check fails and the caller didn't pass `force=true` — nothing is saved until the
athlete has seen exactly which row disagreed and either fixes it or explicitly saves anyway.
`update_piece`'s `distance_m`/`duration_s` are the *independent* total the athlete entered or
the screen showed; omitting them keeps validating against the piece's existing total rather
than re-deriving one from the very splits being edited, which would make the check pass
trivially on every edit after the first (a real bug an advisor review caught).

**Alignment** (`find_best_window`, Part D.1): auto-suggests the window (of the piece's own
total time) whose average HR is highest in the containing activity's own sample stream — an
O(n) prefix-sum scan, tie-broken toward more defined samples so a window that's mostly
dropout overlapping a few real high readings never beats one backed by a full window of real
data. A manual drag (the HR chart's own band + start handle, `HrChart.tsx`'s `pieceBands`/
`onPieceDragEnd` props) re-runs the same window-application logic with an explicit start.
Per-split HR is derived from the window on every align — but never overwrites a typed/photo
HR (`hr_source: "typed"`) or one a Concept2 sync later supplied (`"concept2"`); only a row
with no athlete-supplied reading gets a `"derived"` one, refreshed on every re-align rather
than surviving stale from a previous window (another real bug an advisor review caught).

**Refining, never adding, strain** (Part D.3): `power_member_and_samples`
(`catch/sync/piece.py`, called from `canonical.py`'s `_resolve_zones` before `has_power` is
computed) overlays each aligned piece's own per-split watts onto its window in the
*zones/strain computation*, only where the real recording has no power there already — never
a flat average over the whole window, and never outside the piece's own window. This exposed
a real pre-existing gap: session 12's rowing branch computed `threshold_watts` (for the
muscular-AU split) but never actually built `power_zones` the way the cycling branch does, so
a rowing session's power-vs-HR zone label never had anything to read — moot before this
session (zero Concept2 results in this real account means no rowing session ever had
per-sample power), exposed the moment a piece supplies the first real power data a rowing
session here can have. Fixed alongside this feature, same shape as the cycling branch.
`strain_trimp` itself stays HR-Banister-based regardless of a piece's existence for rowing
(no `cycling_tss`-equivalent branch here), so the exact same strain number before and after a
piece is added is the whole no-double-counting guarantee, checked directly in
`tests/test_piece_sync.py` rather than merely asserting "a number exists."

**A confirmed piece feeds the rowing watts-2k threshold and predicted-2k ensemble**
(`rowing_predict.py::recent_rower_pieces`, via `confirmed_piece_pace_candidates`) exactly like
a real Concept2 result — this account's real history has zero Concept2 results (session 12's
finding, still true), so without this the erg power-zone threshold above has nothing to draw
from at all. Filtered by the *containing activity's* own date, not `Piece.created_at` (a
piece typed in well after the fact, reviewing an old photo, is judged by when the effort
happened). Excludes any piece Part D.4 already absorbed into a real Concept2 result, which is
already counted via the normal Concept2 path.

**Part D.4 — a later Concept2 sync wins, without corrupting the containing session.**
`absorb_concept2_piece_results` (called from `catch/sync/matching.py::run_matching`, after
the ordinary merge pass) covers two real shapes:

1. *The PM5 result is the piece itself*, synced as its own small canonical — its duration
   ratio against the much-longer parent fails `run_matching`'s `[0.8, 1.25]` candidate gate
   on its own, so it never merges there. **Its `canonical_id` is never reassigned onto the
   parent** — an earlier version of this absorb did that, and a second advisor review caught
   that it silently corrupts the parent: `resolve_canonical`'s field priority puts Concept2
   first for start/duration/distance and prefers it for HR too, so a 90-minute session's own
   resolved fields would get overwritten by the absorbed 6-minute piece's. Instead, the short
   result's own (otherwise-orphan) canonical gets `absorbed_into_piece_id` set and
   `exclude_from_totals: true` in its overrides, and is left exactly where it is — filtered
   out of `GET /api/activities` and the test-center's own-candidate detection by that
   persisted column (never deleted, since it may carry user overrides — the
   `_choose_surviving` precedent).
2. *The PM5 ran the whole session* and the piece is one of its own interval splits — the
   whole Concept2 result merged normally (same canonical as the piece already); this finds
   which `Stroke.interval_index` group matches the piece's own distance/duration signature.

Either way, `_splits_from_concept2` recomputes real per-split rate/watts/hr averages (not
just real split times) by bucketing each stroke by its own cumulative time against the split
boundaries `actual_splits` already computed — without this, an absorbed piece's splits kept
real times but lost rate/watts/hr entirely, silently dropping the Part D.3 power-zone
refinement the moment a piece got absorbed (the second advisor review's other finding). The
typed/photo original is kept in `splits_json_fallback`. `piece_pb_candidates` and
`confirmed_piece_pace_candidates` both exclude an absorbed piece (`concept2_activity_id` set)
— the real Concept2 `Activity` row is already counted via the normal path once absorbed, so
including the piece too would count the same effort twice.

**Test center integration**: `erg_test.py::list_tests` now returns pieces as first-class rows
alongside confirmed tests, each carrying `"kind": "piece"` and a `piece_id` (a piece's own
`canonical_id` is the *containing* activity, not unique to the piece the way a confirmed
test's canonical is — so `kind`/`piece_id` disambiguate which detail route a row's id
resolves through). `GET /api/pieces/{id}/test-detail` is a separate route from `GET /api/
tests/{canonical_id}` for exactly that reason. `GET /api/pbs` draws PB candidates from both
real Concept2 `Activity` rows and confirmed pieces (again excluding an absorbed piece).

## 26. Training intelligence & recommendations (`catch/analytics/training_intelligence.py`, `catch/sync/training_intelligence.py`), session 18

The task's own prompt called itself "session 14" — PLAN.md's sessions 14-17 (gym logger
through pieces) already occupy that slot, so this is recorded as the next free one, same
renumbering precedent sessions 8/12 and 17 used for an identical collision. The governing
design rule throughout: reuse the existing engines rather than re-derive them. Nothing here
invents a new trend-fitting or zone-bucketing algorithm — it orchestrates `erg_test.py`'s
`project_time`, `erg_test.py::list_tests`' already-unified confirmed-test/piece rows, and
`routes_analytics.trends_volume`'s weekly zone buckets.

**Scope limit, stated explicitly rather than left as a silent gap**: no training-plan/
calendar subsystem exists in this app (`Event` is a race/test, not a weekly plan), and this
session doesn't build one. "Sessions completed vs. planned" compares the athlete's actual
session count against one configurable weekly target
(`settings.training_intelligence.target_sessions_per_week`/`target_minutes_per_week`) — a
deliberate stand-in, not a hidden limitation. `gather_training_consistency`'s overall
`pct_of_target`/band take the *more conservative* of the session-count and minutes
percentages, so hitting one target with unusually short (or unusually few, unusually long)
sessions doesn't read as full consistency on its own. "Each athlete" means the single user
this install serves; there's no `user_id` column anywhere in this schema, so nothing here
carries any multi-user migration risk.

**Nutrition/daily-activity context and coach notes ("when available," the task's own phrase)**
are present on `training_profile`'s output (`nutrition`, `daily_activity`, `recent_note`) —
`{"logged": false}` rather than silently treated as zero when nothing's logged, matching the
confidence/data-honesty idiom everywhere else in this module. Context only, not yet factored
into phase/strengths/confidence — see PLAN.md's session 18 "Not yet done" note.

**Performance trends — equivalence bucketing reuses confirmed classifications, never
reinvents them.** `catch/sync/erg_test.py::list_tests` already returns every confirmed test
and confirmed piece tagged with its own `test_type`/`piece_type` — grouping those rows by
that field *is* the equivalence bucket; nothing here re-derives a tolerance-based
classification the way `detect_test_type` does for *un*confirmed candidates. Within a bucket,
distance-based types (500m-6000m) compare pace in s/500m (lower is better — different exact
distances within the same standard type's ±2% tolerance are already folded onto one scale by
the pace conversion); duration-based types (`30min_r20`, `60min`) compare distance covered in
that fixed duration (higher is better), since the duration itself can't vary. The trend line
itself is `erg_test.py::project_time`, called directly — same ±1-residual-SD band, same
refusal below `data_quality_min_pieces_for_trend` (default 3, matching `project_time`'s own
hard-coded minimum) points, same "inputs always listed" honesty.

**Distinguishing real improvement from a pacing/rate change** (the task's own requirement):
rather than attempting to model stroke rate out of the pace number — a level of precision
this app doesn't actually have the data to support — a materially higher average stroke rate
(> `rate_delta_material_pct`, default 5%) alongside an apparent improvement is surfaced as a
plain-English caveat ("possible pacing/rate change") rather than silently normalized away or
ignored. A drag-factor spread across a bucket's pieces (≥3 points) gets the same treatment: an
annotation, never a reason to split the bucket into a second, less-comparable one.

**Training profile**: a pure synthesis (`training_profile`) over pre-gathered dicts — today's
cached `recovery`/`load`/`illness` (the exact `daily_scores` JSON shapes `recompute_scores`
already caches, read as-is rather than recomputed), the next event, the performance-trend
buckets above, and a consistency summary. Phase (`base`/`build`/`taper`) is explicitly
labelled `"inferred"` in its own output — a load-trend/days-to-next-A-event heuristic, never
stated as a fact the app actually knows. When two signals disagree (e.g. load says
undertraining while illness says "likely"), both are named in the explanation text rather
than collapsed into one invented verdict — the task's own "avoid pretending correlation
proves causation" extends to "avoid pretending two disagreeing signals have one answer."

**Confidence ladder** (`confidence_level`): `insufficient_data` / `low` / `medium` / `high`,
driven by the *weaker* of "how many days of wellness history exist" and "how many equivalent
data points support this specific claim" — plenty of wellness history with only one or two
pieces of a given test type still caps that type's own trend confidence at `low`. Every
recommendation's wording is selected by this same tier (`_apply_hedge`): `insufficient_data`/
`low`/`medium` confidence always gets a "based on the data so far, not certain" prefix;
`high` doesn't. A narrow banned-phrase backstop (`"push through"`, `"definitely"`,
`"guaranteed"`, `"will improve"`) is checked by a test as a floor, not the actual honesty
mechanism — the structural guarantee is the confidence-tier wording and the suppression rules
below, verified directly by `tests/analytics/test_training_intelligence.py`.

**Training insights**: a fixed, enumerated set of five pattern checks (`training_insights`),
never an open-ended correlation search — weekday concentration, recovery the day after a
high-strain day (strain ≥14, `strain.py`'s own "high" band boundary) vs. the athlete's own
baseline, a recurring fast-start pacing pattern (from `pacing_analysis`, bounded to the 10
most recent pieces with inline `splits_json` — deliberately *not* re-fetching real Concept2
stroke data for confirmed tests, to keep this cheap enough to run from the recommendation
hook below), zone polarization (AT/TR/AN share drifting ≥30% from the athlete's own recent
baseline), and consistency gaps (≥10 days with no qualifying session). Each has its own
minimum-sample gate and is worded correlationally ("tends to", "has been"), never causally.

**Recommendation engine — four types, one evaluator each, a fixed firing order.**
`evaluate_data_quality_warning` / `evaluate_overload_warning` / `evaluate_recovery_suggestion`
/ `evaluate_training_suggestion`, each pure (`context`, `settings`) -> `dict | None`.
`evaluate_training_suggestion` is the only one that requires *positive* evidence, not merely
the absence of a red flag (a real bug a post-implementation advisor review caught live: a
"green" recovery reading backed only by `prior_strain`, with no HRV/resting-HR/sleep component
that day, used to be enough to fire a load-increasing suggestion) — it fires only when
`recovery.band == "green"` *and* at least one physiological component (`hrv`/`resting_hr`/
`sleep`) is present, `load.band` is `optimal`/`undertraining`, `history_days` clears
`data_quality_min_history_days`, illness is `none`, the niggle streak is below
`niggle_flag_min_days`, and no A/B event is within `overload_suppress_near_event_days` (default
5). It's also never evaluated in the same `generate_recommendations` run as a fired
`recovery_suggestion`/`overload_warning` — at `recovery.value == recovery_suggestion_
recovery_max` (band `"yellow"`), the two used to be able to fire at once, a direct
contradiction the band-level requirement above now also structurally prevents on its own.
`evaluate_overload_warning` is deliberately *independent* of all of that (it needs to fire
exactly when load is already too high, not be silenced by the same signals that would silence
a load-increasing suggestion), and requires `overload_min_consecutive_days` (default 3) of
acute:chronic ≥ `overload_acr_threshold` (default 1.5, independently tunable from
`acr_bands.caution_high`'s own UI-coloring threshold) — one noisy day never fires it.
`evaluate_recovery_suggestion`/`evaluate_overload_warning` are caution-direction
recommendations, so neither is suppressed by thin evidence the way `training_suggestion` is —
understating a plausible concern is the actual risk there — they just fire at reduced
confidence (`"low"`/`"medium"`) instead of being hedged into silence.

**Consistency/insights never count the future or the account's own pre-history.** A shared
`_clamped_window` helper bounds every lookback window to `[max(nominal_start,
earliest_real_data_date), min(nominal_end, today + 1)]` — before this fix, the not-yet-elapsed
remainder of the current week counted as rest days (and charged a full week's session target
on a Monday), and a fresh account's pre-history read as a training gap instead of the simple
absence of the app itself. `concentrated_block` additionally requires ≥3 sessions in a week
before checking its top-2-days-share threshold — with 1 or 2 sessions, the top two days trivially
*are* the whole week.

**Dedup/cooldown and staleness** (`catch/core/models.py::Recommendation`, a plain
autoincrement-PK table — unlike `IllnessAck`'s date-PK insert-only shape, the same `rule_key`
legitimately recurs over time, so dismiss/save/rate are ordinary mutations on one specific
row). Before inserting, `_upsert_recommendation` checks for an existing row with the same
`rule_key` created within its cooldown window (`recovery_suggestion_cooldown_days`, default 3,
for that type since recovery state changes daily; `recommendation_cooldown_days`, default 7,
for the other three) — if found, it bumps that row's `last_confirmed_on` to today rather than
inserting a duplicate; dismissal does **not** reset the cooldown, so a dismissed row within
the window still blocks a new one. "Active" (what `GET /api/training-intelligence/
recommendations?status=active` and `memory_block` both read) is `not dismissed and
last_confirmed_on >= today - 1` — the fix for a real risk an advisor review caught: without
this staleness check (a flat days-since-creation validity window was the first design tried
and rejected), a resolved overload warning would read as "still active" indefinitely, well
after acute:chronic dropped the very next day, and the coach would keep asserting something
the data no longer supported.

**The `recompute_scores` hook stays cheap on purpose.** `generate_recommendations` is called
once per `recompute_scores` run — scoped to *today* only, never inside that function's own
`while day <= today` loop (which legitimately recomputes every historical day on every call;
re-evaluating "should we recommend X" for years of history on every sync/settings-PUT/note-
POST would not be legitimate the same way). It assembles only today's cached `DailyScore`,
today's check-in, a bounded recent-activity count for the missing-HR check, and the next
event — never the 365-day equivalent-piece scan `gather_performance_trends` does, which stays
in that separate, only-called-when-the-tool/route-is-hit path. Wrapped in its own try/except
with a rollback, so a bug in this newer, more heuristic subsystem can never undo the core
`DailyScore` rows the same `recompute_scores` call already committed above it.

**Surfacing**: `memory_block` appends at most the single most severe *active* (per the
definition above) recommendation as one line + its body — the same unprompted-surfacing shape
the illness-level line already uses, and for the same reason: the coach should see it without
having to think to call a tool first, but it must never be a stale claim once a later
recompute has stopped confirming it.


## 27. Intervals within a piece (`catch/analytics/piece_intervals.py`, `catch/sync/piece_intervals.py`), session 19

A piece may be made of intervals (`piece_intervals` rows; `Piece.has_intervals`). Each row has
a *prescribed* side (`target_type` = distance or time) and an optional *achieved* other side.

**Validation** (`validate_intervals`, soft like `validate_splits`): no negatives; the prescribed
target must be > 0; positions are exactly 0..n-1; rate 14-50 spm; avg HR 30-230; max HR >=
avg HR; a stored split must agree with distance/time within max(1s, 3%); <= 100 intervals.

**Summary** (`summarize_intervals`): work distance/time and rest time are separate sums
(rest is never folded into work). Piece average split = sum(time)/sum(distance)*500 over rows
that have *both* values. Watts, rate and HR are weighted by work time over rows that have that
metric — missing values are skipped, not zero — so two unequal intervals never produce a mean of
means. Max HR is the max of max-HRs; calories sum. `complete_count` reports how many rows have
both distance and time.

**No double counting.** An interval piece keeps `splits_json = []` and no sample window, so
`power_member_and_samples`/zones/strain see nothing from it; the parent canonical's strain,
duration and distance are unchanged (asserted exactly). `has_intervals` excludes it from test
rows, PBs, 2k prediction, fast-start flags and the Concept2 absorb pass.

**Comparison** (`interval_signature`, `compare_equivalent_intervals`): sessions are bucketed by
prescription (`4x500m/r60`; non-uniform sets list each `work/rest` in order; the last rest is
ignored). Within a bucket: best/typical(median)/recent weighted-average split, % vs typical, and
the shared `confidence_level` ladder. No time-projection (that is for standard test distances).

**Concept2 import** (on demand): `workout.intervals[]` -> rows (`distance`, `time`/10 s,
`rest_time`/10 s, `stroke_rate`), watts/HR/rate from strokes with the same `interval_index`.
Missing intervals -> error; nothing is derived from aggregate distance/time.

## 28. GPS tracks, on-water metrics, routes and weather (`gps.py`, `routes.py`, `weather.py`), session 20

Everything GPS-derived is computed from the watch's own position fixes and **labelled as such**
(`source: "gps_derived"`); what Garmin reported is kept alongside (`"provider"`), never blended
into it. A figure that can't be computed is `null` and shown as missing — never a stand-in zero.
Thresholds live in `settings.on_water` (`catch/analytics/defaults.py`) and are illustrative
defaults checked against this account's real rowing files, not validated constants.

### 28.1 Where the track comes from

The only documented source of a route is the activity's FIT file (`docs/garmin-endpoints.md`
§GPS). `parse_fit_track` (`catch/sync/fit_parse.py`) streams `record`/`lap`/`session` messages in
one separate pass — `parse_fit` and therefore HR/zones/strain are untouched — converting FIT
semicircles to degrees (`semi * 180 / 2**31`). `gps_metadata` messages (altitude + speed at ~1 Hz,
but no timestamp or position) are ignored because they can't be aligned to a fix without guessing.
This account's `rowing_v2` files record at smart-recording intervals (median 3 s, p90 7 s); there
is no `gps_accuracy` field and no record-level altitude, so accuracy and elevation are stored only
when a device reports them (a nullable blob each).

Storage (`activity_tracks`, one row per source activity, like `activity_samples`): int32
degrees×1e7 delta-coded + zlib for lat/lon, whole-second offsets, centimetre distance, 0.01 m/s
speed — about 9–14 KB per ~800-point track. **Filtering happens at read time, never on write**: the
stored track is what the device recorded. `n_points = 0` means "parsed, no GPS" (an erg/trainer file)
so sync never re-parses it. The time origin is the file's first record, the same as
`activity_samples`, so `elapsed_s` lines up across the HR and speed charts.

### 28.2 Filtering (`filter_track`)

Every step is counted in the `filter_report` shown to the user.

1. **No fix**: missing, NaN, out-of-range, or (0, 0) coordinates are dropped.
2. **Timestamps**: strictly increasing — a duplicate timestamp keeps the first fix, a backwards one
   is dropped.
3. **Impossible jumps**: a fix implying a speed above a per-sport ceiling from the last accepted fix
   is dropped (rowing 10, running 12, walking/hiking 6, paddling 8, cycling 25, other 15 m/s). If N=3
   consecutive rejected fixes agree with *each other* it was a real relocation (GPS lost, then
   re-acquired) — a new segment starts there and the jump itself adds no distance.
4. **Gaps**: dt > max(10 × median dt, 30 s) starts a new segment; distance is **never interpolated
   across a gap** and the gap's time is nobody's moving time.
5. Positions are not smoothed. Display speed is a 3-point median of the pair speeds.

### 28.3 Metrics

- **Distance** = haversine sum (R = 6,371,008.8 m) over *every* in-segment pair. An earlier version
  skipped pairs below the moving threshold ("stationary jitter") and under-counted by a median 2.2%
  against Garmin on this account's real rows; counting all pairs matches Garmin's own distance to a
  median **+0.15%** (range −0.09% to +0.50%, 29 sessions). The device's own FIT record `distance`
  agrees with Garmin's summary exactly.
- **Moving time** = sum of dt where pair speed ≥ 0.5 m/s (a median −2.5% vs Garmin's
  `movingDuration`, i.e. a slightly different threshold). `moving_distance` is the pairs above that
  threshold, and **average speed = moving distance / moving time**.
- **Garmin's `averageSpeed` is distance / *elapsed* time** (7,731.93 m / 2,922 s = 2.646 m/s), not
  moving time. So an `avg_speed_elapsed_mps` is reported too, for a like-for-like comparison (median
  +0.3% vs Garmin). Mixing the two bases looked like a 15–20% discrepancy until this was checked.
- **Peak speed** = best *chord* speed (straight-line displacement / time) over any ≥ 10 s stretch.
  Chord, not path length: a one-fix GPS spike adds its out-and-back to the path but barely moves the
  endpoints. The remaining bias is at most (position error ÷ window), e.g. 6 m / 10 s = 0.6 m/s —
  tested. (A 3-point median of pair speeds read up to 30% over Garmin's max on real data.)
- **Pace**: s/500 m rowing, s/km running, km/h otherwise.
- **Splits** (`compute_splits`) over a configurable distance: each boundary is the instant the GPS
  cumulative distance reaches k × split_m, linearly interpolated between fixes; split time is
  elapsed wall time. A final remainder under max(1 m, 0.2% of the split) is float error, not a split;
  a real short remainder is `partial`; a split touching a gap is flagged `has_gap`.
- **Pace consistency** = population CV of full, gap-free split speeds; `null` with fewer than 4.
- **Laps**: FIT lap messages are used only when ≥ 2 exist (this account's rows have one). Each lap
  shows GPS-derived distance/speed (`cum_dist_at`, flat across gaps) next to the lap's own numbers.

### 28.4 Routes (rowing only)

A signature is 64 points resampled by GPS distance. Two tracks align only if they run in the same
direction, start and end within 150 m of each other, their lengths agree within 10%, and each covers
the other (≥ 90% of points within 50 m of the other's polyline, point-to-segment). A track whose gap
fraction exceeds 20% is never compared. Two tracks whose time windows overlap (or that are already
merged into one canonical) are one outing recorded twice, never a repeat — routes form at ingest,
before matching merges two devices' recordings, so time overlap is the merge-independent guard. Direction is recorded: an out-and-back and its reverse are
not silently merged.

A `Route` is created only when a **second** aligned session appears; a single session is never
promoted, so the Routes page doesn't fill with one-off outings. Formation is greedy and
order-dependent (the earliest session anchors). The athlete can name/tag a route, pin or unpin a
session by hand (`route_pinned` — auto-matching then leaves it alone), or save one course as a route.

Validated on this account's 29 real rows: **6 routes covering 15 sessions** (sizes 3, 3, 3, 2, 2, 2);
14 sessions form no route. Of 812 ordered pairs, 44 failed on length alone (same water, different
distance), 52 on coverage alone and 4 on direction alone — i.e. most rows are different-length
outings on the same stretch, which strict whole-course matching deliberately does not equate.
Segment-level comparison would be future work.

History (`history_stats`, reads only each session's cached `summary_json` — never a blob): best =
highest average moving speed, typical = median, recent = latest; speed distribution (quartiles +
5-bin histogram of per-session averages), HR context (mean/range over sessions that have HR),
confidence via the shared `confidence_level` ladder. **Not wind-, current- or water-corrected**, and a
session's structure (steady vs intervals vs warm-up) is included — both stated in the payload's
`caveats`. Weather differences between the best session and the rest are returned as
`observed_difference` items with a note that they are not corrections.

### 28.5 Weather matching

See `docs/weather-endpoints.md` for the provider. Matching is on UTC instants only — never
`startTimeLocal` or the host timezone. Hour semantics differ per variable: `precipitation` is a
*preceding-hour sum* (the value stamped T covers (T−1h, T]), so a 20:37–21:25 UTC session takes
23/60 of the 21:00 stamp and 25/60 of the 22:00 one; temperature, humidity, wind speed/gusts,
direction and pressure are *instantaneous* and interpolated linearly between stamps (direction along
the shortest arc, mean by unit vectors) — never across a missing stamp. A window crossing UTC midnight
fetches both days. `coverage` is the covered fraction of the window; status is `ok`, `partial` (the
*weakest* of temperature/wind/precipitation covers under half the window, or the reanalysis day is
still provisional) or `unavailable`.

### 28.6 Scope limits, stated explicitly

- Route formation is rowing-only; the map, GPS metrics and weather work for any activity with a
  position track (running, cycling).
- Weather is gridded reanalysis (≈9–25 km), not a reading at the water, and wind *direction relative
  to the course* is not computed — so nothing here says whether wind helped or hurt.
- No on-water pace is corrected for conditions. The coach is told to separate observed data from its
  own inference (`system_prompt.md`).
- Garmin's `locationName` seeds an auto route label only; it is not shown as the athlete's name.
- GPS accuracy is unavailable on this device; elevation likewise.


## 29. Calendar planning (`catch/analytics/planning.py`, `catch/sync/planning.py`), session 21

Full write-up in `docs/calendar.md`. The numeric rules, for reference:

- **Match score** (0–1.0, offered at ≥ 0.6): same day 0.4 / adjacent day 0.15; specific sport agrees 0.3
  (an unspecified session type 0.1); erg-vs-on-water agree +0.05 / disagree −0.2; duration ratio 0.75–1.33 → +0.25,
  0.5–2.0 → +0.1, else −0.1; distance within 0.8–1.25 → +0.1. Hard filters: not a rest day, ≤ 1 day apart, sport agrees.
- **Planned totals** exclude rest days; skipped sessions are counted separately and not in the minutes. Zone minutes come
  from block zones (work time only) or the session's `target_zone`.
- **Review flag**: `Δ ≥ 60 min` and `Δ% > planning.review_threshold_pct` against `max(previous planned week, trailing
  4-week completed average)`; the baseline for a future week is the 4 weeks before *this* week.
- **Projection**: `project_time` over confirmed tests (needs ≥ 3), ±1 residual SD; 2000 m also shows `predict_2k`.


## 30. Provider-independent wellness inputs (`catch/analytics/wellness_inputs.py`, `catch/sync/wellness_readings.py`), session 23

**Model.** Every provider records what it measured as `wellness_readings(date, source, signal, value, recorded_at,
fetched_at, external_id, meta_json)`. Signals: `hrv_rmssd` (ms, overnight RMSSD), `resting_hr` (bpm), `sleep_seconds`
(time asleep; stage seconds and wake time ride in `meta`), `sleep_respiration` (breaths/min, overnight), `skin_temp_c`,
`spo2`. Check-ins are not readings (they have one source, you). `resolve_days` writes the winning value into the
existing `daily_wellness` row — **the only writer of those columns** — and `field_sources_json` records the winner of
each. Everything downstream (recovery, strain, illness, the API, the MCP tools) still reads `daily_wellness` and is
unchanged. Garmin's non-signal fields (steps, kcal, stress, body battery, intensity minutes, floors, `sleep_score`,
whole-day `respiration`) stay Garmin-only and are never touched by the resolver.

**Deterministic conflict rules.**
1. *One winner per signal per day; never averaged or summed.* This is the no-double-counting guarantee.
2. *Order* is `Settings.wellness_priority[signal]`; a source not listed ranks after the listed ones, alphabetically, so
   the order is total and never depends on row order. Default: Garmin first for everything it measures (so an existing
   Garmin history scores exactly as before — checked on a copy of the real database: all 31 days resolve to identical
   values), Whoop first for skin temperature (Garmin has none), Whoop's respiration below Garmin's (its unit is
   undocumented).
3. *Implausible values are rejected before ranking* (HRV 5–300 ms, resting HR 25–120, sleep 0.5–20 h, respiration
   4–40, skin temperature 20–45 °C, SpO₂ 70–100 %), so a glitch from the preferred device falls through to the next.
4. *A missing preferred value falls through* to the next provider.
5. *Per provider, per day, one reading* (primary key). For Whoop the main sleep is the longest non-nap sleep ending on
   the wake day; naps never feed any signal.
6. *Which day*: Garmin's `calendarDate` is the wake day; Whoop's date is the local date of the sleep's `end` using that
   record's `timezone_offset`, and a recovery takes its sleep's date (see docs/whoop-endpoints.md). The same night from
   both providers therefore lands on one date.
7. *Disagreement is flagged, not averaged*: `Resolved.conflict` is true when another provider's value differs from the
   winner by more than a per-signal tolerance (display only).

**Baselines and mixed sources.** The 7-night baseline and 60-night spread are built from the *resolved* series, so one
night is one point however many providers measured it. HRV from different devices isn't directly comparable, so when
the last seven nights of an input came from more than one provider the recovery and illness payloads carry
`baseline_mixed_sources` and the UI says today's comparison is less exact. Changing `wellness_priority`
re-resolves history (`PUT /api/settings`), which can itself create such a mix.

**Calibration** is unchanged: no score until `min_hrv_nights_for_baseline` (7) nights of resolved HRV exist
(`calibration.status`, `nights`, `required`). **Respiration, temperature and SpO₂** are defined, stored and shown but
are not in the recovery formula (respiration still feeds the separate illness signal, §23).

**Migration.** At startup, idempotently, every `source = 'garmin'` `daily_wellness` row without Garmin readings gets the
readings it implies; resolving them reproduces the same numbers. Garmin's sync now records readings and resolves the
days it touched instead of writing those columns directly, and `scheduler.run_sync` rescoring follows every source's
sync.
