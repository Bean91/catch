from __future__ import annotations

from datetime import datetime, timedelta, timezone

from catch.analytics.matching import (
    MatchInput,
    category_for_canonical,
    is_indoor,
    match_pair,
    sport_family,
)

T0 = datetime(2026, 1, 1, 7, 0, 0, tzinfo=timezone.utc)


def _mi(source, type_, start, duration_s, *, offset_s=0):
    return MatchInput(
        source=source,
        external_id="x",
        sport_family=sport_family(source, type_),
        indoor=is_indoor(source, type_),
        start=start + timedelta(seconds=offset_s),
        duration=duration_s,
    )


def test_sport_family_covers_garmin_and_concept2_types():
    assert sport_family("garmin", "indoor_rowing") == "rowing"
    assert sport_family("garmin", "rowing_v2") == "rowing"
    assert sport_family("garmin", "indoor_cycling") == "cycling"
    assert sport_family("garmin", "strength_training") == "strength"
    assert sport_family("garmin", "unknown_type") == "other"
    assert sport_family("concept2", "rower") == "rowing"
    assert sport_family("concept2", "bike") == "cycling"
    assert sport_family("concept2", "water") == "rowing"


def test_is_indoor():
    assert is_indoor("garmin", "indoor_cycling") is True
    assert is_indoor("garmin", "cycling") is False
    assert is_indoor("concept2", "rower") is True
    assert is_indoor("concept2", "water") is False
    assert is_indoor("garmin", "unknown") is None


def test_category_for_canonical():
    assert category_for_canonical("rowing", True) == "erg"
    assert category_for_canonical("rowing", False) == "on_water"
    assert category_for_canonical("cycling", True) == "other"


def test_watch_and_peloton_pushed_same_ride_auto_merges():
    """Part A.2/B: a Peloton-pushed Garmin activity and the watch's own recording of the same
    ride — same source (garmin), different external_id, same sport family, start within the
    3-minute window, near-identical duration."""
    watch = _mi("garmin", "indoor_cycling", T0, 2700.0)
    peloton = _mi("garmin", "indoor_cycling", T0, 2700.0, offset_s=20)
    result = match_pair(watch, peloton)
    assert result.is_candidate
    assert result.auto_merge
    assert not result.hard_block


def test_back_to_back_separate_rides_never_merge():
    """Two genuinely separate sessions just outside the matching window never merge, even
    with identical duration."""
    first = _mi("garmin", "indoor_rowing", T0, 1800.0)
    second = _mi("garmin", "indoor_rowing", T0, 1800.0, offset_s=1800 + 600)  # starts after first ends + 10 min gap
    result = match_pair(first, second)
    assert not result.is_candidate
    assert not result.auto_merge


def test_concept2_and_garmin_same_rowing_session_matches():
    c2 = _mi("concept2", "rower", T0, 1800.0)
    garmin = _mi("garmin", "indoor_rowing", T0, 1800.0, offset_s=30)
    result = match_pair(c2, garmin)
    assert result.auto_merge


def test_indoor_vs_outdoor_never_auto_merges_even_with_a_perfect_time_match():
    indoor = _mi("garmin", "indoor_cycling", T0, 1800.0)
    outdoor = _mi("garmin", "cycling", T0, 1800.0)
    result = match_pair(indoor, outdoor)
    assert result.hard_block
    assert not result.auto_merge


def test_different_sport_family_is_not_even_a_candidate():
    rowing = _mi("garmin", "indoor_rowing", T0, 1800.0)
    cycling = _mi("garmin", "indoor_cycling", T0, 1800.0)
    result = match_pair(rowing, cycling)
    assert not result.is_candidate
    assert result.score == 0.0


def test_duration_ratio_outside_range_is_not_a_candidate():
    short = _mi("garmin", "indoor_rowing", T0, 1200.0)
    long = _mi("garmin", "indoor_rowing", T0, 1200.0 * 1.3, offset_s=10)  # ratio ~0.77, below 0.8
    result = match_pair(short, long)
    assert not result.is_candidate


def test_overlap_based_match_without_close_start_times():
    """Two long sessions that start more than 3 minutes apart can still match via >=70%
    overlap of the shorter one."""
    a = _mi("garmin", "indoor_rowing", T0, 3600.0)
    b = _mi("garmin", "indoor_rowing", T0, 3600.0, offset_s=300)  # 5 min late, but 55/60 min overlap
    result = match_pair(a, b)
    assert result.is_candidate
    assert result.auto_merge


def test_other_family_never_auto_matches_even_if_identical():
    a = _mi("garmin", "paddle_boarding_made_up", T0, 1800.0)
    b = _mi("garmin", "paddle_boarding_made_up", T0, 1800.0, offset_s=5)
    result = match_pair(a, b)
    assert not result.is_candidate


# -- session 14 (see PLAN.md Part B.1): catch_strength <-> Garmin strength_training ----------


def test_catch_strength_sport_family_and_indoor():
    assert sport_family("catch_strength", "catch_strength") == "strength"
    assert is_indoor("catch_strength", "catch_strength") is True


def test_catch_strength_merges_with_garmin_strength_training_on_overlap_alone():
    """Catch's own window is padded 10min before/5min after the logged sets
    (catch/sync/gym.py) — far outside the generic rule's 3-minute-start window — but still
    merges, since the strength match rule only requires time overlap."""
    garmin = _mi("garmin", "strength_training", T0, 2400.0)  # 40 real minutes on the watch.
    # Catch's padded window: starts 9 min before the watch did, runs 20 min longer.
    catch = _mi("catch_strength", "catch_strength", T0, 2400.0 + 15 * 60, offset_s=-9 * 60)
    result = match_pair(garmin, catch)
    assert result.is_candidate
    assert result.auto_merge
    assert not result.hard_block


def test_catch_strength_no_overlap_is_not_a_candidate():
    garmin = _mi("garmin", "strength_training", T0, 1800.0)
    catch = _mi("catch_strength", "catch_strength", T0, 1800.0, offset_s=3600)  # a different day's lift.
    result = match_pair(garmin, catch)
    assert not result.is_candidate


def test_catch_strength_never_matches_a_different_sport_family():
    garmin_cardio = _mi("garmin", "indoor_cycling", T0, 1800.0)
    catch = _mi("catch_strength", "catch_strength", T0, 1800.0)
    result = match_pair(garmin_cardio, catch)
    assert not result.is_candidate
