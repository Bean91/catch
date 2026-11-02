# Peloton — findings and integration approach

**No Peloton login, no Peloton API.** This document is the entire Peloton integration spec:
detect a Peloton-pushed activity by what it looks like inside Garmin's own data (the Garmin
Personal API / FIT files Catch already syncs), nothing else.

## What was actually checked (2026-11-02, real account data)

The live account has **zero Peloton-pushed activities** as of this session — the real DB
(synced through 2026-10-31, the most recent local snapshot available; the Pi's live DB
wasn't reachable this session, see PLAN.md's session 12 notes) has 34 Garmin activities and
0 Concept2 results, same as every prior session. Two are `indoor_cycling`:

| id | external_id | start | `activityName` | `raw_json` has "peloton"? |
|---|---|---|---|---|
| 1 | 24918902966 | 2026-10-31 | "Indoor Cycling" | no |
| 15 | 24758071337 | 2026-10-17 | "Indoor Cycling" | no |

Both are generic Garmin Connect summary objects (`manufacturer: "GARMIN"`, no `averagePower`/
`averageBikeCadence` field in the summary JSON at all) — these are watch-recorded indoor
rides, not Peloton pushes. Parsing both FIT files directly (`catch/sync/fit_parse.py`,
`fitdecode`) confirms the same thing at the file level: `file_id.manufacturer` is `"garmin"`
for both, every `device_info` block is a Garmin sensor (wrist HR, barometer, sensor hub) or a
paired third-party **HR strap** (`"cardiosport"` — confirms accessories *other* than the
watch legitimately show up in `device_info`, which is why Peloton detection below uses
`file_id`, not `device_info`), and the `record` messages carry only `distance`/`heart_rate` —
**no `power`, no `cadence` field at all** on either file.

**Conclusion: this account's two real indoor-cycling activities are plain watch recordings,
not Peloton pushes.** The user may not currently have Peloton's Garmin sync enabled, or
hasn't ridden since enabling it. There is nothing to verify Peloton-specific field names
against — the mechanism below is implemented per the FIT spec and this account's own
confirmed-watch baseline, but **unverified against a real Peloton-origin file**. Revisit this
document the first time a real one shows up.

## Detection mechanism

A Peloton-pushed Garmin activity is detected by **`file_id.manufacturer`** inside the FIT
file, not by any Garmin Connect summary field (no such field was found — see the table
above) and not by `device_info` (which also lists legitimately non-Garmin *paired
accessories* on an otherwise watch-recorded ride, confirmed above with the Cardiosport strap
— using it would false-positive on anyone with a non-Garmin HR strap or power meter).
`catch/sync/fit_parse.py::parse_fit().is_peloton_like` is `True` whenever `file_id.manufacturer`
is present and isn't `"garmin"` (or missing). Stored on the Garmin `Activity` row as
`origin = "peloton"` (vs. `"watch"`), set once per sync in `catch/sync/garmin_client.py` after
the FIT file downloads.

If this ever needs to be tightened (e.g. once a real Peloton-pushed file exists and its exact
`file_id.manufacturer` string is known), change `_WATCH_MANUFACTURERS` in `fit_parse.py` —
that's the one place this check lives.

## Mapping

Both `JustRide` and class rides land in `sport_family = "cycling"`, `indoor = True` —
forced in `catch/sync/garmin_client.py`'s `_ingest_fit_samples` once FIT parsing confirms
`origin == "peloton"`, regardless of whatever typeKey Garmin assigned the import (unconfirmed
either way — see above), and the matching engine's indoor/outdoor hard block
(`catch/sync/matching.py::_to_match_input`) honors that override too, so a Peloton-pushed
ride is never blocked from merging with the watch's own `indoor_cycling` recording over a
type mismatch.

Title: `catch/sync/canonical.py`'s `auto_title` uses the activity's own `title_hint` (Garmin's
`activityName`, stored at upsert time) verbatim whenever it isn't Garmin's generic per-type
label — confirmed live that a plain watch recording's `activityName` is exactly "Indoor
Cycling" (i.e. `type.replace("_", " ").title()`), so that exact string is treated as
"no real title" and a synthesized one is used instead. A genuine Peloton class name (once a
real Peloton-pushed activity's `activityName` can be checked) would differ from that generic
label and would be used as-is — unverified, since no such activity exists yet. No separate
"instructor" field has ever been seen on this account's summary JSON at all; if Garmin
Connect's real shape for an imported Peloton ride turns out to carry one, add it here.

## Power/cadence: use whatever the watch recorded

Per the task's explicit fallback: **neither of this account's real indoor-cycling FIT files
has a `power` or `cadence` record field.** `catch/sync/canonical.py`'s field-priority
resolution for a cycling canonical with no power-capable source anywhere falls back to
HR-based load (Part B.3) and shows no power/cadence row in workout detail rather than a
misleading zero. If a Peloton-pushed activity *does* carry power/cadence once a real one
exists (Peloton bikes do have power meters — this is plausible, just unconfirmed here), the
existing field-priority config (`field_priority.power`/`.cadence`, default
`["peloton", "concept2", "garmin"]`) already prefers it over the watch with no code change
needed.

## Strain

`catch/analytics/cycling_load.py` + `catch/sync/canonical.py::_resolve_zones`: power-based
TSS-style load (`TSS = 100 * hours * (avg_power/FTP)^2`, the standard simplified formula —
this app doesn't compute a lag-filtered "normalized power", a documented approximation) when
the canonical's cycling power source has power samples, HR-based (the same per-sample
Banister integration as every other sport, Part E) otherwise — which, given the real data
above, is every cycling session in this account today. FTP comes from `settings.ftp_watts`
if set, else is estimated per-ride from that ride's own best 20-minute average power x 0.95
(`CanonicalActivity.strain_method` records `"cycling_tss_estimated_ftp"` so the UI can flag
it as an estimate — a true FTP estimate would scan *all* history for the best 20 minutes
ever, which this doesn't do, a scope cut given zero real cycling-power data exists to tune
it against). Cycling load is included in total daily load; Today shows rowing-specific load
as its own line (`rowing_load` alongside `load`) so cycling volume never silently inflates
the rowing training-load number the athlete actually cares about.
