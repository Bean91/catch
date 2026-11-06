from __future__ import annotations

from unittest.mock import patch

from catch.sync import scheduler


def test_check_notifications_calls_every_trigger_and_survives_one_failing(session, monkeypatch):
    monkeypatch.setattr(scheduler, "get_session", lambda: _FakeSessionCtx(session))

    calls = []

    def make_check(name):
        def _check(s):
            calls.append(name)
            if name == "check_illness":
                raise RuntimeError("boom")

        return _check

    with patch("catch.notify.triggers.check_morning_brief", side_effect=make_check("check_morning_brief")), patch(
        "catch.notify.triggers.check_illness", side_effect=make_check("check_illness")
    ), patch("catch.notify.triggers.check_garmin_key_expiring", side_effect=make_check("check_garmin_key_expiring")), patch(
        "catch.notify.triggers.check_sync_stale", side_effect=make_check("check_sync_stale")
    ), patch("catch.notify.triggers.check_test_reminder", side_effect=make_check("check_test_reminder")):
        scheduler.check_notifications()

    assert calls == [
        "check_morning_brief",
        "check_illness",
        "check_garmin_key_expiring",
        "check_sync_stale",
        "check_test_reminder",
    ]


class _FakeSessionCtx:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False
