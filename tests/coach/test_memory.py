from __future__ import annotations

from datetime import date, timedelta

from catch.coach import memory


def test_remember_and_recall_filters_expired_facts(session):
    today = date.today()
    memory.remember(session, "preference", "prefers short warmups")
    memory.remember(session, "schedule", "traveling next week", valid_until=today - timedelta(days=1))

    results = memory.recall(session)
    texts = [r["text"] for r in results]
    assert "prefers short warmups" in texts
    assert "traveling next week" not in texts

    # list_all shows it anyway, flagged expired — nothing is actually deleted.
    everything = memory.list_all(session)
    expired = [f for f in everything["facts"] if f["text"] == "traveling next week"]
    assert expired and expired[0]["expired"] is True


def test_remember_rejects_unknown_category(session):
    try:
        memory.remember(session, "nonsense", "x")
        assert False, "should have raised"
    except ValueError:
        pass


def test_add_event_and_next_a_race(session):
    today = date.today()
    memory.add_event(session, "Club regatta", today + timedelta(days=30), "race", priority="B")
    a_race = memory.add_event(session, "Head of the Charles", today + timedelta(days=10), "race", priority="A")

    result = memory.next_a_race(session, today)
    assert result is not None
    assert result["name"] == "Head of the Charles"
    assert result["days_to_go"] == 10
    assert result["taper"] is True  # <=14 days out


def test_next_a_race_none_when_no_a_race(session):
    today = date.today()
    memory.add_event(session, "Club regatta", today + timedelta(days=5), "race", priority="B")
    assert memory.next_a_race(session, today) is None


def test_update_event_only_changes_passed_fields(session):
    event = memory.add_event(session, "2k test", date.today(), "2k_test")
    updated = memory.update_event(session, event.id, result="6:50")
    assert updated.result == "6:50"
    assert updated.name == "2k test"


def test_set_goal_create_then_update(session):
    goal = memory.set_goal(session, "Break 6:40 for 2k", target_date=date(2027, 1, 1))
    assert goal.status == "active"
    updated = memory.set_goal(session, "Break 6:40 for 2k", status="done", goal_id=goal.id)
    assert updated.id == goal.id
    assert updated.status == "done"


def test_forget_handles_unknown_ref_kind(session):
    try:
        memory.forget(session, "nope:1")
        assert False, "should have raised"
    except ValueError:
        pass


def test_forget_returns_false_for_missing_id(session):
    assert memory.forget(session, "fact:999") is False


def test_memory_block_lists_events_goals_facts(session):
    today = date.today()
    memory.add_event(session, "Head of the Charles", today + timedelta(days=5), "race", priority="A", goal_time="6:40")
    memory.set_goal(session, "Qualify for selection camp")
    memory.remember(session, "injury", "tight hamstring, easing back in")

    block = memory.memory_block(session)
    assert "Head of the Charles" in block
    assert "Qualify for selection camp" in block
    assert "tight hamstring" in block
    assert "days to go" in block


# --- Session 15 Parts A/B: check-in and illness in the uncached memory block ------------


def test_memory_block_says_not_logged_with_no_checkin(session):
    block = memory.memory_block(session)
    assert "check-in: not logged yet" in block


def test_memory_block_reports_todays_checkin(session):
    from catch.core.models import CheckIn

    session.add(CheckIn(date=date.today(), soreness=2, mood=4))
    session.commit()

    block = memory.memory_block(session)
    assert "soreness 2/5" in block
    assert "mood 4/5" in block


def test_memory_block_flags_a_niggle_past_the_min_days(session):
    from catch.core.models import CheckIn

    today = date.today()
    for i in range(3):
        session.add(CheckIn(date=today - timedelta(days=i), niggle_area="left knee", niggle_severity=1))
    session.commit()

    block = memory.memory_block(session)
    assert "Niggle flag" in block
    assert "left knee" in block


def test_memory_block_includes_illness_level_when_flagged(session):
    import json

    from catch.core.models import DailyScore

    session.add(DailyScore(date=date.today(), illness_json=json.dumps({"level": "watch", "explanation": "signs of strain"})))
    session.commit()

    block = memory.memory_block(session)
    assert "Illness early-warning: watch" in block
