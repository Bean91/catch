"""Personal-deployment (SQLite, single owner) latency and SQL-statement count check — the Pi-shaped counterpart of
scripts/load_local.py (session 32, docs/performance.md).

Builds a scratch SQLite database in a temp directory (never data/catch.db, never the real .env's secrets), seeds `--years` of
realistic single-athlete history (daily wellness, a rowing session most days with a few hard Concept2 efforts, a strength
session twice a week with sets, body composition every other day, a morning check-in, four food logs a day, a weekly note),
runs one full score recompute, then times the main read endpoints and the writes that trigger a recompute, counting the SQL
statements each request issues. No network: the scheduler is never started and no provider is connected.

    uv run python scripts/perf_personal.py --years 3 --repeat 7 [--json out.json]
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
from sqlalchemy import event  # noqa: E402
from sqlmodel import Session  # noqa: E402

from catch.core import db as core_db  # noqa: E402
from catch.core.models import (  # noqa: E402
    Activity, BodyComp, CanonicalActivity, CheckIn, DailyWellness, Food, FoodLog, Note, StrengthSet,
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
)


def seed(years: int, rng: random.Random) -> dict:
    today = date.today()
    start_day = today - timedelta(days=365 * years)
    counts = dict.fromkeys(("days", "activities", "sets", "body", "food", "checkins"), 0)
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
                                      strain_trimp=rng.uniform(40, 160))
                s.add(c)
                s.flush()
                aid += 1
                s.add(Activity(owner_id=OWNER, source="concept2", external_id=f"c2-{aid}", type="rower", start=morning, duration=dur,
                               distance=dist, avg_hr=c.avg_hr, workout_type="JustRow", sport_family="rowing", canonical_id=c.id,
                               raw_json=json.dumps({"id": aid, "date": morning.isoformat(), "stroke_data": True, "pad": "x" * 1500})))
                counts["activities"] += 1
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
    args = ap.parse_args()

    import catch.main as main_module

    main_module.start_scheduler = lambda: None
    main_module.stop_scheduler = lambda: None
    core_db.init_db()

    t0 = time.perf_counter()
    counts = seed(args.years, random.Random(args.seed))
    seed_s = time.perf_counter() - t0

    from catch.sync.scoring import recompute_scores

    t0 = time.perf_counter()
    with Session(core_db.engine) as s:
        recompute_scores(s)
    full_recompute_ms = (time.perf_counter() - t0) * 1000

    counter = Counter()
    event.listen(core_db.engine, "before_cursor_execute", counter)
    results = []
    with TestClient(main_module.app) as client:
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
        today = date.today()
        for url in READS:
            url = url.format(from_=(today - timedelta(days=35)).isoformat(), to=(today + timedelta(days=7)).isoformat())
            results.append(measure(client, "GET", url, args.repeat, counter))
        results.append(measure(client, "POST", "/api/checkins", max(2, args.repeat // 2), counter,
                               {"date": today.isoformat(), "soreness": 2, "stress": 2, "mood": 4, "sleep_quality": 4}))
        latest = client.get("/api/activities?limit=1").json()
        items = latest.get("items", latest) if isinstance(latest, dict) else latest
        if items:
            results.append(measure(client, "PATCH", f"/api/activities/{items[0]['id']}", max(2, args.repeat // 2), counter, {"rpe": 6}))
    event.remove(core_db.engine, "before_cursor_execute", counter)

    out = {"years": args.years, "seeded": counts, "seed_s": round(seed_s, 1), "full_recompute_ms": round(full_recompute_ms),
           "results": results}
    print(f"seeded {counts} in {seed_s:.1f}s; full recompute {full_recompute_ms:.0f} ms")
    print(f"{'method':6} {'endpoint':55} {'status':>6} {'p50 ms':>8} {'max ms':>8} {'SQL':>6} {'bytes':>9}")
    for r in results:
        print(f"{r['method']:6} {r['url'][:55]:55} {r['status']:>6} {r['p50_ms']:>8} {r['max_ms']:>8} {r['sql']:>6} {r['bytes']:>9}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
