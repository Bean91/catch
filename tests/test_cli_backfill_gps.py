from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timedelta, timezone

import pytest

import catch.cli as cli
from tests.test_weather_sync import START, _restore_fitdecode, row_activity  # noqa: F401


@pytest.fixture()
def cli_session(session, monkeypatch):
    @contextlib.contextmanager
    def fake_get_session():
        yield session

    monkeypatch.setattr(cli, "get_session", fake_get_session)
    monkeypatch.setattr(cli, "init_db", lambda: None)
    return session


def test_backfill_gps_with_weather_terminates_when_the_provider_is_down(cli_session, tmp_path, capsys, monkeypatch):
    for i in range(3):
        row_activity(cli_session, tmp_path, START + timedelta(days=i), ext=f"c{i}")
    # conftest already makes OpenMeteoClient.fetch_day return None (unreachable); make any sleep fail loudly
    monkeypatch.setattr("time.sleep", lambda s: pytest.fail("must not wait when the minute budget isn't the cause"))
    cli.cmd_backfill_gps(argparse.Namespace(weather=True, force=False))  # would hang before the fix
    out = capsys.readouterr().out
    assert "tracks:" in out and "routes:" in out
    assert "3 still pending" in out and "run again later" in out


def test_backfill_gps_without_weather_makes_no_weather_calls(cli_session, tmp_path, capsys):
    row_activity(cli_session, tmp_path, START, ext="x")
    cli.cmd_backfill_gps(argparse.Namespace(weather=False, force=False))
    assert "weather" not in capsys.readouterr().out


def test_backfill_gps_reports_done_when_everything_is_fetched(cli_session, tmp_path, capsys, monkeypatch):
    from catch.sync.weather_client import OpenMeteoClient
    from tests.test_weather_sync import FakeClient

    row_activity(cli_session, tmp_path, START, ext="y")
    fake = FakeClient()
    monkeypatch.setattr(OpenMeteoClient, "fetch_day", lambda self, a, b, c: fake.fetch_day(a, b, c))
    cli.cmd_backfill_gps(argparse.Namespace(weather=True, force=False))
    out = capsys.readouterr().out
    assert "'processed': 1" in out and "'ok': 1" in out and "pending" not in out
