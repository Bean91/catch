"""Session 33, Part E: the Settings page fires about a dozen requests at once. On the public build each replica has three pooled
database connections (CATCH_DB_POOL_SIZE=1 + 2 overflow). Measured on production before this session: alone, each request took
150–350 ms; together, every one of them took ~30.4 s and many returned 500.

The cause: `GET /api/ai/providers` was an `async def` route doing synchronous database work. Waiting for a pooled connection on
the event loop's own thread stops the loop, and the requests holding the other connections can only give them back through the
loop — so nothing moves until SQLAlchemy's pool timeout (30 s) fails the wait. This reproduces it with the same pool shape over
SQLite and a short timeout, so a regression shows up as failures here rather than a slow page in production.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.pool import QueuePool
from sqlmodel import Session, SQLModel, create_engine

from test_api_pieces import _login

SETTINGS_READS = (
    "/api/settings",
    "/api/connections",
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
POOL_TIMEOUT_S = 4


@pytest.fixture()
def small_pool_client(client, tmp_path, monkeypatch):
    """The real app, but every request gets its own Session from a 1 + 2 connection pool (the public build's shape)."""
    import catch.main as main_module
    from catch.api.deps import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'pool.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=2,
        pool_timeout=POOL_TIMEOUT_S,
    )
    SQLModel.metadata.create_all(engine)

    def per_request_session():
        with Session(engine) as s:
            yield s

    main_module.app.dependency_overrides[get_db] = per_request_session
    yield client
    engine.dispose()


def test_settings_requests_fired_together_all_succeed_quickly(small_pool_client):
    client = small_pool_client
    _login(client)

    def one(url: str) -> tuple[str, int, float]:
        t0 = time.perf_counter()
        r = client.get(url)
        return url, r.status_code, time.perf_counter() - t0

    for _ in range(3):
        with ThreadPoolExecutor(max_workers=len(SETTINGS_READS)) as pool:
            results = list(pool.map(one, SETTINGS_READS))
        failed = [(u, s) for u, s, _ in results if s != 200]
        assert not failed, failed
        slowest = max(t for _, _, t in results)
        assert slowest < POOL_TIMEOUT_S, f"a request waited {slowest:.1f}s — the pool timeout, i.e. starved"


def test_concurrent_requests_on_one_session_share_one_liveness_lookup():
    """A burst used to run one `session_is_live` query (one pooled connection) per request for the same session id."""
    import threading

    from catch.core.supabase_auth import SessionLiveness

    liveness = SessionLiveness()
    calls = []
    release = threading.Event()

    def slow_query(sid: str) -> bool:
        calls.append(sid)
        release.wait(2)
        return True

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(liveness.check, "sid-1", slow_query) for _ in range(12)]
        time.sleep(0.2)
        release.set()
        assert all(f.result() for f in futures)
    assert calls == ["sid-1"]
    assert liveness.check("sid-1", slow_query) is True and calls == ["sid-1"]  # cached afterwards


def test_saving_a_notification_setting_does_not_rescore_history(client, monkeypatch):
    import catch.sync.scoring as scoring

    _login(client)
    calls = []
    monkeypatch.setattr(scoring, "recompute_scores", lambda *a, **k: calls.append(k))
    assert client.put("/api/settings", json={"notifications": {"quiet_hours_start": "22:30"}}).status_code == 200
    assert client.put("/api/settings", json={"zone_mode": "power"}).status_code == 200
    assert calls == []
    assert client.put("/api/settings", json={"recovery_green": 70}).status_code == 200
    assert calls == [{"full": True}]


def test_switching_the_recovery_input_provider_does_not_re_resolve_workouts_inline(client, monkeypatch):
    """The recovery-inputs switch re-decides every day's readings. Re-resolving every workout whose zones read those days now runs
    as a background task (with the full recompute), not inside the request."""
    import catch.api.routes_analytics as routes
    import catch.sync.canonical as canonical

    _login(client)
    inline = []
    monkeypatch.setattr(canonical, "resolve_canonical", lambda *a, **k: inline.append(a))
    background = []
    monkeypatch.setattr(routes, "_resolve_all_and_recompute_in_background", lambda engine: background.append(engine))
    resp = client.put("/api/settings", json={"wellness_priority": {"resting_hr": ["whoop", "garmin"]}})
    assert resp.status_code == 200, resp.text
    assert inline == [] and len(background) == 1


def test_a_stored_value_from_before_the_new_rules_does_not_block_an_unrelated_save(client, session):
    """Settings saves its whole form. A max HR stored before session 33's validation (e.g. 240 from a provider) must not turn every
    later save into a 422."""
    import json

    from catch.core import tenant
    from catch.core.models import AppSettings
    from catch.core.settings_store import SETTINGS_ID

    session.add(AppSettings(id=SETTINGS_ID, data_json=json.dumps({"max_hr": 240, "zones": {"hr_pct": {"UT2": 60, "UT1": 50}}})))
    session.commit()
    _login(client)
    current = client.get("/api/settings").json()
    resp = client.put("/api/settings", json={**current, "notifications": {**current["notifications"], "quiet_hours_start": "21:00"}})
    assert resp.status_code == 200, resp.text
    assert client.put("/api/settings", json={"max_hr": 250}).status_code == 422  # a change is still validated
    assert tenant.pk(SETTINGS_ID)
