from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.core.models import AiUsageEvent, CoachConversation, CoachMessage
from catch.core.principal import OWNER_ID

_RATE_KEYS = ("input", "output", "cache_write", "cache_read")
_USAGE_TO_RATE = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_creation_input_tokens": "cache_write",
    "cache_read_input_tokens": "cache_read",
}


def estimate_cost_usd(prices: dict | None, usage: dict) -> float | None:
    """prices: {"input": $/1M tok, "output": ..., "cache_write": ..., "cache_read": ...},
    user-entered in Settings — Ollama's `prices` is always {} (local, $0), which this
    correctly turns into a $0.0 cost rather than None (None means "no price configured",
    which is a different, UI-distinguishable state from "free")."""
    if prices is None:
        return None
    total = 0.0
    for usage_key, rate_key in _USAGE_TO_RATE.items():
        tokens = usage.get(usage_key) or 0
        total += tokens * (prices.get(rate_key) or 0)
    return total / 1_000_000


def _local_day_utc_range(day: date) -> tuple[datetime, datetime]:
    # Matches catch/sync/scoring.py's day convention: a naive datetime's .astimezone() is
    # defined to assume the system's own local timezone.
    local_midnight = datetime(day.year, day.month, day.day)
    start_utc = local_midnight.astimezone(timezone.utc)
    end_utc = (local_midnight + timedelta(days=1)).astimezone(timezone.utc)
    return start_utc, end_utc


def _todays_rows(session: Session, owner_id: str, today: date | None):
    start, end = _local_day_utc_range(today or date.today())
    coach_rows = session.exec(
        select(CoachMessage.cost_usd, CoachMessage.usage_json)
        .join(CoachConversation, CoachConversation.id == CoachMessage.conversation_id)
        .where(CoachConversation.owner_id == owner_id, CoachMessage.created_at >= start, CoachMessage.created_at < end)
    ).all()
    other_rows = session.exec(
        select(AiUsageEvent.cost_usd, AiUsageEvent.usage_json).where(
            AiUsageEvent.owner_id == owner_id, AiUsageEvent.created_at >= start, AiUsageEvent.created_at < end
        )
    ).all()
    return [*coach_rows, *other_rows]


def today_spend_usd(session: Session, today: date | None = None, owner_id: str = OWNER_ID) -> float:
    """Session 13 (see PLAN.md Part B): also sums `AiUsageEvent` — AI spend outside the coach chat
    loop (the photo-estimate calls) — so the daily cap covers every AI call this app makes, not just
    conversation turns. Session 23: scoped to one owner; a turn on an unpriced model contributes
    nothing here (its cost is unknown, not $0 — see today_tokens for the cap that still applies)."""
    return sum(c for c, _ in _todays_rows(session, owner_id, today) if c)


def today_tokens(session: Session, today: date | None = None, owner_id: str = OWNER_ID) -> int:
    total = 0
    for _, usage_json in _todays_rows(session, owner_id, today):
        if usage_json:
            usage = json.loads(usage_json)
            total += sum(usage.get(k) or 0 for k in _USAGE_TO_RATE)
    return total


def record_usage_event(
    session: Session,
    kind: str,
    usage: dict | None,
    cost_usd: float | None,
    owner_id: str = OWNER_ID,
    provider: str | None = None,
    model: str | None = None,
) -> AiUsageEvent:
    row = AiUsageEvent(
        kind=kind, usage_json=json.dumps(usage) if usage else None, cost_usd=cost_usd, owner_id=owner_id, provider=provider, model=model
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def conversation_usage(session: Session, conversation_id: int) -> dict:
    rows = session.exec(select(CoachMessage).where(CoachMessage.conversation_id == conversation_id)).all()
    totals = {k: 0 for k in _USAGE_TO_RATE}
    cost = 0.0
    for row in rows:
        if row.usage_json:
            usage = json.loads(row.usage_json)
            for k in totals:
                totals[k] += usage.get(k) or 0
        if row.cost_usd:
            cost += row.cost_usd
    return {**totals, "cost_usd": cost}


def usage_summary(session: Session, owner_id: str = OWNER_ID, days: int = 30) -> dict:
    """What Catch itself recorded, per provider — not a provider-reported balance (none of the
    providers expose one through an ordinary key). A turn on a model with no entered price counts
    its tokens but contributes no cost, and is reported as `unpriced_turns` rather than as $0."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    by_provider: dict[str, dict] = {}

    def bucket(provider: str | None) -> dict:
        return by_provider.setdefault(provider or "unknown", {"tokens": 0, "cost_usd": 0.0, "turns": 0, "unpriced_turns": 0})

    chat_rows = session.exec(
        select(CoachMessage.provider, CoachMessage.usage_json, CoachMessage.cost_usd)
        .join(CoachConversation, CoachConversation.id == CoachMessage.conversation_id)
        .where(CoachConversation.owner_id == owner_id, CoachMessage.created_at >= since, CoachMessage.usage_json.is_not(None))
    ).all()
    event_rows = session.exec(
        select(AiUsageEvent.provider, AiUsageEvent.usage_json, AiUsageEvent.cost_usd).where(
            AiUsageEvent.owner_id == owner_id, AiUsageEvent.created_at >= since, AiUsageEvent.usage_json.is_not(None)
        )
    ).all()
    for provider, usage_json, cost_usd in [*chat_rows, *event_rows]:
        b = bucket(provider)
        usage = json.loads(usage_json)
        b["tokens"] += sum(usage.get(k) or 0 for k in _USAGE_TO_RATE)
        b["turns"] += 1
        if cost_usd is None:
            b["unpriced_turns"] += 1
        else:
            b["cost_usd"] += cost_usd
    return {"days": days, "by_provider": by_provider}
