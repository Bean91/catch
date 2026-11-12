from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, select

from catch.core.models import AthleteFact, CheckIn, DailyScore, Event, Goal
from catch.core.settings_store import get_settings

_KINDS = {"fact": AthleteFact, "event": Event, "goal": Goal}


def _parse_ref(ref: str) -> tuple[type, int]:
    kind, _, raw_id = ref.partition(":")
    model = _KINDS.get(kind)
    if model is None or not raw_id.isdigit():
        raise ValueError(f"Unknown memory reference '{ref}' — expected 'fact:<id>', 'event:<id>', or 'goal:<id>'")
    return model, int(raw_id)


def remember(
    session: Session,
    category: str,
    text: str,
    valid_until: date | None = None,
    source_conversation: int | None = None,
) -> AthleteFact:
    allowed = {"injury", "schedule", "equipment", "preference", "other"}
    if category not in allowed:
        raise ValueError(f"category must be one of {sorted(allowed)}")
    fact = AthleteFact(category=category, text=text, valid_until=valid_until, source_conversation=source_conversation)
    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact


def add_event(session: Session, name: str, date_: date, type: str, **fields: Any) -> Event:
    """Kept as the one Memory-page/REST entry point; the rules live in catch.sync.planning so
    there is a single validation path (the coach tools go through the same service)."""
    from catch.sync import planning

    try:
        return planning.create_event(session, planning.OWNER_ID, {"name": name, "date": date_, "type": type, **fields})
    except planning.PlanningError as exc:
        raise ValueError(str(exc)) from exc


def update_event(session: Session, event_id: int, **fields: Any) -> Event:
    from catch.sync import planning

    try:
        return planning.update_event(session, planning.OWNER_ID, event_id, fields)
    except planning.PlanningError as exc:
        raise ValueError(str(exc)) from exc


def set_goal(
    session: Session,
    text: str,
    target_date: date | None = None,
    status: str = "active",
    goal_id: int | None = None,
) -> Goal:
    allowed = {"active", "done", "abandoned"}
    if status not in allowed:
        raise ValueError(f"status must be one of {sorted(allowed)}")
    if goal_id is not None:
        goal = session.get(Goal, goal_id)
        if goal is None:
            raise ValueError(f"No goal with id {goal_id}")
        goal.text, goal.target_date, goal.status = text, target_date, status
    else:
        goal = Goal(text=text, target_date=target_date, status=status)
        session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


def forget(session: Session, ref: str) -> bool:
    model, row_id = _parse_ref(ref)
    if model is Event:
        from catch.sync import planning

        try:
            planning.delete_event(session, planning.OWNER_ID, row_id)
        except planning.NotFound:
            return False
        return True
    row = session.get(model, row_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def _fact_dict(f: AthleteFact) -> dict:
    return {
        "ref": f"fact:{f.id}",
        "kind": "fact",
        "category": f.category,
        "text": f.text,
        "valid_until": f.valid_until,
        "created_at": f.created_at,
    }


def _event_dict(e: Event, today: date) -> dict:
    return {
        "id": e.id,
        "ref": f"event:{e.id}",
        "kind": "event",
        "name": e.name,
        "date": e.date,
        "type": e.type,
        "distance": e.distance,
        "boat_class": e.boat_class,
        "priority": e.priority,
        "goal_time": e.goal_time,
        "result": e.result,
        "location": e.location,
        "goals": e.goals,
        "notes": e.notes,
        "distance_m": e.distance_m,
        "days_to_go": (e.date - today).days,
    }


def _goal_dict(g: Goal) -> dict:
    return {"ref": f"goal:{g.id}", "kind": "goal", "text": g.text, "target_date": g.target_date, "status": g.status}


def recall(session: Session, query: str | None = None) -> list[dict]:
    """Expired facts (valid_until in the past) are filtered here, at read time, rather than
    deleted — so a fact that turns out to matter again isn't gone, just no longer surfaced."""
    today = date.today()
    needle = (query or "").strip().lower()

    facts = session.exec(select(AthleteFact)).all()
    facts = [f for f in facts if f.valid_until is None or f.valid_until >= today]
    events = session.exec(select(Event)).all()
    goals = session.exec(select(Goal)).all()

    out: list[dict] = []
    for f in facts:
        if not needle or needle in f.text.lower() or needle in f.category.lower():
            out.append(_fact_dict(f))
    for e in events:
        haystack = " ".join(str(v) for v in (e.name, e.type, e.boat_class, e.distance) if v).lower()
        if not needle or needle in haystack:
            out.append(_event_dict(e, today))
    for g in goals:
        if not needle or needle in g.text.lower():
            out.append(_goal_dict(g))
    return out


def update_fact(session: Session, fact_id: int, **fields: Any) -> AthleteFact:
    fact = session.get(AthleteFact, fact_id)
    if fact is None:
        raise ValueError(f"No fact with id {fact_id}")
    unknown = set(fields) - {"category", "text", "valid_until"}
    if unknown:
        raise ValueError(f"Unknown fact field(s): {sorted(unknown)}")
    for key, value in fields.items():
        setattr(fact, key, value)
    session.commit()
    session.refresh(fact)
    return fact


def list_all(session: Session) -> dict:
    """Unfiltered listing for the Memory settings page — unlike recall(), this includes
    expired facts (flagged, not hidden) so the athlete can see what dropped out and why."""
    today = date.today()
    facts = session.exec(select(AthleteFact)).all()
    events = session.exec(select(Event)).all()
    goals = session.exec(select(Goal)).all()
    return {
        "facts": [{**_fact_dict(f), "expired": f.valid_until is not None and f.valid_until < today} for f in facts],
        "events": [_event_dict(e, today) for e in events],
        "goals": [_goal_dict(g) for g in goals],
    }


def next_a_race(session: Session, today: date | None = None) -> dict | None:
    today = today or date.today()
    stmt = select(Event).where(Event.type == "race", Event.priority == "A", Event.date >= today).order_by(Event.date)
    row = session.exec(stmt).first()
    if row is None:
        return None
    days_to_go = (row.date - today).days
    return {
        "id": row.id,
        "name": row.name,
        "date": row.date,
        "days_to_go": days_to_go,
        "taper": 0 <= days_to_go <= 14,
    }


def memory_block(session: Session) -> str:
    """A compact, deterministic summary injected into the system prompt on every chat — kept
    short on purpose (it's uncached, see catch/coach/chat.py) so a long memory list doesn't
    balloon the per-turn token cost that caching the rest of the prompt was meant to avoid."""
    today = date.today()
    events = session.exec(select(Event).where(Event.date >= today).order_by(Event.date)).all()
    goals = session.exec(select(Goal).where(Goal.status == "active")).all()
    facts = session.exec(select(AthleteFact)).all()
    facts = [f for f in facts if f.valid_until is None or f.valid_until >= today]

    lines = ["## Athlete memory"]
    if events:
        lines.append("Upcoming events:")
        for e in events:
            days = (e.date - today).days
            bits = [e.name, e.date.isoformat(), e.type]
            if e.priority:
                bits.append(f"priority {e.priority}")
            if e.goal_time:
                bits.append(f"goal {e.goal_time}")
            lines.append(f"- {' / '.join(bits)} ({days} days to go)")
    else:
        lines.append("Upcoming events: none recorded.")

    if goals:
        lines.append("Active goals:")
        for g in goals:
            target = f" (by {g.target_date.isoformat()})" if g.target_date else ""
            lines.append(f"- {g.text}{target}")
    else:
        lines.append("Active goals: none recorded.")

    if facts:
        lines.append("Current facts:")
        for f in facts:
            lines.append(f"- [{f.category}] {f.text}")
    else:
        lines.append("Current facts: none recorded.")

    # Session 15 (see PLAN.md Parts A/B): put directly in the uncached block, not behind a
    # tool call, so the coach always has today's check-in/illness state without having to
    # think to call get_today first — the system prompt still tells it to call get_today for
    # the numbers behind recovery/strain, this is just the always-visible headline.
    settings = get_settings(session)
    today_checkin = session.get(CheckIn, today)
    if today_checkin is not None:
        bits = [f"soreness {today_checkin.soreness}/5" if today_checkin.soreness else None]
        bits += [f"stress {today_checkin.stress}/5" if today_checkin.stress else None]
        bits += [f"mood {today_checkin.mood}/5" if today_checkin.mood else None]
        bits += [f"sleep quality {today_checkin.sleep_quality}/5" if today_checkin.sleep_quality else None]
        lines.append(f"Today's check-in: {', '.join(b for b in bits if b) or 'logged, no sliders set'}.")
    else:
        lines.append("Today's check-in: not logged yet.")

    niggle_streak = 0
    day = today
    while True:
        row = session.get(CheckIn, day)
        if row is None or not row.niggle_area:
            break
        niggle_streak += 1
        day -= timedelta(days=1)
    if niggle_streak >= settings["niggle_flag_min_days"]:
        area = today_checkin.niggle_area if today_checkin else None
        lines.append(f"Niggle flag: {area or 'a niggle'} has been logged for {niggle_streak} days running — ask about it.")

    score_row = session.get(DailyScore, today)
    illness = json.loads(score_row.illness_json) if score_row and score_row.illness_json else None
    if illness and illness["level"] != "none":
        lines.append(f"Illness early-warning: {illness['level']} — {illness['explanation']}")

    # Session 18 (see PLAN.md) — same unprompted-surfacing shape as the illness block above:
    # at most the single most severe *active* (not dismissed, confirmed as recently as
    # yesterday — see catch.sync.training_intelligence.is_active) recommendation, never a
    # stale one a later recompute has already stopped confirming.
    from catch.sync.training_intelligence import list_recommendations

    active = list_recommendations(session, status="active")
    if active:
        _SEVERITY = {"overload_warning": 0, "recovery_suggestion": 1, "plan_review": 2, "data_quality_warning": 3, "training_suggestion": 4}
        top = min(active, key=lambda r: _SEVERITY.get(r["type"], 99))
        lines.append(f"Active recommendation ({top['type']}, {top['confidence']} confidence): {top['body']}")

    return "\n".join(lines)
