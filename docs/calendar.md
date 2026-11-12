# Calendar, race planning and periodization (session 21)

Code: `catch/analytics/planning.py` (pure), `catch/sync/planning.py` (DB), `catch/api/routes_calendar.py`,
coach/MCP tools in `catch/coach/tools.py`, web `pages/Calendar.tsx`, `EventDetail.tsx`, `Plan.tsx`,
`components/calendar/`, `lib/dates.ts`, `lib/mockCalendar.ts`.

## The one rule: a plan is not a workout

`planned_workouts` is its own table. Nothing writes an `Activity`/`CanonicalActivity` from it, and no
completed-training reader (`trends_volume`, `gather_training_*`, `day_strain`, ATL/CTL, `/api/activities`)
imports it. Linking sets `planned_workouts.linked_canonical_id` and nothing else. Tests snapshot every one of
those readers before and after seeding plans (past, today, future, repeating) and assert byte-identical output,
and a source-text guard asserts `scoring.py`, `analytics/load.py`, `analytics/training_intelligence.py`,
`sync/training_intelligence.py` and `routes_analytics.py` never mention `PlannedWorkout`. The one place plans
reach the recommendation engine is `planned_load_context()`, which hands it pre-computed review flags as plain data.

## Data model

| Table | Notes |
| --- | --- |
| `planned_workouts` | `date` (athlete-local calendar day), optional `start_time` "HH:MM", `session_type` (erg, on_water, run, bike, strength, cross, test, rest, other), `target_zone` (UT2/UT1/AT/TR/AN), duration/distance, `structure_json` (interval blocks), `status` (`planned`/`skipped`), `linked_canonical_id` (**unique**, so a link is one-to-one), `series_id`, `event_id`, `notes`, `coach_feedback`, `declined_json`, `owner_id`. |
| `training_phases` | `kind` (general_prep, specific_prep, pre_competition, competition, recovery), dates, goals, weekly targets (minutes, sessions, strength sessions, per-zone min/max %), `coach_approved_at/by/note`, `owner_id`. Phases may not overlap. |
| `events` (extended) | gained `location`, `goals`, `notes`, `distance_m`, `owner_id` (nullable; NULL = the install's owner). `plan_json` (pacing plan), `goal_time`, `result` unchanged. |

### Status vocabulary (no shaming)

Stored: `planned | skipped`. A link is a column, not a status. Derived `display_status`:
`rest`, `linked` ("Done"), `skipped`, `not_logged` (a past, unlinked, un-skipped plan entry), `planned`.
The UI says **"Not logged"** (dashed outline, tertiary text) — never "missed", "behind" or "overdue"; a test
scans the rendered day views for those words. Every state also has a text label and a glyph, never colour alone.

## Matching a workout to a plan

`analytics/planning.py::match_score` — same local day (+0.4) or one day apart (+0.15), same sport (+0.3), erg vs
on-water agreement, duration ratio and distance similarity; below 0.6 nothing is offered. A rest day never matches,
and a specific sport must agree. `suggest_matches` assigns greedily one-to-one by score, so an AM/PM double yields
one workout per slot. Suggestions are **computed when the calendar is read, never stored, never applied**; the
athlete links ("Link them") or declines ("Not this one", remembered in `declined_json`). Both records are left
untouched either way. **Merges and splits:** `matching._merge_canonicals` is the only place a canonical is deleted; it calls
`planning.relink_after_merge`, so a plan follows the surviving canonical (if both sides were linked, the dropped side's
plan becomes unlinked — one workout, one plan). A split keeps the link on the original canonical. The link's foreign key
is `ON DELETE SET NULL` (matters on PostgreSQL, where a dangling FK would make the merge itself fail), and reads self-heal
any other dangling link to "unlinked".

## Time zones and dates

Plans and events are plain local dates. Completed workouts are bucketed by the **host's local zone**
(`start.astimezone()`), exactly as scoring, trends and distribution already do, so the calendar, the week summary
and the load numbers can't disagree about which day a workout is on. That is why there is **no `timezone`
setting**: a second zone would split the app in two. The pure helpers (`local_date`, `today_in`,
`local_day_utc_range`) take an explicit `tz` so tests cover Sydney / New York / DST / 23:30-local; the DB layer passes
the host zone. A per-user zone belongs to the multi-user (Supabase) build. SQLite hands tz-aware columns back
naive; `aware_utc()` treats naive as UTC, and a test compares a fresh row with a reloaded one.

## Recurrence

Expanded at creation: `repeat = {weekdays:[0..6], interval_weeks, until | count}` makes individual rows sharing a
`series_id` (max 26 weeks / 200 rows). Plain dates, so a DST change can't move a session. Edits and deletes take
`scope = this | this_and_following` (a date change shifts later rows by the same number of days).

## Periodization

Weekly targets come from the phase covering the week (Thursday of that week), falling back to
`training_intelligence.target_minutes_per_week / target_sessions_per_week`. `GET /api/calendar/week-summary` returns
planned totals, completed totals (the existing completed readers), the targets, a descriptive comparison (numbers
side by side — no verdict field) and review flags. Zone splits for completed training use `trends_volume`'s
`zones_json` (available for the last 52 weeks only; older/future weeks say so).

### Review flags (large planned workload changes)

`workload_change_flags`: a week is flagged when its planned minutes are more than `planning.review_threshold_pct`
(default 25) **and** at least 60 min above the larger of the previous planned week and the trailing 4-week
completed average. Drops are flagged except in recovery / pre-competition / competition phases. A flag **only asks
for review**; it never edits the plan. Wording: hedged by history confidence (`_apply_hedge`); on a
**coach-approved** phase it defers ("worth confirming with your coach") and doesn't hedge. The same function
feeds one recommendation of its own type, `plan_review` (`rule_key plan:load_change`, normal cooldown; a neutral badge in
the UI — deliberately not `overload_warning`, which says completed load is high, and ranked below overload/recovery in
the coach's memory block), which also suppresses the "room for another session" suggestion that run. No plan is ever generated automatically.
There is no athlete age in the schema, so no age-specific threshold exists; the conservative defaults apply to everyone.

### Coach approval

`coach_approved_at/by/note` are entered by the athlete. "Edited since approval" is **derived**: the phase or any
planned session inside it has `updated_at` later than `coach_approved_at`. Only plan-content edits bump
`updated_at` (date, type, duration, distance, zone, structure, title…) — linking, skipping and feedback don't.
A deleted session can't be detected after the fact.

## Race projection (`GET /api/events/{id}/projection`)

Composes existing models only: `project_time` (linear trend through confirmed tests of that distance, ±1 residual SD
band) and, for 2000 m, `predict_2k` (Paul's law). Returns the data used, an assumptions list, the range, a plain-text
uncertainty note, the gap to the goal time, or `available: false` with the reason (no distance, a non-standard
distance, fewer than 3 results). Erg only: wind, current and race-day conditions aren't modelled and the card says so.

## Ownership (single-user, with a seam)

The **new** tables (and the new service in `catch/sync/planning.py`) carry `owner_id` (constant `OWNER_ID = "owner"`); every
function there takes it and filters on it, and another owner's row is reported as **not found**. The *legacy* event readers
(`memory.recall`/`list_all`/`memory_block`/`next_a_race`, `erg_test.next_relevant_event`, `routes_tests._find_plan_for`) are not
owner-filtered — by design of the "new tables only" choice — and the multi-user build must add that. Tests cover read/update/move/delete/link/skip/decline for planned
rows, events, phases, projection, and a cross-owner `event_id`. The app is still single-user; this makes the
Supabase build's job a column and a session lookup, not an audit.

## Coach / MCP tools (47 total at session 21; 55 after session 22 — see library.md)

Reads: `get_calendar(from, to)` (≤100 days, planned and completed in separate keys), `get_upcoming_events`,
`get_event(id)` (overview + projection), `get_training_phase(date?)`. Writes: `create_planned_workout`,
`update_planned_workout`, `delete_planned_workout`, `create_event`, `update_event`, and `forget` on an `event:` ref.
**Every write previews first**: without `confirm` it runs the exact validation the real call runs and returns
`{saved: false, preview, message}`, writing nothing; only `confirm === true` saves (falsy/"true"/1 don't).
That is one shared code path (`_gate`) plus the model following the system prompt — **not hard enforcement**: an
MCP caller can pass `confirm=true` on its first call, as with `merge_activities`/`log_strength`. A stateless HMAC of
the previewed arguments would close that gap if it is ever wanted. `add_event` was removed (it wrote without
asking); old conversations still render its label.

## PostgreSQL compatibility

Queries are ORM-only (no `strftime`, `julianday`, `PRAGMA`, `INSERT OR`, `json_extract`, `rowid`, raw `text()`) —
a test scans the new modules. `_migrate_columns` now uses `sqlalchemy.inspect()` instead of `PRAGMA table_info`; new
`events` columns are nullable `TEXT`/`REAL` (no `BOOLEAN DEFAULT 0`). Tests compile every new table, its indexes and
the generated `ALTER TABLE`s against SQLAlchemy's `postgresql` dialect. **No real PostgreSQL was run** — there is no
server or driver here — so execution against Supabase is untested. `CREATE INDEX IF NOT EXISTS` in
`_migrate_columns` remains SQLite-era code the Postgres move must still revisit.

## Scheduling from the workout library (session 22)

A library template can be added to the calendar (`POST /api/library/templates/{id}/schedule`, or "Add to calendar"
on the template page). It creates ordinary planned sessions through `create_planned` and records
`planned_workouts.template_id`; the plan is a snapshot, and matching to completed workouts is unchanged. See
[library.md](library.md). The legacy `PlannedWorkout.coach_feedback` string is still there and still edited in the
planned-session sheet; the Feedback page is where authored, versioned feedback lives.
