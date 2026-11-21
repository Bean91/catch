# Time zones and days (session 32)

Catch is used by people in different zones who travel. This is how it decides which calendar day — and which "today" — anything
belongs to. It closes launch-audit findings L-09 (no per-user zone), L-49 (mixed conventions), L-15 (copied meals drifting an hour
across DST) and L-24 (Concept2 results with no zone read as UTC).

## Conventions

- **Every absolute instant is stored in UTC** (`TIMESTAMP WITH TIME ZONE` on Postgres; sqlmodel's `UTCDateTime` on SQLite, which
  refuses naive values on write). A naive value that reaches the analytics is read as UTC, never as local time.
- **A calendar day is a plain `date`**, never an instant. Day-keyed tables keep their own local dates: `daily_wellness` (Garmin's
  `calendarDate`, Whoop's wake date — already the athlete's local day), check-ins, notes, planned workouts, events, club sessions.
- **Records bucketed by an instant are stamped** on write with the day and zone they happened in: `local_date` + `local_tz` on
  `activities`, `canonical_activities`, `food_logs` and `body_comp`. A stamp never changes because the athlete later moves.
- **A zone is an IANA name** (`Europe/Paris`) or, only where a provider gave nothing better, a fixed offset (`+09:00`). The home zone
  is always IANA and validated on the backend against the `tzdata` database.
- **One helper**: `catch/core/localtime.py` (DB-facing) over `catch/analytics/localtime.py` (pure). `tests/test_localtime.py` fails on
  any `date.today()`, `datetime.now()` or bare `.astimezone()` elsewhere under `catch/`.

## Where the zone comes from

| Setting / data | Where | Notes |
|---|---|---|
| Home zone | `user_profiles.timezone` | Chosen in setup or Settings → Time zone. Suggested from the device (`Intl…resolvedOptions().timeZone`), never from IP. |
| Follow my device | `user_profiles.follow_device_zone` | Default on. Off = everything uses the home zone (the single-zone model). |
| Timeline | `user_zone_periods(start_utc, tz, source)` | Where the athlete was, from when. Grown automatically (below); never edited by hand. |
| Fallback | — | No home zone: the Pi's host zone (`$TZ`, the `/etc/localtime` link, `/etc/timezone`), so a personal install behaves as before; UTC on the public build until a device reports one. |

**The timeline grows by itself.** The app (web and native) sends `PUT /api/time-zone/device` with the device's IANA zone when it opens
or returns to the foreground (at most hourly unless the zone changed). Each sync also reads what watches recorded — a Garmin
workout's local-minus-GMT start, a Whoop workout's or sleep's `timezone_offset`, a phone workout's offset in its ISO start — and opens
a period when the offset differs (`learn_from_records`). So "today" moves when a watch syncs from abroad even if Catch is never
opened. An offset that matches the current IANA zone's offset is recorded under that name (DST stays right); an offset-only period is
upgraded to the IANA name when a device report agrees.

**A device that disagrees with a watch** — a laptop still on home time while the phone and watch are abroad — is ignored if a
provider observation from the last 12 hours says otherwise.

## Which zone a record uses (priority)

1. A watch/phone-observed offset carried on the record itself (Garmin, Whoop, Apple Health, Health Connect).
2. The timeline period covering its instant.
3. An account-level provider zone: Concept2's `timezone` is the logbook *account's* setting, often home even on a hotel erg, so it only
   wins before any period is known.
4. The fallback above.

A canonical (merged) workout takes the best member's zone, or the athlete's **Change day** override (`overrides_json.local_date`,
limited to the recorded day ± 1 by `PATCH /api/activities/{id}`; the time itself never changes). With following off, every record uses
the home zone.

Records with no zone of their own — Withings weigh-ins, most Concept2 results, phone health readings — use the timeline at **their**
instant, not the zone at sync time, so a weigh-in synced after the trip still lands on the day it happened abroad. A Concept2 result
with neither `date_utc` nor `timezone` has its monitor-local `date` read in the timeline's zone at that time (was: assumed UTC).

## Days, ranges and "today"

- `today(session)` and `now_local(session)`: the current period's zone. `day_range(session, day)`: `[local midnight, next local midnight)`
  as UTC — 23 h on spring-forward, 25 h on fall-back. A wall-clock time skipped by spring-forward maps forward; a repeated one takes
  the first occurrence.
- `?from=`/`?to=` dates and naive datetimes are the athlete's local days/wall-clock (`date_bounds`, `naive_to_utc`), never UTC.
- A manual weigh-in date is stored at local noon of that day.
- "Copy yesterday's meals" keeps each meal's wall-clock time in the zone it was logged in (`shift_local_days`), across DST.
- A workout crossing local midnight belongs to the day it started.
- Travel days are what they were: flying west can make a 30-hour day, flying east an 18-hour one, and crossing the date line can
  skip or repeat a date. Each record lands on the day it was lived; nothing is split, duplicated or dropped. A skipped date enters
  acute/chronic load as a zero day, like rest.
- Weather stays UTC by design (Open-Meteo hours are UTC).

## Changing zones

Changing the home zone or the follow switch never touches an instant. Every stamped record is re-read (`restamp`), and scores are
recomputed from the earliest day that changed, in the background (`PUT /api/time-zone`). A new period from a late watch observation
re-stamps only the records from that instant to the next period. After a move west, a score row dated after the new "today" is
deleted rather than left as a phantom future day.

## Existing data

`catch.sync.scheduler.run_maintenance` — personal: a minute after start, then daily; public: before each user's sync tick — runs
`localtime.ensure_backfilled` once per person: learn the timeline from the whole history, stamp every unstamped record (paged, 500
rows at a time), re-resolve canonicals and recompute all scores. After that it is one small query per table.

## Background jobs

Notifications run per person under that person's owner context, so quiet hours, the morning-brief time and "already sent today" use
their own zone (`notify/triggers.py`). Sync windows ("the last N days") are the person's local days. Scheduling itself stays absolute:
APScheduler intervals on the Pi, `pg_cron` ticks on the public build. Sync never depends on the app being open.

## Frontend

`/api/me` returns `timezone`, `follow_device_zone`, `current_zone` and `today`. `web/src/lib/localTime.ts` adopts `current_zone`:
`todayISO()` is today in that zone (recomputed each call, so it rolls over at the athlete's midnight), and instants are formatted in it.
A workout shows its time in the zone it happened in, labelled ("07:10 · Tokyo") only when that differs from the current zone. Bare
`YYYY-MM-DD` strings are never zone-shifted; chart axes convert their local-midnight positions back with local calendar fields
(`toISODate`), never `toISOString().slice(0, 10)`.

## API

| Route | |
|---|---|
| `GET /api/time-zone` | home zone, follow switch, current zone, fallback, today |
| `PUT /api/time-zone` | `{timezone?, follow_device_zone?}` — 422 for anything not an IANA name |
| `PUT /api/time-zone/device` | `{timezone}` — the app's report; `{changed, current_zone, today}` |
| `PATCH /api/activities/{id}` | `local_date` — Change day (recorded day ± 1) |

## Tests

`tests/analytics/test_localtime_rules.py` (pure: New York, Paris, Tokyo, DST days, missing and repeated local times, the date line,
priority rules) and `tests/test_localtime.py` (stamping, the timeline from Garmin offsets, a late Withings weigh-in after travel,
Concept2 vs watch priority, device reports and the laptop-on-home-time case, home-zone changes, day strain across the UTC boundary,
backfill, per-user notification clocks, provider timestamps with and without zones, and the ban on server-clock calls);
`web/src/lib/localTime.test.ts`.

## Limitations

- A zone learned only from an offset has no DST rules until a device report names it.
- A watch whose own clock zone was wrong files its workouts on the wrong day until the athlete uses Change day.
- Recomputing after a zone change runs in the background; for a few seconds the Today screen can still show the previous numbers.
