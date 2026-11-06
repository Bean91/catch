from __future__ import annotations

from sqlmodel import select

from catch.core.models import NotificationLog, SyncState
from catch.sync import state


def test_record_error_increments_consecutive_failures(session):
    state.record_error(session, "garmin", "boom")
    state.record_error(session, "garmin", "boom again")

    row = session.get(SyncState, "garmin")
    assert row.consecutive_failures == 2
    assert row.last_error == "boom again"


def test_crossing_the_threshold_sends_exactly_one_alert(session):
    state.record_error(session, "garmin", "e1")
    state.record_error(session, "garmin", "e2")

    state.record_error(session, "garmin", "e3")  # 3rd in a row — crosses the threshold

    row = session.get(SyncState, "garmin")
    assert row.consecutive_failures == 3
    assert row.alert_sent_at is not None

    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "sync_broken"]
    assert len(logs) == 1

    state.record_error(session, "garmin", "e4")  # 4th — must NOT re-alert
    state.record_error(session, "garmin", "e5")

    row = session.get(SyncState, "garmin")
    assert row.consecutive_failures == 5
    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "sync_broken"]
    assert len(logs) == 1


def test_a_success_clears_the_failure_count_and_alert_episode(session):
    state.record_error(session, "garmin", "e1")
    state.record_error(session, "garmin", "e2")
    state.record_error(session, "garmin", "e3")
    assert session.get(SyncState, "garmin").alert_sent_at is not None

    state.record_success(session, "garmin")

    row = session.get(SyncState, "garmin")
    assert row.consecutive_failures == 0
    assert row.alert_sent_at is None
    assert row.last_error is None
