from __future__ import annotations

import pytest

from catch.analytics.erg_math import pace_from_watts, w_per_kg, watts_from_pace


def test_watts_from_pace_matches_task_hand_checks():
    # From the session 2 task spec: a 1:45.0/500m split is about 302 W, 2:00.0 is about 202.5 W.
    assert watts_from_pace(105.0) == pytest.approx(302, abs=1)
    assert watts_from_pace(120.0) == pytest.approx(202.5, abs=0.5)


def test_pace_from_watts_is_the_inverse():
    pace = 105.0
    assert pace_from_watts(watts_from_pace(pace)) == pytest.approx(pace)


def test_pace_from_watts_matches_task_hand_check():
    assert pace_from_watts(202.5) == pytest.approx(120.0, abs=0.1)


def test_w_per_kg():
    assert w_per_kg(300.0, 75.0) == pytest.approx(4.0)
    assert w_per_kg(300.0, None) is None
    assert w_per_kg(None, 75.0) is None
    assert w_per_kg(300.0, 0) is None
