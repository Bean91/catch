"""Personal-deployment (SQLite, single owner) latency and SQL-statement count check — the Pi-shaped counterpart of
scripts/load_local.py (session 32, docs/performance.md).

Builds a scratch SQLite database in a temp directory (never data/catch.db, never the real .env's secrets), seeds `--years` of
realistic single-athlete history (daily wellness, a rowing session most days with a few hard Concept2 efforts, a strength
session twice a week with sets, body composition every other day, a morning check-in, four food logs a day, a weekly note),
runs one full score recompute, then times the main read endpoints and the writes that trigger a recompute, counting the SQL
statements each request issues. No network: the scheduler is never started and no provider is connected.

    uv run python scripts/perf_personal.py --years 3 --repeat 7 [--json out.json]
    uv run python scripts/perf_personal.py --years 3 --only settings      # session 33: every Settings request + a concurrent burst
    uv run python scripts/perf_personal.py --years 3 --strokes            # session 36: plus a Concept2 stroke stream per rowing session
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PASSWORD = "perf-only-password-0"

_tmp = tempfile.mkdtemp(prefix="catch-perf-")
os.environ["CATCH_DEPLOYMENT"] = "personal"
os.environ["CATCH_DB_PATH"] = str(Path(_tmp) / "perf.db")
os.environ["CATCH_FIT_DIR"] = str(Path(_tmp) / "fit")
for _k in ("GARMIN_API_KEY", "CONCEPT2_ACCESS_TOKEN", "CONCEPT2_CLIENT_ID", "WITHINGS_CLIENT_ID", "WHOOP_CLIENT_ID", "VAPID_PRIVATE_KEY",
           "NTFY_TOPIC", "HEALTHCHECKS_SYNC_URL", "USDA_FDC_API_KEY"):
    os.environ[_k] = ""

from argon2 import PasswordHasher  # noqa: E402

os.environ["CATCH_PASSWORD_HASH"] = PasswordHasher().hash(PASSWORD)
if not os.environ.get("CATCH_FERNET_KEY"):
    from cryptography.fernet import Fernet

    os.environ["CATCH_FERNET_KEY"] = Fernet.generate_key().decode()

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event, insert  # noqa: E402
from sqlmodel import Session  # noqa: E402

from catch.core import db as core_db  # noqa: E402
from catch.core.models import (  # noqa: E402
    Activity, BodyComp, CanonicalActivity, CheckIn, DailyWellness, Food, FoodLog, Note, StrengthSet, Stroke,
)

OWNER = "owner"

READS = (
    "/api/today",
    "/api/activities?limit=50",
    "/api/trends?metric=hrv_rmssd",
    "/api/series?metrics=hrv_rmssd,resting_hr,recovery,strain",
    "/api/wellness",
    "/api/predict/2k",
    "/api/pbs",
    "/api/erg/results",
    "/api/trends/volume?weeks=12",
    "/api/calendar?from={from_}&to={to}",
    "/api/nutrition/summary/week?from={from_}&to={to}",
    "/api/body",
    "/api/checkins/today",
    "/api/training-intelligence/profile",
    "/api/training-intelligence/trends",
    "/api/training-intelligence/distribution",
    "/api/training-intelligence/consistency",
    "/api/training-intelligence/insights",
    "/api/gym/muscle-readiness",
    "/api/status",
    # Session 36
    "/api/records",
    "/api/lab/progression",
    "/api/lab/hr-at-workload",
    "/api/lab/split-by-rate",
    "/api/lab/split-by-rate?from={from3y}",
    "/api/lab/power-curve?from={from3y}",
    "/api/trends/load-history?weeks=26",
    "/api/goals",
    "/api/activities?limit=30&q=steady",
    "/api/export/activities",
)


# Session 33: every request the Settings page makes when it opens (docs/performance.md "Settings").
SETTINGS_READS = (
    "/api/settings",
    "/api/connections",
    "/api/sync/status",
    "/api/time-zone",
    "/api/me",
    "/api/push/subscriptions",
    "/api/nutrition/targets",
    "/api/illness/backtest",
    "/api/coach/settings",
    "/api/coach/tokens",
    "/api/ai/providers",
    "/api/zones",
)


def burst(client: TestClient, urls: list[str], rounds: int) -> dict:
    """Every Settings request at once from parallel threads, the way the page fires them, repeated `rounds` times. Reports each
    request's median latency inside the burst and the median time until the last one finished (what a user waits for)."""
    from concurrent.futures import ThreadPoolExecutor

    per: dict[str, list[float]] = {u: [] for u in urls}
    walls: list[float] = []
    statuses: dict[str, int] = {}
    for _ in range(rounds):
        t0 = time.perf_counter()

        def one(u: str) -> tuple[str, float, int]:
            s0 = time.perf_counter()
            r = client.get(u)
            return u, (time.perf_counter() - s0) * 1000, r.status_code

        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            for u, ms, status in pool.map(one, urls):
                per[u].append(ms)
                statuses[u] = status
        walls.append((time.perf_counter() - t0) * 1000)
    return {
        "wall_p50_ms": round(statistics.median(walls), 1),
        "requests": [{"url": u, "status": statuses[u], "p50_ms": round(statistics.median(v), 1)} for u, v in per.items()],
    }


def seed_ai_credential() -> None:
    """A configured provider so the AI cards exercise their real path (a stored, sealed key) — never used for a network call."""
    from catch.coach import settings as coach_settings

    with Session(core_db.engine) as s:
        coach_settings.set_credential(s, "anthropic", "sk-ant-perf-only-not-a-real-key-000000", OWNER)
        coach_settings.update_coach_settings(s, {"provider": "anthropic", "models": {"anthropic": "claude-sonnet-5-5"}}, OWNER)


def _strokes(activity_id: int, dur: float, pace: float, hard: bool, rng: random.Random) -> list[dict]:
    """Session 36 (--strokes): a Concept2-shaped stroke stream, so the Performance Lab's stroke aggregate is measured on real volume."""
    rows, t, d, seq = [], 0.0, 0.0, 0
    base_rate = 32.0 if hard else 20.0
    while t < dur:
        rate = base_rate + rng.choice((-2, -1, 0, 0, 1, 2))
        p = pace + rng.uniform(-3, 3)
        dt = 60.0 / rate
        t += dt
        d += 500.0 * dt / p
        rows.append({"owner_id": OWNER, "activity_id": activity_id, "seq": seq, "t": round(t, 1), "distance": round(d, 1), "pace_500m": round(p, 1),
                     "watts": round(2.8 / (p / 500.0) ** 3, 1), "stroke_rate": rate, "hr": 130.0 + (40 if hard else 0) + rng.uniform(-5, 5)})
        seq += 1
    return rows


def seed(years: int, rng: random.Random, strokes: bool = False) -> dict:
    today = date.today()
    start_day = today - timedelta(days=365 * years)
    counts = dict.fromkeys(("days", "activities", "sets", "body", "food", "checkins", "strokes"), 0)
    with Session(core_db.engine) as s:
        food = Food(owner_id=OWNER, source="manual", name="Oats", kcal_100g=380, protein_100g=13, carbs_100g=67, fat_100g=7)
        s.add(food)
        s.flush()
        day = start_day
        aid = 0
        while day <= today:
            counts["days"] += 1
            s.add(DailyWellness(owner_id=OWNER, date=day, resting_hr=rng.randint(44, 56), hrv_rmssd=rng.uniform(55, 95),
                                sleep_seconds=rng.randint(6 * 3600, 9 * 3600), steps=rng.randint(4000, 14000), active_kcal=rng.randint(200, 900)))
            s.add(CheckIn(owner_id=OWNER, date=day, soreness=rng.randint(1, 4), stress=rng.randint(1, 4), mood=rng.randint(2, 5),
                          sleep_quality=rng.randint(2, 5)))
            counts["checkins"] += 1
            morning = datetime(day.year, day.month, day.day, 7, 0, tzinfo=timezone.utc)
            if rng.random() < 0.85:
                hard = rng.random() < 0.1
                dist = rng.choice([2000, 5000, 6000]) if hard else rng.choice([8000, 10000, 12000])
                pace = rng.uniform(98, 106) if hard else rng.uniform(118, 128)
                dur = dist / 500 * pace
                c = CanonicalActivity(owner_id=OWNER, sport_family="rowing", category="erg", start=morning, duration=dur, distance=dist,
                                      avg_hr=rng.uniform(165, 180) if hard else rng.uniform(128, 142), title="Row",
                                      strain_trimp=rng.uniform(40, 160), avg_power=round(2.8 / (pace / 500.0) ** 3, 1) if strokes else None)
                s.add(c)
                s.flush()
                aid += 1
                act = Activity(owner_id=OWNER, source="concept2", external_id=f"c2-{aid}", type="rower", start=morning, duration=dur,
                               distance=dist, avg_hr=c.avg_hr, workout_type="JustRow", sport_family="rowing", canonical_id=c.id,
                               raw_json=json.dumps({"id": aid, "date": morning.isoformat(), "stroke_data": True, "pad": "x" * 1500}))
                s.add(act)
                counts["activities"] += 1
                if strokes:
                    s.flush()
                    rows = _strokes(act.id, dur, pace, hard, rng)
                    s.execute(insert(Stroke), rows)
                    counts["strokes"] += len(rows)
            if day.weekday() in (1, 4):
                eve = morning + timedelta(hours=10)
                c = CanonicalActivity(owner_id=OWNER, sport_family="strength", category="other", start=eve, duration=3600, title="Lift",
                                      muscular_load_au=rng.uniform(1500, 3500))
                s.add(c)
                s.flush()
                aid += 1
                act = Activity(owner_id=OWNER, source="catch_strength", external_id=f"gym-{aid}", type="strength", start=eve, duration=3600,
                               sport_family="strength", canonical_id=c.id)
                s.add(act)
                s.flush()
                for i in range(15):
                    s.add(StrengthSet(owner_id=OWNER, client_id=f"set-{aid}-{i}", activity_id=act.id, exercise_id=1 + i % 5, seq=i, reps=5,
                                      load_kg=80.0, effective_load_kg=80.0, equipment_type="barbell", muscular_au=150.0))
                    counts["sets"] += 1
                counts["activities"] += 1
            if day.toordinal() % 2 == 0:
                s.add(BodyComp(owner_id=OWNER, source="withings", external_id=f"w-{day}", ts=morning, weight_kg=rng.uniform(80, 84)))
                counts["body"] += 1
            for h, meal in ((8, "breakfast"), (12, "lunch"), (16, "snack"), (19, "dinner")):
                s.add(FoodLog(owner_id=OWNER, ts=datetime(day.year, day.month, day.day, h, tzinfo=timezone.utc), meal=meal, food_id=food.id,
                              quantity=150, unit="g", kcal=570, protein=20, carbs=100, fat=10))
                counts["food"] += 1
            if day.weekday() == 6:
                s.add(Note(owner_id=OWNER, date=day, text="weekly note", rpe=rng.randint(3, 8)))
            day += timedelta(days=1)
            if counts["days"] % 200 == 0:
                s.commit()
        s.commit()
    return counts


class Counter:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self, *args, **kwargs) -> None:
        self.n += 1


def measure(client: TestClient, method: str, url: str, repeat: int, counter: Counter, body: dict | None = None) -> dict:
    times, stmts, status = [], [], None
    for _ in range(repeat):
        counter.n = 0
        t0 = time.perf_counter()
        r = client.request(method, url, json=body)
        times.append((time.perf_counter() - t0) * 1000)
        stmts.append(counter.n)
        status = r.status_code
        size = len(r.content)
    times.sort()
    return {"method": method, "url": url, "status": status, "p50_ms": round(statistics.median(times), 1), "max_ms": round(times[-1], 1),
            "sql": int(statistics.median(stmts)), "bytes": size}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--repeat", type=int, default=7)
    ap.add_argument("--seed", type=int, default=32)
    ap.add_argument("--json", help="write the results here as JSON")
    ap.add_argument("--only", choices=("all", "settings"), default="all")
    ap.add_argument("--strokes", action="store_true", help="session 36: also seed a Concept2 stroke stream (and average power) for every rowing session")
    args = ap.parse_args()

    import catch.main as main_module

    main_module.start_scheduler = lambda: None
    main_module.stop_scheduler = lambda: None
    core_db.init_db()

    t0 = time.perf_counter()
    counts = seed(args.years, random.Random(args.seed), strokes=args.strokes)
    seed_s = time.perf_counter() - t0

    from catch.sync.scoring import recompute_scores

    t0 = time.perf_counter()
    with Session(core_db.engine) as s:
        recompute_scores(s)
    full_recompute_ms = (time.perf_counter() - t0) * 1000

    seed_ai_credential()
    counter = Counter()
    event.listen(core_db.engine, "before_cursor_execute", counter)
    results = []
    settings_burst = None
    with TestClient(main_module.app) as client:
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
        today = date.today()
        for url in SETTINGS_READS:
            results.append(measure(client, "GET", url, args.repeat, counter))
        results.append(measure(client, "PUT", "/api/settings", max(2, args.repeat // 2), counter, {"notifications": {"quiet_hours_start": "22:30"}}))
        settings_burst = burst(client, list(SETTINGS_READS), args.repeat)
        if args.strokes and args.only == "all":
            # Session 36 follow-up: strokes seeded in bulk have no per-recording summary yet, so the first 3-year read builds every
            # recording's summary (the cold cost, once); everything after reads the cache.
            cold_url = f"/api/lab/split-by-rate?from={(today - timedelta(days=3 * 365)).isoformat()}"
            results.append({**measure(client, "GET", cold_url, 1, counter), "url": cold_url + " (cold: builds the cache)"})
        for url in READS if args.only == "all" else ():
            url = url.format(from_=(today - timedelta(days=35)).isoformat(), to=(today + timedelta(days=7)).isoformat(),
                             from3y=(today - timedelta(days=3 * 365)).isoformat())
            results.append(measure(client, "GET", url, args.repeat, counter))
        if args.only == "all":
            results.append(measure(client, "POST", "/api/checkins", max(2, args.repeat // 2), counter,
                                   {"date": today.isoformat(), "soreness": 2, "stress": 2, "mood": 4, "sleep_quality": 4}))
            latest = client.get("/api/activities?limit=1").json()
            items = latest.get("items", latest) if isinstance(latest, dict) else latest
            if items:
                results.append(measure(client, "PATCH", f"/api/activities/{items[0]['id']}", max(2, args.repeat // 2), counter, {"rpe": 6}))
    event.remove(core_db.engine, "before_cursor_execute", counter)

    out = {"years": args.years, "seeded": counts, "seed_s": round(seed_s, 1), "full_recompute_ms": round(full_recompute_ms),
           "results": results, "settings_burst": settings_burst}
    print(f"seeded {counts} in {seed_s:.1f}s; full recompute {full_recompute_ms:.0f} ms")
    print(f"{'method':6} {'endpoint':55} {'status':>6} {'p50 ms':>8} {'max ms':>8} {'SQL':>6} {'bytes':>9}")
    for r in results:
        print(f"{r['method']:6} {r['url'][:55]:55} {r['status']:>6} {r['p50_ms']:>8} {r['max_ms']:>8} {r['sql']:>6} {r['bytes']:>9}")
    if settings_burst:
        print(f"\nSettings burst ({len(SETTINGS_READS)} requests at once): last one done after {settings_burst['wall_p50_ms']} ms (median)")
        for r in settings_burst["requests"]:
            print(f"  {r['url'][:45]:45} {r['status']:>4} {r['p50_ms']:>8} ms")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
