# Performance (session 32)

Measured before changing anything, then after. Both deployments were measured: the personal Pi shape (SQLite, one owner) and the
public shape (Postgres through the `catch_api` role with forced RLS and a real GoTrue token). Neither set is a production or Pi
measurement: both ran on a laptop. The Pi 3 runs this pure-Python work several times slower, and the ratios are what carry over.

## How it was measured

- **Personal:** `uv run python scripts/perf_personal.py --years 3 --repeat 7`. It builds a scratch SQLite database (never
  `data/catch.db` or `.env`) and seeds three years:
  - 1,096 days of wellness and check-ins;
  - 1,255 activities (a row most mornings, some hard efforts, lifting twice a week with 4,710 sets);
  - 548 weigh-ins and 4,384 food logs.

  It then times each endpoint as the median of 7 runs and counts SQL statements per request.
- **Public:** a one-off benchmark on the local `supabase start` stack, run against this branch and against a worktree of `main` with
  identical data:
  - two years for one signed-up user (730 days of wellness, check-ins and rows);
  - `catch_api` + RLS, with the median of 5 runs.

  It was a scratch test placed in `tests/pg` for the run and not committed; its shape matches `tests/test_query_budget.py`.
- `scripts/load_local.py` (multi-user concurrency) was not rerun. Its seed has no check-ins, lifting or writes, which is exactly what
  this session's bottlenecks were.

## Bottlenecks found

| # | Where | What | Fix |
|---|---|---|---|
| 1 | Every write | `recompute_scores` redid every day of history on each write. The duplicate matcher inside it ran one `match_decisions` query per candidate pair, twice per recompute: 5,914 of a check-in's 5,958 statements after the first fix. | Decisions are read once per pass. Each write recomputes from the earliest local day it touched (tracked on the session), seeding load and illness state from stored rows; a test asserts the result equals a full recompute. The remaining days load in a handful of batched queries instead of ~10 per day. |
| 2 | Public, every write | One process-wide *non-blocking* lock: one user's recompute silently skipped another user's that ran at the same moment (a correctness bug as well as a performance one). | A lock per owner. A recompute that can't get it within 30 s hands its start day to the running one, which re-runs from there. Nothing is skipped and no request waits long. |
| 3 | `/api/erg/results` | Re-resolved the whole body-composition history once per row (N+1) and sent every provider payload (`raw_json`, ~2 KB a row). | The weight lookup is resolved once per request, `raw_json` is not sent, and results are capped at 500 by default (`limit`). |
| 4 | Training intelligence, Today, the 2k estimate | `erg_test.list_tests` ran one query per erg session to find its Concept2 member, and pieces did one query per piece. | One batched query each. |
| 5 | `/api/trends/volume` and its three callers | Loaded every canonical activity ever, then filtered in Python. | Only the weeks asked for are read, by each workout's local day. |
| 6 | Series cache | Invalidated *every* user's cache on any user's recompute; unbounded. | Invalidated per owner; bounded LRU of 256 series. |
| 7 | Postgres indexes | `activities(canonical_id)` and `strokes(activity_id)` existed only on SQLite. Nothing indexed activity start or the new local day. | Migration 0011 and the SQLite startup add `activities(canonical_id)`, `(owner_id, start)`, `strokes(activity_id)`, `canonical_activities(owner_id, local_date)` / `(owner_id, start)`, `body_comp(owner_id, ts)`, `food_logs(owner_id, local_date)` and `user_zone_periods(owner_id, start_utc)`. |
| 8 | Sync | Every sync ran a full-history recompute. | It recomputes from the earliest day the sync wrote (`changed_since`). The one-time model/zone upgrade is a separate maintenance job. |
| 9 | Pi memory | Matching and the new backfill would have loaded every `Activity` with its `raw_json`. | `raw_json` is deferred wherever it isn't read. The backfill and timeline passes page 500 rows at a time. |

No new infrastructure was needed: no Redis and no new service. The one new dependency is the pure-Python `tzdata` wheel, so zone
data exists on slim images (docs/time.md).

## Personal (SQLite, 3 years)

Full recompute: **3,881 ms → 669 ms**.

| Request | Before p50 ms | SQL | Bytes | After p50 ms | SQL | Bytes |
|---|---|---|---|---|---|---|
| `POST /api/checkins` | 3,951.5 | 21,376 | 231 | **76.7** | **46** | 231 |
| `PATCH /api/activities/{id}` | 3,963.6 | 21,392 | 9,363 | **85.0** | **60** | 9,579 |
| `GET /api/erg/results` | 4,542.9 | 1,883 | 2,160,632 | **25.2** | **5** | 373,389 |
| `GET /api/training-intelligence/profile` | 269.6 | 971 | 3,454 | **24.6** | **25** | 3,458 |
| `GET /api/training-intelligence/trends` | 223.3 | 944 | 14 | **17.0** | **7** | 14 |
| `GET /api/trends/volume` | 9.3 | 2 | 1,237 | 2.8 | 4 | 1,237 |
| `GET /api/training-intelligence/consistency` | 13.8 | 8 | 393 | 6.3 | 12 | 393 |
| `GET /api/training-intelligence/insights` | 14.2 | 8 | 15 | 7.1 | 11 | 15 |
| `GET /api/today` | 22.0 | 25 | 8,301 | 24.8 | 19 | 11,175 |
| `GET /api/predict/2k` | 2.9 | 3 | 972 | 11.6 | 8 | 3,123 |
| `GET /api/activities?limit=50` | 6.6 | 3 | 64,552 | 7.3 | 3 | 75,790 |
| `GET /api/series` (4 metrics) | 9.6 | 0 | 151,110 | 10.2 | 0 | 157,509 |
| `GET /api/calendar` | 3.3 | 5 | 15,557 | 4.1 | 7 | 15,557 |
| `GET /api/body` | 9.3 | 2 | 116,092 | 9.4 | 2 | 116,092 |
| `GET /api/wellness` | 29.7 | 1 | 698,489 | 31.5 | 1 | 698,489 |

## Public (Postgres + RLS, 2 years)

| Request | Before (`main`) p50 ms / SQL | After p50 ms / SQL |
|---|---|---|
| First recompute (full) | 13,018 / 13,184 | **591 / 62** |
| `POST /api/checkins` | 9,206.6 / 13,179 | **126.9 / 56** |
| `GET /api/erg/results` | 655.3 / 1,465 (509 KB) | **35.3 / 7** (363 KB) |
| `GET /api/training-intelligence/profile` | 491.2 / 764 | **72.3 / 29** |
| `GET /api/today` | 44.5 / 30 | 45.2 / 23 |
| `GET /api/activities?limit=50` | 13.5 / 7 | 26.7 / 7 |
| `GET /api/predict/2k` | 10.0 / 7 | 32.0 / 11 |

## The one-time upgrade job

`run_maintenance` re-resolves every canonical once (each rowing session's power zones now use the 2k estimate as of its own date) and
recomputes all days. Timed with one year of per-second power and heart rate on 321 rowing sessions (426 canonicals): **1.1 s** for
the re-resolve on a laptop, so roughly 3 s for three years and, at the Pi 3's 10–20× slower single core, about 30–60 s once, in the
background. The 2k evidence it reads is built once per pass: the cache is dropped only when something that changes the evidence is
written (a source record, a piece, a canonical's overrides/category/day), not when resolve rewrites a canonical's cached fields.

## What got slower, and why

- **`/api/predict/2k`** went from about 3 to 12 ms on SQLite and 10 to 32 ms on Postgres. The estimate now reads a year of confirmed
  tests, pieces and hard rows instead of the 180-day continuous rows it used to average (docs/analytics.md §2). It is limited to the
  365-day window it can use, never the whole history.
- **Responses that grew:**
  - `/api/today`: +3 KB, for the 2k estimate's basis and measured 2k.
  - The activity list: +11 KB, for each workout's local day and zone.
  - `/api/nutrition/summary/week`: could not be compared, because the "before" run sent it without its required dates. It is now 4
    statements for any range, not 2 per day.
- **`GET /api/activities?limit=50` on Postgres** went from 13.5 to 26.7 ms with the same 7 statements. The difference is the request
  loading the person's time-zone timeline (profile and periods). That is noise-level in absolute terms, but it is reported as measured.

## Frontend

- Initial JS: **233.9 KB gzip**, against a budget of 250 KB (230.0 before). The setup page and the time-zone picker are in lazy chunks;
  the zone list comes from the browser (`Intl.supportedValuesOf`), so no zone data is shipped.
- No new polling on Today. The setup page polls `/api/connections` every 5 s only while its import step is open.
- The app reports its device zone at most hourly (or when the zone changes) and on returning to the foreground.
- Correctness was preserved throughout: incremental results equal full ones (tested), and nothing serves stale data silently. After a
  time-zone change, the recompute runs in the background.

## Regression guards

- `tests/test_query_budget.py` sets statement budgets for `/api/today`, `/api/activities`, `/api/predict/2k`, `/api/erg/results`,
  the training profile and a check-in write, on a seeded history.
- `tests/test_scoring_session32.py` asserts that incremental equals full.

Rerun `scripts/perf_personal.py` after any change to scoring or the hot reads.
