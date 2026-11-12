# Workout library, technique notes and coach feedback (session 22)

The brief called itself "session 17" and cited an older history; this repo was at session 21, so it is recorded as
**session 22** (same handling as session 21's numbering note).

## What was added

| Thing | Table | Service | Routes |
|---|---|---|---|
| Reusable workout templates | `workout_templates` | `catch/sync/workout_library.py` (+ pure `catch/analytics/workout_library.py`) | `/api/library/templates…` |
| Technique notes | `technique_notes` | `catch/sync/coaching_notes.py` | `/api/technique-notes…` |
| Coach feedback + edit history | `coach_feedback`, `coach_feedback_revisions` | `catch/sync/coaching_notes.py` | `/api/coach-feedback…` |
| Who is calling | `api_tokens.role/display_name` | `catch/core/principal.py` | — |

`Note` (the day note + RPE that feeds strain) and `analytics/technique.py` (stroke-data erg metrics) already existed
under those names and are untouched; the new things are deliberately named differently.

## Workout templates

A template is a *definition*, never a workout: no Activity/CanonicalActivity row is ever created from it, and a
template can't change a completed total (tested with the same snapshot the calendar uses).

`structure` = `{warmup, blocks[], cooldown, strength_items[]}`. A block is
`{reps, work_s | work_m, rest_s?, zone?, rate_min?, rate_max?, split_s | watts?, note?}` — seconds and metres, rest in
seconds. Workout types: `erg_intervals`, `steady_state`, `rate_ladder`, `distance_piece`, `time_piece`, `strength`,
`on_water`, `custom`; each has shape rules (a steady-state session is one block with no rest; a ladder needs ≥2 steps,
each with a rate target; a strength template lists exercises that exist in the library; …). Validation returns
`{ok, issues:[{path, message}]}` and never corrects a value.

**Arithmetic** (`summarize_template`): rest follows every rep *except the last rep of the last block* ("4 × 500m r1:00"
has three rests). A **duration is only reported when it can be known**: a distance block has none unless the template
carries a split or watts target, and then `duration_basis` is `estimated`. A distance-only template schedules without a
duration; nothing is invented. Zone minutes count work time only, matching the calendar's planner, and a test asserts
the week summary equals `summarize_template` for every seeded example.

(This deliberately does not reuse `piece_intervals.expand_repeat`, which drops the rest after the last rep of *every*
block and would erase the rest between ladder steps; it reuses that module's limits and its signature convention.)

**Add to calendar** copies the template into a `PlannedWorkout` through `planning.create_planned` (so a repeat series,
validation and the review flags all apply) and stamps `planned_workouts.template_id` for provenance. The plan is a
**snapshot**: editing or archiving the template later doesn't change sessions already planned. Matching to the completed
workout is the existing `match_score`/`suggest_matches`/`link_planned` — a scheduled template is suggested and linked
exactly like any plan (tested, including a template with no derivable duration, which still matches on day and sport).

**Examples** (`catch/seed/workout_templates.json`, seeded idempotently by `external_id`): seven generic structures,
`is_example`, read-only (duplicate to edit), badged "Example — not prescribed training", excluded from the coach's
`search_workout_library` unless `include_examples=true`. They describe structure only; they make no training claims.
An archived example stays archived across restarts.

## Technique notes

Categories: catch, drive, finish, recovery, sequencing, posture, rate_control, blade_boat_handling. A note can attach to
a workout, a piece (which implies its workout), a date, or nothing but its category. Text plus optional media
**references** (an http(s) URL or an app-relative path with a label — nothing is uploaded or stored).
`visibility` is `private` (default) or `coach`.

**No quality is ever inferred.** The table has no rating/score/grade column, nothing derives one from strokes, HR or
GPS, every payload carries the sentence "Catch can't observe technique from this data…", the coach's system prompt
forbids judging technique, and the UI card is titled "Technique notes" so it can't be confused with the existing
stroke-metric "Technique" card.

## Coach feedback

An entry has an author (`author_role` coach|athlete, `author_id`, `author_name`), a date, optional workout/event/planned
links, text, optional focus areas (the technique categories plus pacing/fitness/strength/racing/other), a visibility, an
athlete response, and `created_via` (web | ai_coach | mcp | rest — shown on the timeline so an entry the in-app AI coach
logged is never mistaken for a human coach's). The athlete can also **log feedback they received** (`coach_name`), so the
by-coach filter works without coach accounts.

### Principals, visibility and ownership

There is no user table. A *principal* is derived per request (`catch/core/principal.py`):

| Caller | Principal |
|---|---|
| login cookie, role-less device token | **athlete** |
| device token created with `--role coach` | **coach** (`coach:<token id>`, display name from the token) |
| anything that didn't say who it is | **viewer** — sees nothing |

Rules (one code path: `principal.py`, table-driven in `tests/test_coaching_notes_sync.py`):

- Technique note: athlete sees all; a coach sees only `visibility == "coach"`; only the athlete writes/edits/deletes.
- Feedback `private` is the author's alone; `shared` is the athlete plus any coach principal. **A coach can only create
  `shared` entries** (no hidden coach-only text in the athlete's record). The athlete may keep their own entries private.
- **Only the author edits an entry** (text, focus, visibility, links) or deletes it. Nobody edits another author's entry,
  including the athlete editing a coach's. Only the athlete writes `athlete_response`.
- Not-allowed-to-see reads as **not found**, never "forbidden".
- **History:** every edit, response change and delete appends a `coach_feedback_revisions` row holding the entry's prior
  state *and the visibility it had then*; history is filtered per revision, so text from before an entry was shared never
  reaches a coach. Delete is soft (`deleted_at`): hidden everywhere through the API, kept in the revisions.
- Coach tokens reach **only five tools**: `search_workout_library`, `get_workout_template`, `get_technique_notes`,
  `get_coach_feedback`, `add_coach_feedback` (enforced in `call_tool` and again by `require_tool_auth`'s opt-in, so a
  new route can't hand a coach token athlete data by accident; a test walks every route). Sharing sleep/HR/load with a
  coach is a separate decision this app does not model. All `/api/library`, `/api/technique-notes`, `/api/coach-feedback`
  routes are cookie-only: **there is no coach web UI**; a coach uses a coach token against the tool endpoint or MCP.
- The athlete principal (login, the in-app AI coach, athlete device tokens) *does* see private notes — it is the
  athlete's own assistant — so private text reaches the LLM provider the athlete configured. The tool descriptions say so.

Mint a coach token: `uv run catch token create --name "sam" --role coach --display-name "Coach Sam"`.

### References that go stale

SQLite does not enforce foreign keys here, so the service cleans up explicitly: a canonical merge repoints notes and
feedback to the survivor (`matching._merge_canonicals`); `delete_event` clears `event_id`; `delete_planned` clears
`planned_id`; `delete_piece` clears a note's `piece_id` (keeping its workout). Each has a regression test.

## Coach / MCP tools (47 → 55)

`search_workout_library`, `get_workout_template`, `create_workout_template`, `update_workout_template` (also
`archived`), `get_technique_notes`, `add_technique_note`, `get_coach_feedback`, `add_coach_feedback`. Every write
**previews unless `confirm === true`** (the shared `_gate`; falsy, `"true"` and `1` don't count). As with the calendar
writes that is a shared code path plus the system prompt, not hard enforcement. `add_coach_feedback` accepts
`workout_date` when a coach knows only a date (exactly one workout that local day, else a clear error); a coach cannot
edit their own entry this session (no update tool; REST is cookie-only).

## Database: SQLite and PostgreSQL

New tables are plain `create_all`; `*_json` columns are TEXT; no JSON1, `PRAGMA`, `INSERT OR`, raw `text()`, `LIKE`
(tag/search filtering happens in Python over the owner's bounded rows). New columns on existing tables
(`api_tokens.role/display_name`, `planned_workouts.template_id`) are nullable via `_NEW_COLUMNS`, and a role-less token is
the athlete, so existing tokens keep working.

**Verified on a real PostgreSQL 18** (the local Homebrew server, a throwaway cluster and schema):
`tests/test_postgres_optional.py` creates the *entire* metadata, runs the `ALTER TABLE` statements against old-shape
tables, and drives the library, scheduling, notes, feedback, revisions, delete-detach and filters through the services.
It is skipped unless `CATCH_TEST_PG_URL` is set, so the Pi's suite needs no server:

```bash
CATCH_TEST_PG_URL=postgresql+psycopg://user@127.0.0.1:5432/db uv run --with 'psycopg[binary]' pytest tests/test_postgres_optional.py
```

(`uv.lock` is untouched.) Compile-only tests (`tests/test_db_migrations.py`) and a SQL-token scan over the new modules
run in the normal suite. Still SQLite-only: the engine itself (`catch/core/db.py`, WAL pragmas) and the
`CREATE INDEX IF NOT EXISTS` lines in `_migrate_columns`; the Postgres move must still revisit those. A migration smoke
on a copy of the real `data/catch.db` (which predates `api_tokens` and `planned_workouts`) creates everything, a second
`init_db` is a no-op, and the original file's hash is unchanged.
