from __future__ import annotations

from catch.core import tenant
from catch.core.models import SyncState
from catch.sync import concept2_client, scheduler


def test_an_auth_error_during_sync_marks_the_connection_for_reconnect_and_stops_scheduled_retries(session, monkeypatch):
    """A refused credential can't be retried into working, so it is not counted toward the 3-failure alert: the connection is marked
    needs-reconnect, the user is told once, scheduled runs stop, and a manual sync (or a new credential) tries again."""
    from catch.sync import connections

    connections.store_credential(session, "concept2", "a-personal-token-123456", auth_method="personal_token")
    monkeypatch.setattr(scheduler, "get_session", lambda: _SessionCtx(session))
    calls = {"n": 0}

    def refused(session, updated_after=None, days=3, **kw):
        calls["n"] += 1
        raise concept2_client.Concept2AuthError("Concept2 rejected the saved authorization.")

    monkeypatch.setattr(concept2_client, "sync", refused)

    result = scheduler.run_sync("concept2")

    assert result["needs_reconnect"] is True and "error" in result
    row = session.get(SyncState, tenant.pk("concept2"))
    assert row.last_error and row.consecutive_failures == 0 and row.next_attempt_at is None
    assert connections.get(session, "concept2").status == connections.NEEDS_RECONNECT
    assert scheduler.run_sync("concept2") == {"source": "concept2", "skipped": "needs reconnect"}
    assert calls["n"] == 1
    assert scheduler.run_sync("concept2", manual=True)["needs_reconnect"] is True
    assert calls["n"] == 2


def test_a_plain_failure_counts_toward_the_alert_and_backs_off_exponentially(session, monkeypatch):
    from catch.sync import connections

    connections.store_credential(session, "concept2", "a-personal-token-123456", auth_method="personal_token")
    monkeypatch.setattr(scheduler, "get_session", lambda: _SessionCtx(session))

    def boom(session, updated_after=None, days=3, **kw):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(concept2_client, "sync", boom)
    assert "error" in scheduler.run_sync("concept2")
    row = session.get(SyncState, tenant.pk("concept2"))
    first = row.next_attempt_at
    assert row.consecutive_failures == 1 and first is not None
    assert scheduler.run_sync("concept2") == {"source": "concept2", "skipped": "backing off"}
    assert "error" in scheduler.run_sync("concept2", manual=True)  # a manual sync ignores the backoff
    session.refresh(row)
    assert row.consecutive_failures == 2 and row.next_attempt_at > first  # doubled


class _SessionCtx:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False
