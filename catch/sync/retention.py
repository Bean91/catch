"""Scheduled retention (docs/data-inventory.md "Retention"). Per-person logs that have no purpose beyond a recent window are pruned;
everything else is kept until the person deletes it (Privacy center) or their account.

    notification_log     90 days   (dedup needs "sent today", not history)
    ai_usage_events      400 days  (the spend caps read today; a year of history is plenty for the usage page)
    merge_log            400 days
    match_decisions      400 days

Runs per user inside the tick (public) or the scheduler (personal). Idempotent and cheap."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sa_delete
from sqlmodel import Session

from catch.core.models import AiUsageEvent, MatchDecision, MergeLog, NotificationLog

RULES = (
    (NotificationLog, "sent_at", 90),
    (AiUsageEvent, "created_at", 400),
    (MergeLog, "created_at", 400),
    (MatchDecision, "created_at", 400),
)


def prune_owner(session: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    removed = {}
    for cls, column, days in RULES:
        removed[cls.__tablename__] = session.execute(sa_delete(cls).where(getattr(cls, column) < now - timedelta(days=days))).rowcount or 0
    session.commit()
    return removed
