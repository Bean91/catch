from datetime import datetime, timedelta, timezone

from sqlmodel import select

from catch.core.models import AiUsageEvent, NotificationLog
from catch.sync import retention

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def test_old_logs_are_pruned_and_recent_ones_stay(session):
    for days in (1, 89, 91, 500):
        session.add(NotificationLog(type="t", title="x", body="y", sent_at=NOW - timedelta(days=days), device_count=1))
    for days in (10, 399, 401):
        session.add(AiUsageEvent(**_usage(NOW - timedelta(days=days))))
    session.commit()
    removed = retention.prune_owner(session, NOW)
    assert removed["notification_log"] == 2 and removed["ai_usage_events"] == 1
    assert sorted((NOW - r.sent_at.replace(tzinfo=timezone.utc)).days for r in session.exec(select(NotificationLog)).all()) == [1, 89]
    assert retention.prune_owner(session, NOW) == {t: 0 for t in removed}  # idempotent


def _usage(when):
    cols = {c.name for c in AiUsageEvent.__table__.columns}
    base = {"provider": "anthropic", "model": "m", "kind": "chat", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0, "created_at": when}
    return {k: v for k, v in base.items() if k in cols}


def test_the_tick_knows_the_retention_job():
    from catch.api import routes_internal

    assert "retention" in routes_internal.JOBS and callable(routes_internal._retention_work)


def test_a_persons_not_duplicate_and_split_decisions_are_never_pruned(session):
    """Launch audit L-37: matching rescans all history, so pruning these let an old pair the person had separated auto-merge again."""
    from catch.core.models import MatchDecision

    old = NOW - timedelta(days=900)
    for i, decision in enumerate(("not_duplicate", "split", "merge")):
        session.add(MatchDecision(source_a="garmin", external_id_a=f"a{i}", source_b="concept2", external_id_b=f"b{i}", decision=decision, created_at=old))
    session.commit()
    assert retention.prune_owner(session, NOW)["match_decisions"] == 1
    assert sorted(d.decision for d in session.exec(select(MatchDecision)).all()) == ["not_duplicate", "split"]
