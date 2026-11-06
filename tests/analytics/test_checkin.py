from __future__ import annotations

import pytest

from catch.analytics.checkin import checkin_badness, checkin_recovery_score


def test_best_case_sliders_score_100():
    assert checkin_recovery_score(soreness=1, stress=1, mood=5, sleep_quality=5) == pytest.approx(100.0)


def test_worst_case_sliders_score_0():
    assert checkin_recovery_score(soreness=5, stress=5, mood=1, sleep_quality=1) == pytest.approx(0.0)


def test_partial_sliders_average_only_what_was_answered():
    assert checkin_recovery_score(soreness=None, stress=None, mood=5, sleep_quality=None) == pytest.approx(100.0)


def test_none_when_nothing_was_answered():
    assert checkin_recovery_score(None, None, None, None) is None


def test_badness_is_high_for_sore_and_low_mood():
    assert checkin_badness(soreness=5, mood=1) == pytest.approx(100.0)


def test_badness_is_low_for_fresh_and_good_mood():
    assert checkin_badness(soreness=1, mood=5) == pytest.approx(0.0)


def test_badness_none_when_neither_answered():
    assert checkin_badness(None, None) is None
