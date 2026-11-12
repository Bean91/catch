from __future__ import annotations

from catch.core import tenant
from catch.core.models import SyncState
from catch.sync import concept2_client, scheduler


def test_an_auth_error_during_sync_is_recorded_as_a_failure_not_silently_swallowed(session, monkeypatch):
    """Task's quality-bar scenario ("break a source on purpose (bad token)") depends on this:
    Concept2Client._check already raises Concept2AuthError on a 401 rather than failing open
    (unlike catch/sync/garmin_client.py's backfill-only retry helper, which does swallow a
    persistent 401 into "0 rows this window" — but that path is never used by the regular
    scheduled sync this test exercises). Locks in that `run_sync` -> `record_error` ->
    consecutive_failures wiring actually fires for a real auth failure, not just a generic
    network error."""
    monkeypatch.setattr(scheduler, "get_session", lambda: _SessionCtx(session))
    monkeypatch.setattr(
        concept2_client,
        "sync",
        lambda session, updated_after=None, days=3: (_ for _ in ()).throw(
            concept2_client.Concept2AuthError("Concept2 access token invalid or expired")
        ),
    )

    result = scheduler.run_sync("concept2")

    assert "error" in result
    row = session.get(SyncState, tenant.pk("concept2"))
    assert row.consecutive_failures == 1
    assert "invalid or expired" in row.last_error


class _SessionCtx:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False
