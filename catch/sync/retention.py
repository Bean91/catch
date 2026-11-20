"""Scheduled retention (docs/data-inventory.md "Retention"). Per-person logs that have no purpose beyond a recent window are pruned;
everything else is kept until the person deletes it (Privacy center) or their account.

    notification_log     90 days   (dedup needs "sent today", not history)
    ai_usage_events      400 days  (the spend caps read today; a year of history is plenty for the usage page)
    merge_log            400 days
    match_decisions      400 days, except not_duplicate/split: those block a re-merge for as long as both activities exist
    tool_call_log        90 days   (an audit of recent outside-client activity, not a history)

Runs per user inside the tick (public) or the scheduler (personal). Idempotent and cheap."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sa_delete
from sqlmodel import Session

from catch.core.models import AiUsageEvent, MatchDecision, MergeLog, NotificationLog, OAuthAuthCode, OAuthGrant, ToolCallLog

BLOCKING_DECISIONS = ("not_duplicate", "split")  # catch/sync/matching.py::_blocked

RULES = (
    (NotificationLog, "sent_at", 90),
    (AiUsageEvent, "created_at", 400),
    (MergeLog, "created_at", 400),
    (MatchDecision, "created_at", 400),
    (ToolCallLog, "created_at", 90),
    (OAuthAuthCode, "expires_at", 0),  # an expired authorization code is just garbage
)


def prune_owner(session: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    removed = {}
    for cls, column, days in RULES:
        stmt = sa_delete(cls).where(getattr(cls, column) < now - timedelta(days=days))
        if cls is MatchDecision:
            # Matching rescans all history, so pruning these undid the person's own "not a duplicate"/"split" (launch audit L-37).
            stmt = stmt.where(MatchDecision.decision.not_in(BLOCKING_DECISIONS))
        removed[cls.__tablename__] = session.execute(stmt).rowcount or 0
    # Grants that ended (revoked or past their absolute lifetime) more than 30 days ago.
    cutoff = now - timedelta(days=30)
    removed["oauth_grants"] = session.execute(sa_delete(OAuthGrant).where((OAuthGrant.revoked_at < cutoff) | (OAuthGrant.absolute_expires_at < cutoff))).rowcount or 0
    session.commit()
    return removed
