from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.core.models import CoachMessage

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


def today_spend_usd(session: Session, today: date | None = None) -> float:
    start, end = _local_day_utc_range(today or date.today())
    rows = session.exec(
        select(CoachMessage.cost_usd).where(CoachMessage.created_at >= start, CoachMessage.created_at < end)
    ).all()
    return sum(c for c in rows if c)


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
