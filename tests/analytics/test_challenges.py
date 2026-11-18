"""catch/analytics/challenges.py — validation of unsafe configurations, scoring with caps, ties, excused weeks, ranking."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from catch.analytics import challenges as ch

START = date(2026, 11, 2)  # a Monday
END = date(2026, 11, 29)  # four full weeks
DONE = END + timedelta(days=1)  # the day after: every week has ended


def spec(**kw):
    base = dict(metric="distance", start=START, end=END, goal=100000)
    return ch.validate_challenge(**{**base, **kw})


def act(day: int, *, dist=10000.0, dur=3600.0, key=None, hour=7, **kw):
    d = START + timedelta(days=day)
    return {"key": key or f"a{day}-{hour}", "date": d, "start": datetime(d.year, d.month, d.day, hour), "duration_s": dur, "distance_m": dist,
            "sport_family": "rowing", "provider_sourced": True, **kw}


# ---------------------------------------------------------------- unsafe or unscoreable configurations are refused

@pytest.mark.parametrize("metric", ["distance", "time", "sessions"])
def test_a_volume_challenge_must_have_a_goal(metric):
    with pytest.raises(ValueError, match="set a goal"):
        spec(metric=metric, goal=None)
    with pytest.raises(ValueError, match="set a goal"):
        spec(metric=metric, goal=0)


@pytest.mark.parametrize("kw,message", [
    ({"metric": "distance", "goal": 700001}, "150 km a week"),          # 4 weeks x 150 km = 600 km is the most a goal may ask for
    ({"metric": "time", "goal": 12 * 3600 * 4 + 1}, "12 hours a week"),
    ({"metric": "sessions", "goal": 25}, "6 sessions a week"),
    ({"end": START + timedelta(days=3)}, "weeks"), ({"end": START + timedelta(days=100)}, "weeks"),
    ({"min_session_s": 600}, "15 minutes"), ({"day_cap_s": 20000, "metric": "time", "goal": 100000}, "hours a day"),
    ({"day_cap_m": 40000}, "km a day"), ({"metric": "tests", "goal": 9}, "1-7"), ({"metric": "nonsense"}, "distance, time"),
    ({"sport": "weightlifting"}, "rowing or any"),
])
def test_unsafe_limits_are_refused_with_what_to_change(kw, message):
    with pytest.raises(ValueError, match=message):
        spec(**kw)


def test_a_junior_challenge_has_tighter_ceilings():
    with pytest.raises(ValueError, match="junior"):
        spec(audience="junior", day_cap_s=10800, metric="time", goal=100000)
    with pytest.raises(ValueError, match="8 hours a week"):
        spec(audience="junior", metric="time", goal=9 * 3600 * 4)
    with pytest.raises(ValueError, match="100 km a week"):
        spec(audience="junior", metric="distance", goal=101000 * 4)
    assert spec(audience="junior", metric="time", goal=8 * 3600 * 4).audience == "junior"
    assert spec(audience="adult", metric="time", goal=9 * 3600 * 4).audience == "adult"


def test_a_challenge_cannot_start_in_the_past():
    with pytest.raises(ValueError, match="past"):
        spec(today=START + timedelta(days=1))
    assert spec(today=START)


def test_consistency_asks_for_one_to_five_sessions_a_week_never_more():
    for bad in (0, 6, 10):
        with pytest.raises(ValueError, match="more earns nothing"):
            spec(metric="consistency", goal=None, target_per_week=bad)
    assert spec(metric="consistency", goal=None).target_per_week == 3
    assert spec(metric="consistency", goal=None, target_per_week=5).goal == 4  # capped at the number of weeks


def test_the_metric_vocabulary_names_no_health_quantity():
    banned = ("weight", "calorie", "kcal", "bmi", "body", "fat", "recovery", "sleep", "hrv", "heart", "strain", "readiness", "illness")
    for word in (*ch.METRICS, *ch.SPORTS):
        assert not any(b in word for b in banned), word
    rules = " ".join(ch.describe(spec()))
    assert "Nothing about weight, calories, recovery or sleep is used" in rules


# ---------------------------------------------------------------- distance and time: caps, ceilings, goal

def test_distance_counts_up_to_the_goal_and_no_further():
    s = spec(goal=25000)
    result = ch.score(s, [act(0), act(1), act(2), act(3)], as_of=END)
    assert result.value == 25000 and result.detail["reached"] is True


def test_a_day_cap_stops_one_enormous_day_from_counting():
    s = spec(goal=500000, day_cap_m=20000)
    result = ch.score(s, [act(0, dist=15000, key="a"), act(0, dist=15000, key="b", hour=14), act(0, dist=15000, key="c", hour=18)], as_of=END)
    assert result.value == 20000  # 45 km in one day counts as the cap
    assert result.claimed_keys == ("a", "b")  # the third added nothing, so it isn't claimed


def test_a_week_ceiling_stops_farming_even_under_the_day_cap():
    s = spec(goal=600000)  # the most a four-week goal may ask for
    rows = [act(d, dist=30000, key=f"d{d}") for d in range(7)]  # 210 km in a week, each day at the cap
    assert ch.score(s, rows, as_of=END).value == ch.WEEK_CEILING_M["adult"]  # 150 km
    junior = spec(goal=400000, audience="junior", day_cap_m=20000)
    rows = [act(d, dist=20000, key=f"j{d}") for d in range(7)]
    assert ch.score(junior, rows, as_of=END).value == ch.WEEK_CEILING_M["junior"]  # 100 km


def test_time_trained_is_capped_per_day_and_week_and_needs_a_real_session():
    s = spec(metric="time", goal=12 * 3600 * 4, day_cap_s=7200)
    assert ch.score(s, [act(0, dur=5 * 3600)], as_of=END).value == 7200
    assert ch.score(s, [act(0, dur=600)], as_of=END).value == 0  # ten minutes isn't a session
    week = [act(d, dur=7200, key=f"t{d}") for d in range(7)]
    assert ch.score(s, week, as_of=END).value == ch.WEEK_CEILING_S["adult"]


def test_only_qualifying_activities_count():
    s = spec(goal=600000)
    rows = [
        act(0, key="ok"),
        act(1, key="excluded", excluded=True), act(2, key="absorbed", absorbed=True), act(3, key="typed", provider_sourced=False),
        act(4, key="run", sport_family="running"),
        {**act(5, key="early"), "date": START - timedelta(days=1)}, {**act(6, key="late"), "date": END + timedelta(days=1)},
    ]
    r = ch.score(s, rows, as_of=END)
    assert r.value == 10000 and r.claimed_keys == ("ok",)
    assert ch.score(spec(goal=600000, sport="any"), [act(4, key="run", sport_family="running")], as_of=END).value == 10000


def test_scoring_is_deterministic_whatever_order_the_activities_arrive_in():
    s = spec(goal=500000, day_cap_m=12000)
    rows = [act(0, dist=9000, key="a", hour=6), act(0, dist=9000, key="b", hour=12), act(1, dist=4000, key="c")]
    assert ch.score(s, rows, as_of=END) == ch.score(s, list(reversed(rows)), as_of=END)


def test_a_private_health_value_on_an_activity_row_changes_nothing_and_never_surfaces():
    s = spec(goal=500000)
    clean = ch.score(s, [act(0)], as_of=END)
    tainted = ch.score(s, [act(0, weight_kg=71.5, calories=900, hrv=12.3, sleep_h=4, recovery=17)], as_of=END)
    assert clean == tainted
    blob = json.dumps({"v": tainted.value, "d": tainted.detail, "k": tainted.claimed_keys}, default=str)
    for secret in ("71.5", "900", "12.3", "recovery"):
        assert secret not in blob


# ---------------------------------------------------------------- sessions, tests, consistency

def test_sessions_count_two_a_day_six_a_week_and_need_a_minimum_length():
    s = spec(metric="sessions", goal=20)
    day = [act(0, key=f"s{h}", hour=h) for h in (6, 12, 18)]
    assert ch.score(s, day, as_of=END).value == 2
    week = [act(d, key=f"w{d}{h}", hour=h) for d in range(7) for h in (6, 18)]  # 14 sessions in a week
    assert ch.score(s, week, as_of=END).value == 6
    assert ch.score(s, [act(0, dur=600)], as_of=END).value == 0
    assert ch.score(spec(metric="sessions", goal=2), [act(d) for d in range(5)], as_of=END).value == 2  # never above the goal


def test_erg_test_participation_counts_distinct_tests_not_speed():
    s = spec(metric="tests", goal=None)
    rows = [act(0, key="a", board_key="2000m", dur=420), act(1, key="b", board_key="2000m", dur=395), act(2, key="c", board_key="500m", dur=95),
            act(3, key="d", board_key=None)]
    r = ch.score(s, rows, as_of=END)
    assert r.value == 2 and r.detail["boards"] == ["2000m", "500m"]  # a faster 2k doesn't count twice; a 95 s test counts despite the minimum length
    assert ch.score(spec(metric="tests", goal=1), rows, as_of=END).value == 1
    slow, fast = ch.score(s, [act(0, board_key="2000m", dur=900)], as_of=END), ch.score(s, [act(0, board_key="2000m", dur=350)], as_of=END)
    assert slow.value == fast.value == 1


def test_consistency_counts_weeks_that_reach_the_target_and_never_rewards_more():
    s = spec(metric="consistency", goal=None, target_per_week=3)
    rows = [act(d, key=f"w1-{d}") for d in (0, 1, 2)] + [act(d, key=f"w2-{d}") for d in (7, 8)] + [act(d, key=f"w3-{d}") for d in range(14, 21)]
    r = ch.score(s, rows, as_of=DONE)
    assert r.detail["met"] == 2 and r.detail["eligible_weeks"] == 4 and r.value == 5000  # week 1 and 3; seven sessions in week 3 count once
    assert [w["state"] for w in r.detail["weeks"]] == ["met", "missed", "met", "missed"]


def test_an_excused_week_is_not_counted_against_you():
    s = spec(metric="consistency", goal=None, target_per_week=3)
    rows = [act(d, key=f"w1-{d}") for d in (0, 1, 2)]
    plain = ch.score(s, rows, as_of=DONE)
    excused = ch.score(s, rows, as_of=DONE, excused_weeks=[date(2026, 11, 9), date(2026, 11, 16), date(2026, 11, 25)])  # any day in a week excuses it
    assert plain.value == 2500 and excused.value == 10000  # 1 of 4 weeks vs 1 of 1 eligible
    assert [w["state"] for w in excused.detail["weeks"]] == ["met", "excused", "excused", "excused"]


def test_the_week_in_progress_neither_helps_nor_hurts_until_it_is_met_or_over():
    s = spec(metric="consistency", goal=None, target_per_week=3)
    rows = [act(d, key=f"a{d}") for d in (0, 1, 2)] + [act(7, key="b")]
    mid = ch.score(s, rows, as_of=date(2026, 11, 10))  # Tuesday of week 2
    assert mid.detail["met"] == 1 and mid.detail["eligible_weeks"] == 1 and mid.detail["weeks"][1]["state"] == "in_progress"
    done = ch.score(s, rows + [act(8, key="c"), act(9, key="d")], as_of=date(2026, 11, 10))
    assert done.detail["met"] == 2 and done.detail["eligible_weeks"] == 2


def test_nobody_is_ranked_on_a_streak():
    """There is no consecutive-day or never-miss metric: 3 sessions every week reaches the same score as 3 sessions Mon-Wed."""
    s = spec(metric="consistency", goal=None, target_per_week=3)
    spread = [act(w * 7 + d, key=f"s{w}{d}") for w in range(4) for d in (0, 2, 4)]
    packed = [act(w * 7 + d, key=f"p{w}{d}") for w in range(4) for d in (0, 1, 2)]
    assert ch.score(s, spread, as_of=DONE).value == ch.score(s, packed, as_of=DONE).value == 10000


# ---------------------------------------------------------------- phases, ranking, keys

@pytest.mark.parametrize("today,phase,joinable", [
    (START - timedelta(days=1), "upcoming", True), (START, "open", True), (END, "open", True),
    (END + timedelta(days=1), "grace", False), (END + timedelta(days=2), "grace", False), (END + timedelta(days=3), "closed", False),
])
def test_a_challenge_is_open_then_settles_then_freezes(today, phase, joinable):
    s = spec()
    assert ch.phase(s, today) == phase and ch.can_join(s, today) is joinable


def test_equal_scores_share_a_rank_and_the_next_rank_skips():
    rows = [{"owner_id": o, "value": v} for o, v in (("a", 50), ("b", 80), ("c", 80), ("d", 80), ("e", 10))]
    ranked = ch.rank_standings(rows, 7)
    assert [(r["value"], r["rank"]) for r in ranked] == [(80, 1), (80, 1), (80, 1), (50, 4), (10, 5)]


def test_the_order_inside_a_tie_depends_on_nothing_a_member_controls():
    rows = [{"owner_id": o, "value": 5} for o in "abcdef"]
    a, b = ch.rank_standings(rows, 3), ch.rank_standings(list(reversed(rows)), 3)
    assert [r["owner_id"] for r in a] == [r["owner_id"] for r in b]  # input order doesn't matter
    assert [r["owner_id"] for r in a] != [r["owner_id"] for r in ch.rank_standings(rows, 4)]  # and it varies by challenge, so nobody is always first
    assert {r["rank"] for r in a} == {1}


def test_an_activity_key_is_keyed_and_reveals_nothing_about_the_provider_id():
    k1, k2 = ch.activity_key("secret-1", "garmin", "123456"), ch.activity_key("secret-2", "garmin", "123456")
    assert k1 != k2 and len(k1) == 40 and "123456" not in k1
    assert k1 == ch.activity_key("secret-1", "garmin", "123456") and k1 != ch.activity_key("secret-1", "concept2", "123456")


def test_the_rules_are_written_in_plain_words_for_every_metric():
    for kw in ({"metric": "distance"}, {"metric": "time", "goal": 100000}, {"metric": "sessions", "goal": 10}, {"metric": "tests", "goal": None}, {"metric": "consistency", "goal": None}):
        text = " ".join(ch.describe(spec(**kw)))
        assert "Equal scores share a rank" in text and "recorded by a connected source" in text and "Joining is open until the end date" in text


def test_values_are_formatted_for_people():
    assert ch.format_value(spec(), 12500) == "12.5 km"
    assert ch.format_value(spec(metric="time", goal=100000), 5400) == "1h 30m"
    assert ch.format_value(spec(metric="sessions", goal=10), 1) == "1 session"
    assert ch.format_value(spec(metric="consistency", goal=None), 7500, {"met": 3, "eligible_weeks": 4}) == "3 of 4 weeks"
