"""Launch audit L-36: the weather cache refreshes a provisional cell-day in place, so the runtime role needs UPDATE on it."""

from __future__ import annotations

from sqlalchemy import text

from tests.pg.conftest import signup
from tests.pg.test_rls import as_user


def test_a_user_request_can_refresh_a_provisional_weather_cell(runtime, clean):
    u = signup("wx")
    with as_user(runtime, u.id) as conn:
        conn.execute(text("INSERT INTO weather_cells (provider, lat_e1, lon_e1, utc_date, hourly_json, complete, fetched_at)"
                          " VALUES ('open-meteo', 515, -1, '2026-11-01', '{}', false, now())"))
        n = conn.execute(text("UPDATE weather_cells SET complete = true, hourly_json = '{\"1\": {}}' WHERE lat_e1 = 515 AND lon_e1 = -1")).rowcount
        assert n == 1
        # A finished cell-day can't be rewritten by a user request (the policy only matches complete = false).
        assert conn.execute(text("UPDATE weather_cells SET hourly_json = '{}' WHERE lat_e1 = 515 AND lon_e1 = -1")).rowcount == 0


def test_a_user_still_cannot_delete_weather_cells(runtime, clean):
    import pytest
    from sqlalchemy.exc import ProgrammingError

    u = signup("wx2")
    with as_user(runtime, u.id) as conn, pytest.raises(ProgrammingError):
        conn.execute(text("DELETE FROM weather_cells"))
