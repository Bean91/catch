"""Multi-user latency and concurrency check against a LOCAL public-mode Catch on a throwaway `supabase start` stack (launch audit §H).

Creates N disposable users through GoTrue's admin API, seeds each with `--years` of realistic history directly as the database admin
(daily wellness, one canonical + source activity per day, a note a week), then measures the main read endpoints one at a time
(p50/p95/max) and under concurrency (all users at once), and samples `pg_stat_activity` for the runtime role's connection count.
Refuses any non-loopback host. Deletes its users at the end (the auth.users trigger cascades their rows). Never prints a key.

    LOAD_BASE_URL=http://127.0.0.1:8799 LOAD_SUPABASE_URL=… LOAD_PUBLISHABLE_KEY=… LOAD_SECRET_KEY=… LOAD_ADMIN_DB_URL=… \\
        uv run python scripts/load_local.py --users 20 --years 3 --concurrency 40
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import statistics
import sys
import time
from urllib.parse import urlsplit

import httpx
import psycopg

ENDPOINTS = (
    "/api/me", "/api/today", "/api/activities?limit=50", "/api/trends?metric=hrv_rmssd", "/api/series?metrics=hrv_rmssd,resting_hr,recovery",
    "/api/wellness", "/api/predict/2k", "/api/calendar?from={from_}&to={to}", "/api/status",
)


def _local(url: str) -> bool:
    return urlsplit(url).hostname in ("127.0.0.1", "localhost")


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"Set {name} (see the module docstring)")
    return value


SEED_SQL = """
WITH days AS (SELECT d::date AS day, row_number() OVER (ORDER BY d) AS n FROM generate_series(current_date - (%(days)s - 1), current_date, interval '1 day') d),
w AS (
  INSERT INTO catch.daily_wellness (owner_id, date, source, resting_hr, hrv_rmssd, sleep_seconds, steps, active_kcal, total_kcal, wake_time_minutes, updated_at)
  SELECT %(o)s, day, 'garmin', 48 + (n %% 7), 60 + (n %% 13), 25000 + (n %% 9) * 600, 6000 + (n %% 11) * 500, 300 + (n %% 5) * 40, 2400 + (n %% 5) * 80, 420, now() FROM days
  RETURNING 1
),
c AS (
  INSERT INTO catch.canonical_activities (owner_id, sport_family, start, duration, distance, avg_hr, max_hr, title, created_at, updated_at)
  SELECT %(o)s, 'rowing', day + time '07:00', 3600, 12000 + (n %% 5) * 500, 140 + (n %% 10), 175, 'Steady row', now(), now() FROM days
  RETURNING id, start
)
INSERT INTO catch.activities (owner_id, source, external_id, type, sport_family, start, duration, distance, avg_hr, max_hr, canonical_id, updated_at)
SELECT %(o)s, 'concept2', 'load-' || c.id, 'rower', 'rowing', c.start, 3600, 12000, 145, 175, c.id, now() FROM c
"""


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


async def timed(client: httpx.AsyncClient, path: str, token: str) -> tuple[float, int]:
    t = time.perf_counter()
    r = await client.get(path, headers={"authorization": f"Bearer {token}"})
    return (time.perf_counter() - t) * 1000, r.status_code


async def main_async(args) -> int:
    base, sb, pub, sec, admin_url = env("LOAD_BASE_URL").rstrip("/"), env("LOAD_SUPABASE_URL").rstrip("/"), env("LOAD_PUBLISHABLE_KEY"), env("LOAD_SECRET_KEY"), env("LOAD_ADMIN_DB_URL")
    if not all(_local(u) for u in (base, sb, admin_url)):
        raise SystemExit("Refusing: this script only runs against a local stack")
    adm = {"apikey": sec, "authorization": f"Bearer {sec}"}
    users: list[tuple[str, str]] = []
    failures = 0
    async with httpx.AsyncClient(base_url=base, timeout=60) as client:
        try:
            t0 = time.perf_counter()
            for i in range(args.users):
                email, pw = f"load-{i}-{secrets.token_hex(3)}@example.com", secrets.token_urlsafe(18) + "aA1!"
                uid = httpx.post(f"{sb}/auth/v1/admin/users", headers=adm, json={"email": email, "password": pw, "email_confirm": True}, timeout=20).json()["id"]
                tok = httpx.post(f"{sb}/auth/v1/token?grant_type=password", headers={"apikey": pub}, json={"email": email, "password": pw}, timeout=20).json()["access_token"]
                users.append((uid, tok))
                assert (await client.get("/api/me", headers={"authorization": f"Bearer {tok}"})).status_code == 200
            with psycopg.connect(admin_url) as conn:
                for uid, _ in users:
                    conn.execute(SEED_SQL, {"o": uid, "days": args.years * 365})
                conn.commit()
                rows = conn.execute("SELECT count(*) FROM catch.activities").fetchone()[0]
            print(f"seeded {len(users)} users, {rows} activities ({args.years} y each) in {time.perf_counter() - t0:.1f}s")

            today = time.strftime("%Y-%m-%d")
            month_ago = time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * 86400))
            paths = [p.format(from_=month_ago, to=today) for p in ENDPOINTS]

            print("\nsequential (one user, warm), ms:")
            _, tok = users[0]
            for p in paths:
                await timed(client, p, tok)
                samples = [await timed(client, p, tok) for _ in range(args.repeat)]
                ms = [s[0] for s in samples]
                codes = {s[1] for s in samples}
                failures += sum(1 for s in samples if s[1] >= 500)
                print(f"  {p:45s} p50 {statistics.median(ms):7.1f}  p95 {pct(ms, 95):7.1f}  max {max(ms):7.1f}  status {sorted(codes)}")

            print(f"\nconcurrent: {args.concurrency} in flight, every user x every endpoint x {args.rounds} rounds")
            sem = asyncio.Semaphore(args.concurrency)
            peak = {"conns": 0}

            async def one(path: str, token: str):
                async with sem:
                    return await timed(client, path, token)

            async def sample_connections(stop: asyncio.Event):
                with psycopg.connect(admin_url, autocommit=True) as conn:
                    while not stop.is_set():
                        n = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE usename = 'catch_api'").fetchone()[0]
                        peak["conns"] = max(peak["conns"], n)
                        await asyncio.sleep(0.2)

            stop = asyncio.Event()
            sampler = asyncio.create_task(sample_connections(stop))
            jobs = [one(p, tok) for _ in range(args.rounds) for _, tok in users for p in paths]
            t = time.perf_counter()
            out = await asyncio.gather(*jobs)
            wall = time.perf_counter() - t
            stop.set()
            await sampler
            ms = [o[0] for o in out]
            by_code: dict[int, int] = {}
            for _, code in out:
                by_code[code] = by_code.get(code, 0) + 1
            failures += sum(n for c, n in by_code.items() if c >= 500)
            print(f"  {len(out)} requests in {wall:.1f}s ({len(out) / wall:.0f} req/s); p50 {statistics.median(ms):.0f} ms, p95 {pct(ms, 95):.0f} ms, "
                  f"p99 {pct(ms, 99):.0f} ms, max {max(ms):.0f} ms; status {by_code}; peak catch_api connections {peak['conns']}")
        finally:
            for uid, _ in users:
                httpx.request("DELETE", f"{sb}/auth/v1/admin/users/{uid}", headers=adm, json={"should_soft_delete": False}, timeout=20)
            print(f"\ncleaned up {len(users)} users")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=40)
    ap.add_argument("--repeat", type=int, default=10)
    ap.add_argument("--rounds", type=int, default=2)
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
