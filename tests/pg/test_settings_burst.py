"""Session 33, Part E, on the real public runtime path: a real GoTrue user, the `catch_api` role under forced RLS, and the production
pool shape (CATCH_DB_POOL_SIZE=1 + 2 overflow). Every request the Settings page makes when it opens is fired at once, as the page
does. Before this session that starved the pool (production: ~30 s per request, many 500s); now every request must succeed well
inside the pool timeout. Set CATCH_PERF_OUT=<file> to keep the timings (docs/performance.md)."""

from __future__ import annotations

import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.pg.conftest import signup
from tests.pg.test_runtime import app  # noqa: F401  (the fixture: the real app on the runtime role)

pytestmark = pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")

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
ROUNDS = 5


def test_the_settings_burst_succeeds_on_the_production_pool_shape(app):  # noqa: F811
    user = signup("burst")
    for path in READS:  # warm: first-request costs (profile creation, JWKS) are not what this measures
        app.get(path, headers=user.headers)

    def one(path: str) -> tuple[str, int, float]:
        t0 = time.perf_counter()
        try:
            status = app.get(path, headers=user.headers).status_code
        except Exception:  # the test client re-raises a server error (e.g. the pool timeout) instead of returning a 500
            status = 500
        return path, status, (time.perf_counter() - t0) * 1000

    walls, per = [], {p: [] for p in READS}
    failures = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(READS)) as pool:
            for path, status, ms in pool.map(one, READS):
                per[path].append(ms)
                if status != 200:
                    failures.append((path, status))
        walls.append((time.perf_counter() - t0) * 1000)

    out = {"wall_p50_ms": round(statistics.median(walls), 1), "wall_max_ms": round(max(walls), 1),
           "requests": {p: round(statistics.median(v), 1) for p, v in per.items()}, "failures": failures}
    if os.environ.get("CATCH_PERF_OUT"):
        with open(os.environ["CATCH_PERF_OUT"], "w") as fh:
            json.dump(out, fh, indent=2)
    assert not failures, failures
    assert max(walls) < 10_000, out  # the pool timeout is 30 s; a starved burst waits for it
