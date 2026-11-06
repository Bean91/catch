from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime, timedelta, timezone

from sqlmodel import delete, select

from catch.core.models import DailyScore, Event, IllnessAck, NotificationLog
from catch.notify import push, triggers


def _no_vapid(monkeypatch):
    # Notification type/quiet-hours/dedup gating is what these tests exercise — not the real
    # send — so VAPID stays unconfigured (push.notify still writes a NotificationLog row with
    # zero devices, which is exactly what _sent_today/dedup read back).
    monkeypatch.setattr(push, "settings", dataclasses.replace(push.settings, vapid_private_key=""))


def test_morning_brief_syncs_first_and_reports_todays_recovery(session, monkeypatch):
    """Without the sync-first call this added, this would almost always report yesterday's
    (or nothing's) recovery — the regular 2h-interval job may not have run yet this soon
    after waking."""
    _no_vapid(monkeypatch)
    from catch.sync import scheduler as scheduler_module

    sync_calls = []
    monkeypatch.setattr(scheduler_module, "run_sync", lambda source, days=3: sync_calls.append((source, days)))
    # No wake-time samples seeded -> falls back to the 7:30 default, so the target send
    # window is 8:00-10:00; pin "now" inside it.
    monkeypatch.setattr(triggers, "_now_local", lambda: datetime(2026, 1, 1, 8, 5))

    today = date.today()
    session.add(DailyScore(date=today, recovery_json=json.dumps({"value": 72, "band": "green"})))
    session.commit()

    triggers.check_morning_brief(session)

    assert sync_calls == [("garmin", 1)]
    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "morning_brief"]
    assert len(logs) == 1
    assert "72%" in logs[0].body
    assert logs[0].deep_link == "/"


def test_morning_brief_does_not_fire_outside_its_window(session, monkeypatch):
    _no_vapid(monkeypatch)
    from catch.sync import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "run_sync", lambda source, days=3: None)
    monkeypatch.setattr(triggers, "_now_local", lambda: datetime(2026, 1, 1, 6, 0))  # well before 8:00

    triggers.check_morning_brief(session)

    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "morning_brief"]
    assert len(logs) == 0


def test_in_quiet_hours_wraps_past_midnight():
    settings = {"notifications": {"quiet_hours_start": "22:00", "quiet_hours_end": "06:00", "types": {}}}
    late = datetime(2026, 1, 1, 23, 0)
    early = datetime(2026, 1, 1, 5, 0)
    midday = datetime(2026, 1, 1, 12, 0)
    assert triggers._in_quiet_hours(settings, late) is True
    assert triggers._in_quiet_hours(settings, early) is True
    assert triggers._in_quiet_hours(settings, midday) is False


def test_garmin_key_expiring_fires_only_on_the_three_warn_days(session, monkeypatch):
    _no_vapid(monkeypatch)
    from catch.core.settings_store import update_settings

    for days_out, should_fire in [(14, True), (13, False), (3, True), (1, True), (0, False), (5, False)]:
        session.exec(delete(NotificationLog))
        session.commit()
        expires_on = (date.today() + timedelta(days=days_out)).isoformat()
        update_settings(session, {"garmin_key_expires_on": expires_on})

        triggers.check_garmin_key_expiring(session)

        logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "garmin_key_expiring"]
        assert (len(logs) == 1) == should_fire, f"days_out={days_out}"


def test_garmin_key_expiring_does_not_double_fire_same_day(session, monkeypatch):
    _no_vapid(monkeypatch)
    from catch.core.settings_store import update_settings

    update_settings(session, {"garmin_key_expires_on": (date.today() + timedelta(days=14)).isoformat()})
    triggers.check_garmin_key_expiring(session)
    triggers.check_garmin_key_expiring(session)


    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "garmin_key_expiring"]
    assert len(logs) == 1


def test_illness_notifies_once_and_sets_notified_at(session, monkeypatch):
    _no_vapid(monkeypatch)
    today = date.today()
    session.add(DailyScore(date=today, illness_json=json.dumps({"level": "likely", "explanation": "HRV and RHR both deviated."})))
    session.add(IllnessAck(date=today, first_flagged_at=datetime.now(timezone.utc)))
    session.commit()

    triggers.check_illness(session)


    ack = session.get(IllnessAck, today)
    assert ack.notified_at is not None
    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "illness"]
    assert len(logs) == 1
    assert "HRV and RHR" in logs[0].body

    triggers.check_illness(session)  # a second tick must not re-notify
    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "illness"]
    assert len(logs) == 1


def test_illness_does_not_notify_about_an_old_historical_flag(session, monkeypatch):
    """The exact "first deploy" scenario: a flag from a week ago, inserted by some earlier
    recompute, with notified_at never set because the notifier didn't exist yet."""
    _no_vapid(monkeypatch)
    old_day = date.today() - timedelta(days=7)
    session.add(DailyScore(date=old_day, illness_json=json.dumps({"level": "likely", "explanation": "old"})))
    session.add(IllnessAck(date=old_day, first_flagged_at=datetime.now(timezone.utc) - timedelta(days=7)))
    session.commit()

    triggers.check_illness(session)

    ack = session.get(IllnessAck, old_day)
    assert ack.notified_at is not None  # marked handled...
    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "illness"]
    assert len(logs) == 0  # ...but nothing was actually sent


def test_illness_skips_when_a_later_recompute_downgraded_the_level(session, monkeypatch):
    _no_vapid(monkeypatch)
    today = date.today()
    # illness_json now says "watch" (downgraded since this ack was first inserted) —
    # first_flagged_at/notified_at on the ack row are untouched either way (insert-only).
    session.add(DailyScore(date=today, illness_json=json.dumps({"level": "watch", "explanation": "x"})))
    session.add(IllnessAck(date=today, first_flagged_at=datetime.now(timezone.utc)))
    session.commit()

    triggers.check_illness(session)

    assert session.get(IllnessAck, today).notified_at is not None
    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "illness"]
    assert len(logs) == 0


def test_illness_skips_a_dismissed_flag(session, monkeypatch):
    _no_vapid(monkeypatch)
    today = date.today()
    session.add(DailyScore(date=today, illness_json=json.dumps({"level": "likely", "explanation": "x"})))
    session.add(IllnessAck(date=today, first_flagged_at=datetime.now(timezone.utc), dismissed=True))
    session.commit()

    triggers.check_illness(session)


    assert session.get(IllnessAck, today).notified_at is None
    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "illness"]
    assert len(logs) == 0


def test_test_reminder_fires_for_tomorrows_2k_test_with_a_pacing_plan(session, monkeypatch):
    _no_vapid(monkeypatch)
    tomorrow = date.today() + timedelta(days=1)
    session.add(
        Event(
            name="Erg test",
            date=tomorrow,
            type="2k_test",
            plan_json=json.dumps({"goal_time_s": 390.5}),
        )
    )
    session.commit()

    triggers.check_test_reminder(session)

    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "test_reminder"]
    assert len(logs) == 1
    assert "6:30" in logs[0].body or "6:31" in logs[0].body
    assert logs[0].deep_link == "/tests"


def test_check_sync_stale_alerts_once_when_no_success_in_36h(session, monkeypatch):
    _no_vapid(monkeypatch)
    from catch.core.models import SyncState

    stale_at = datetime.now(timezone.utc) - timedelta(hours=40)
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    session.add(SyncState(source="garmin", last_attempt_at=stale_at, last_success_at=None))
    session.add(SyncState(source="withings", last_attempt_at=recent, last_success_at=recent))
    session.add(SyncState(source="concept2", last_attempt_at=recent, last_success_at=recent))
    session.commit()

    triggers.check_sync_stale(session)

    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "sync_broken"]
    assert len(logs) == 1  # only garmin is stale — withings/concept2 synced an hour ago
    row = session.get(SyncState, "garmin")
    assert row.alert_sent_at is not None

    triggers.check_sync_stale(session)  # a second tick must not re-alert the same episode
    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "sync_broken"]
    assert len(logs) == 1


def test_check_sync_stale_leaves_a_recently_successful_source_alone(session, monkeypatch):
    _no_vapid(monkeypatch)
    from catch.core.models import SyncState

    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    session.add(SyncState(source="garmin", last_attempt_at=recent, last_success_at=recent))
    session.commit()

    triggers.check_sync_stale(session)

    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "sync_broken"]
    assert len(logs) == 0


def test_check_sync_stale_skips_a_source_that_has_never_been_attempted(session, monkeypatch):
    _no_vapid(monkeypatch)
    # No SyncState row at all — a fresh instance before its first scheduled sync tick.
    triggers.check_sync_stale(session)

    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "sync_broken"]
    assert len(logs) == 0


def test_test_reminder_ignores_a_b_priority_race_tomorrow(session, monkeypatch):
    _no_vapid(monkeypatch)
    tomorrow = date.today() + timedelta(days=1)
    session.add(Event(name="Club regatta", date=tomorrow, type="race", priority="B"))
    session.commit()

    triggers.check_test_reminder(session)


    logs = [n for n in session.exec(select(NotificationLog)).all() if n.type == "test_reminder"]
    assert len(logs) == 0
