"""Settings-page latency on a DEPLOYED public Catch (session 33, docs/performance.md "Settings").

Creates one disposable user through GoTrue's admin API (same pattern and environment as scripts/smoke_public.py), signs in, and
measures every request the Settings page makes when it opens: each one alone, then all of them at once (the way the page fires
them), `--rounds` times. Read-only apart from the user it creates, which it deletes at the end. Never prints a secret.

  SMOKE_BASE_URL, SMOKE_SUPABASE_URL, SMOKE_PUBLISHABLE_KEY, SMOKE_SECRET_KEY or SMOKE_SECRET_KEY_FILE   (see smoke_public.py)

Run:  uv run python scripts/perf_settings.py --rounds 7 [--json out.json]

A fresh account has no history, so this measures the fixed cost of each request (auth, database round trips, the pool) — the
history-dependent costs are measured by scripts/perf_personal.py --only settings.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
import smoke_public as smoke  # noqa: E402

# Keep in step with scripts/perf_personal.py SETTINGS_READS (the personal-only /api/status is not on the public Settings page).
READS = (
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
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=7)
    ap.add_argument("--json")
    ap.add_argument("--reads", help="comma-separated override of the request list")
    args = ap.parse_args()
    for name in ("SMOKE_BASE_URL", "SMOKE_SUPABASE_URL", "SMOKE_PUBLISHABLE_KEY"):
        smoke.need(name)
    if not smoke.SEC:
        raise SystemExit("Set SMOKE_SECRET_KEY or SMOKE_SECRET_KEY_FILE")
    reads = tuple(args.reads.split(",")) if args.reads else READS

    user = smoke.User("perf")
    smoke.admin_create(user)
    try:
        if not smoke.sign_in(user):
            raise SystemExit("sign-in failed")
        client = httpx.Client(base_url=smoke.BASE, headers=user.headers(), timeout=60)
        t0 = time.perf_counter()
        warm = client.get("/api/health")
        first_ms = (time.perf_counter() - t0) * 1000

        sequential: dict[str, list[float]] = {u: [] for u in reads}
        statuses: dict[str, set[int]] = {u: set() for u in reads}
        for _ in range(args.rounds):
            for u in reads:
                s0 = time.perf_counter()
                r = client.get(u)
                sequential[u].append((time.perf_counter() - s0) * 1000)
                statuses[u].add(r.status_code)

        in_burst: dict[str, list[float]] = {u: [] for u in reads}
        walls: list[float] = []
        for _ in range(args.rounds):
            b0 = time.perf_counter()

            def one(u: str) -> tuple[str, float, int]:
                s0 = time.perf_counter()
                r = client.get(u)
                return u, (time.perf_counter() - s0) * 1000, r.status_code

            with ThreadPoolExecutor(max_workers=len(reads)) as pool:
                for u, ms, status in pool.map(one, reads):
                    in_burst[u].append(ms)
                    statuses[u].add(status)
            walls.append((time.perf_counter() - b0) * 1000)
        client.close()
    finally:
        if user.id:
            smoke.admin_delete(user.id)

    out = {
        "base": smoke.BASE,
        "first_request_ms": round(first_ms, 1),
        "first_status": warm.status_code,
        "burst_wall_p50_ms": round(statistics.median(walls), 1),
        "burst_wall_max_ms": round(max(walls), 1),
        "requests": [
            {
                "url": u,
                "statuses": sorted(statuses[u]),
                "alone_p50_ms": round(statistics.median(sequential[u]), 1),
                "in_burst_p50_ms": round(statistics.median(in_burst[u]), 1),
                "in_burst_max_ms": round(max(in_burst[u]), 1),
            }
            for u in reads
        ],
    }
    print(f"first request {out['first_request_ms']} ms ({out['first_status']}); burst of {len(reads)}: last done after "
          f"{out['burst_wall_p50_ms']} ms median, {out['burst_wall_max_ms']} ms worst")
    print(f"{'endpoint':32} {'status':>8} {'alone p50':>10} {'burst p50':>10} {'burst max':>10}")
    for r in out["requests"]:
        print(f"{r['url']:32} {','.join(map(str, r['statuses'])):>8} {r['alone_p50_ms']:>10} {r['in_burst_p50_ms']:>10} {r['in_burst_max_ms']:>10}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
