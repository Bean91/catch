from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from catch.analytics import planning as pl

SYDNEY = ZoneInfo("Australia/Sydney")
NY = ZoneInfo("America/New_York")


# --- time zones ------------------------------------------------------------------------------


def test_local_date_same_instant_is_different_days_in_different_zones():
    # 23:30 on Mar 3 in New York is 04:30 Mar 4 UTC and 15:30 Mar 4 in Sydney.
    instant = datetime(2026, 3, 4, 4, 30, tzinfo=timezone.utc)
    assert pl.local_date(instant, NY) == date(2026, 3, 3)
    assert pl.local_date(instant, timezone.utc) == date(2026, 3, 4)
    assert pl.local_date(instant, SYDNEY) == date(2026, 3, 4)


def test_local_date_reads_a_naive_datetime_as_utc():
    naive = datetime(2026, 3, 4, 4, 30)
    assert pl.local_date(naive, NY) == date(2026, 3, 3)


def test_today_in_differs_across_the_date_line():
    now = datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)
    assert pl.today_in(NY, now) == date(2026, 6, 1)
    assert pl.today_in(SYDNEY, now) == date(2026, 6, 2)


def test_local_day_utc_range_is_dst_safe():
    # US spring-forward: Mar 8 2026 is a 23-hour local day.
    start, end = pl.local_day_utc_range(date(2026, 3, 8), NY)
    assert (end - start).total_seconds() == 23 * 3600
    # Fall-back: Nov 1 2026 is 25 hours.
    start, end = pl.local_day_utc_range(date(2026, 11, 1), NY)
    assert (end - start).total_seconds() == 25 * 3600


def test_event_countdown_uses_local_today_not_utc():
    race = date(2026, 6, 10)
    now = datetime(2026, 6, 2, 3, 0, tzinfo=timezone.utc)  # still Jun 1 evening in New York
    assert pl.days_to_go(race, pl.today_in(NY, now)) == 9
    assert pl.days_to_go(race, pl.today_in(SYDNEY, now)) == 8


def test_week_start_is_monday():
    assert pl.week_start(date(2026, 11, 11)) == date(2026, 11, 9)  # Wednesday
    assert pl.week_start(date(2026, 11, 15)) == date(2026, 11, 9)  # Sunday
    assert pl.week_start(date(2026, 11, 9)) == date(2026, 11, 9)


# --- recurrence ------------------------------------------------------------------------------


def test_weekly_repeat_default_weekday_is_the_anchor():
    out = pl.expand_repeat(date(2026, 11, 11), {"count": 3})
    assert out == [date(2026, 11, 11), date(2026, 11, 18), date(2026, 11, 25)]


def test_repeat_multiple_weekdays_until_inclusive():
    out = pl.expand_repeat(date(2026, 11, 9), {"weekdays": [0, 2, 4], "until": date(2026, 11, 20)})
    assert out == [date(2026, 11, 9), date(2026, 11, 11), date(2026, 11, 13), date(2026, 11, 16), date(2026, 11, 18), date(2026, 11, 20)]


def test_repeat_skips_weekdays_before_the_anchor_in_the_first_week():
    out = pl.expand_repeat(date(2026, 11, 11), {"weekdays": [0, 2, 4], "count": 3})
    assert out == [date(2026, 11, 11), date(2026, 11, 13), date(2026, 11, 16)]


def test_repeat_across_dst_change_keeps_the_same_weekday():
    # The US clocks go back on Nov 1; every generated date must still be a Tuesday.
    out = pl.expand_repeat(date(2026, 10, 27), {"count": 4})
    assert out == [date(2026, 10, 27), date(2026, 11, 3), date(2026, 11, 10), date(2026, 11, 17)]
    assert {d.weekday() for d in out} == {1}


def test_repeat_every_other_week():
    out = pl.expand_repeat(date(2026, 11, 9), {"interval_weeks": 2, "count": 3})
    assert out == [date(2026, 11, 9), date(2026, 11, 23), date(2026, 12, 7)]


def test_repeat_without_end_or_count_is_rejected():
    with pytest.raises(ValueError):
        pl.expand_repeat(date(2026, 11, 9), {"weekdays": [0]})


def test_repeat_caps_span_and_row_count():
    with pytest.raises(ValueError, match="26 weeks"):
        pl.expand_repeat(date(2026, 1, 5), {"until": date(2027, 1, 5)})
    with pytest.raises(ValueError):
        pl.expand_repeat(date(2026, 1, 5), {"count": 60})
    daily = pl.expand_repeat(date(2026, 1, 5), {"weekdays": [0, 1, 2, 3, 4, 5, 6], "until": date(2026, 7, 5)})
    assert len(daily) <= pl.MAX_REPEAT_ROWS


def test_no_repeat_is_a_single_date():
    assert pl.expand_repeat(date(2026, 11, 9), None) == [date(2026, 11, 9)]


# --- structure / validation ------------------------------------------------------------------


def test_validate_structure_cleans_and_totals():
    blocks = pl.validate_structure([{"reps": 4, "work_min": 5, "rest_min": 2, "zone": "AT"}, {"reps": 1, "work_min": 10, "zone": "UT2"}])
    assert pl.structure_minutes(blocks) == 38.0
    assert blocks[0]["zone"] == "AT"


@pytest.mark.parametrize(
    "bad",
    [
        "x",
        [{"reps": 0, "work_min": 5}],
        [{"reps": 2}],
        [{"reps": 2, "work_min": -1}],
        [{"reps": 2, "work_min": 5, "zone": "Z9"}],
        [1],
    ],
)
def test_validate_structure_rejects_bad_blocks(bad):
    with pytest.raises(ValueError):
        pl.validate_structure(bad)


def test_distance_only_structure_has_no_invented_duration():
    assert pl.structure_minutes(pl.validate_structure([{"reps": 8, "work_m": 500}])) is None


def test_validate_planned_fields():
    pl.validate_planned_fields({"session_type": "erg", "target_zone": "UT2", "start_time": "06:30", "duration_min": 60})
    for bad in ({"session_type": "swim"}, {"target_zone": "Z2"}, {"start_time": "6.30"}, {"duration_min": -5}, {"status": "missed"}):
        with pytest.raises(ValueError):
            pl.validate_planned_fields(bad)


def test_validate_phase_fields():
    pl.validate_phase_fields({"kind": "general_prep", "start_date": date(2026, 1, 1), "end_date": date(2026, 2, 1), "target_zone_pct": {"UT2": {"min": 70}}})
    for bad in (
        {"kind": "peak"},
        {"start_date": date(2026, 2, 1), "end_date": date(2026, 1, 1)},
        {"target_zone_pct": {"UT2": {"avg": 3}}},
        {"target_zone_pct": {"UT2": {"min": 120}}},
        {"target_minutes_per_week": -1},
    ):
        with pytest.raises(ValueError):
            pl.validate_phase_fields(bad)


# --- matching --------------------------------------------------------------------------------


def _planned(id, day, session_type="erg", duration=60, **kw):
    return {"id": id, "date": day, "session_type": session_type, "duration_min": duration, "distance_m": None, **kw}


def _act(id, day, family="rowing", category="erg", duration=62, distance=None):
    return {"id": id, "local_date": day, "sport_family": family, "category": category, "duration_min": duration, "distance_m": distance}


def test_same_day_same_sport_similar_duration_matches():
    m = pl.match_score(_planned(1, date(2026, 11, 9)), _act(10, date(2026, 11, 9)))
    assert m and m["score"] >= 0.9 and "same day" in m["reasons"]


def test_wrong_sport_two_days_away_and_rest_days_never_match():
    assert pl.match_score(_planned(1, date(2026, 11, 9), "run"), _act(10, date(2026, 11, 9))) is None
    assert pl.match_score(_planned(1, date(2026, 11, 9)), _act(10, date(2026, 11, 11))) is None
    assert pl.match_score(_planned(1, date(2026, 11, 9), "rest", None), _act(10, date(2026, 11, 9))) is None


def test_adjacent_day_is_a_weaker_but_possible_match():
    same = pl.match_score(_planned(1, date(2026, 11, 9)), _act(10, date(2026, 11, 9)))
    adj = pl.match_score(_planned(1, date(2026, 11, 9)), _act(10, date(2026, 11, 10)))
    assert adj and adj["score"] < same["score"]


def test_erg_plan_vs_on_water_workout_is_penalised_below_threshold_when_duration_off():
    m = pl.match_score(_planned(1, date(2026, 11, 9), "erg", 60), _act(10, date(2026, 11, 10), category="on_water", duration=200))
    assert m is None


def test_a_double_day_gets_one_workout_per_slot():
    day = date(2026, 11, 9)
    planned = [_planned(1, day, duration=60), _planned(2, day, duration=30)]
    acts = [_act(10, day, duration=31), _act(11, day, duration=61)]
    out = {m["planned_id"]: m["canonical_id"] for m in pl.suggest_matches(planned, acts)}
    assert out == {1: 11, 2: 10}


def test_one_workout_is_never_suggested_for_two_sessions():
    day = date(2026, 11, 9)
    out = pl.suggest_matches([_planned(1, day), _planned(2, day)], [_act(10, day)])
    assert len(out) == 1


def test_declined_pairs_are_not_re_offered():
    day = date(2026, 11, 9)
    assert pl.suggest_matches([_planned(1, day)], [_act(10, day)], declined={(1, 10)}) == []


# --- totals / zones / targets ----------------------------------------------------------------


def test_planned_totals_ignore_rest_and_separate_skipped():
    rows = [
        {"session_type": "erg", "duration_min": 60, "distance_m": 14000, "target_zone": "UT2", "status": "planned"},
        {"session_type": "strength", "duration_min": 45, "status": "planned"},
        {"session_type": "rest", "duration_min": 99, "status": "planned"},
        {"session_type": "bike", "duration_min": 90, "status": "skipped"},
        {"session_type": "erg", "structure": [{"reps": 4, "work_min": 5, "rest_min": 2, "zone": "AT"}], "status": "planned"},
    ]
    t = pl.planned_totals(rows)
    assert t["minutes"] == 60 + 45 + 28
    assert t["sessions"] == 3 and t["strength_sessions"] == 1 and t["skipped_sessions"] == 1
    assert t["zone_minutes"]["UT2"] == 60 and t["zone_minutes"]["AT"] == 20


def test_zone_pct_and_empty():
    assert pl.zone_pct({"UT2": 0, "UT1": 0, "AT": 0, "TR": 0, "AN": 0}) == {}
    pct = pl.zone_pct({"UT2": 75, "UT1": 0, "AT": 25, "TR": 0, "AN": 0})
    assert pct["UT2"] == 75.0 and pct["AT"] == 25.0


def test_phase_lookup_and_overlap():
    phases = [
        {"id": 1, "start_date": date(2026, 1, 1), "end_date": date(2026, 1, 31)},
        {"id": 2, "start_date": date(2026, 2, 1), "end_date": date(2026, 2, 28)},
    ]
    assert pl.phase_for_date(phases, date(2026, 1, 31))["id"] == 1
    assert pl.phase_for_date(phases, date(2026, 3, 1)) is None
    assert pl.overlapping_phase(phases, date(2026, 1, 20), date(2026, 2, 2))["id"] == 1
    assert pl.overlapping_phase(phases, date(2026, 3, 1), date(2026, 3, 10)) is None
    assert pl.overlapping_phase(phases, date(2026, 1, 1), date(2026, 1, 31), ignore_id=1) is None


def test_compare_week_to_targets_is_descriptive():
    planned = {"minutes": 300, "sessions": 5, "strength_sessions": 2}
    rows = pl.compare_week_to_targets(
        planned,
        {"minutes": 200, "sessions": 3, "strength_sessions": 1},
        {"minutes": 320, "sessions": 5, "strength_sessions": 2, "zone_pct": {"UT2": {"min": 70}, "AN": {"max": 5}}},
        {"UT2": 65.0, "AN": 3.0},
    )
    zones = rows[-1]["zones"]
    assert {z["zone"]: z["within"] for z in zones} == {"UT2": False, "AN": True}
    assert not any("verdict" in r or "behind" in str(r) for r in rows)


# --- review flags ----------------------------------------------------------------------------


def _wk(day, planned, base=None, kind=None, approved=False):
    return {"week_start": day, "planned_minutes": planned, "completed_baseline_minutes": base, "phase_kind": kind, "phase_approved": approved}


def test_large_increase_vs_completed_baseline_is_flagged_with_hedged_wording():
    flags = pl.workload_change_flags([_wk(date(2026, 11, 9), 500, base=300)], 25, confidence="medium")
    assert len(flags) == 1 and flags[0]["kind"] == "increase"
    assert flags[0]["message"].startswith("Based on the data so far (not certain): ")
    assert "nothing has been changed" in flags[0]["message"]


def test_modest_change_and_small_absolute_change_are_not_flagged():
    assert pl.workload_change_flags([_wk(date(2026, 11, 9), 330, base=300)], 25) == []
    assert pl.workload_change_flags([_wk(date(2026, 11, 9), 80, base=50)], 25) == []


def test_uses_the_larger_reference():
    weeks = [_wk(date(2026, 11, 2), 400, base=200), _wk(date(2026, 11, 9), 430, base=200)]
    flags = pl.workload_change_flags(weeks, 25)
    assert [f["week_start"] for f in flags] == [date(2026, 11, 2)]


def test_approved_phase_defers_to_the_coach_and_is_not_hedged():
    flags = pl.workload_change_flags([_wk(date(2026, 11, 9), 500, base=300, approved=True)], 25, confidence="low")
    msg = flags[0]["message"]
    assert "coach-approved" in msg and "confirming with your coach" in msg
    assert not msg.startswith("Based on the data")


def test_drops_are_flagged_only_outside_recovery_style_phases():
    assert pl.workload_change_flags([_wk(date(2026, 11, 9), 150, base=400, kind="recovery")], 25) == []
    flags = pl.workload_change_flags([_wk(date(2026, 11, 9), 150, base=400, kind="general_prep")], 25)
    assert flags and flags[0]["kind"] == "drop"


def test_no_banned_or_shaming_language_in_flag_messages():
    for approved in (True, False):
        msg = pl.workload_change_flags([_wk(date(2026, 11, 9), 500, base=300, approved=approved)], 25)[0]["message"].lower()
        for word in ("missed", "behind", "lazy", "failed", "push through", "definitely", "guaranteed"):
            assert word not in msg
