from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.analytics.wake_time import average_wake_time_minutes
from catch.core.models import DailyWellness, Event, IllnessAck, NotificationLog
from catch.core.settings_store import get_settings
from catch.notify import ntfy, push

logger = logging.getLogger("catch.notify.triggers")

# Fallback when there isn't yet a trailing-wake-time baseline (a fresh instance, or Garmin
# sleep data missing) — 7:30am, a reasonable default rather than never sending a brief at all.
_DEFAULT_WAKE_MINUTES = 7 * 60 + 30
_WAKE_LOOKBACK_DAYS = 14
# How late past the target minute the brief is still allowed to fire — covers this job's own
# poll interval without re-firing hours later if the app was offline all morning.
_MORNING_BRIEF_GRACE_MINUTES = 120
_SYNC_STALE_HOURS = 36
_GARMIN_KEY_WARN_DAYS = (14, 3, 1)


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _minutes_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _in_quiet_hours(settings: dict, now: datetime) -> bool:
    cfg = settings["notifications"]
    start = _parse_hhmm(cfg["quiet_hours_start"])
    end = _parse_hhmm(cfg["quiet_hours_end"])
    now_m = _minutes_of_day(now)
    if start == end:
        return False
    if start < end:
        return start <= now_m < end
    return now_m >= start or now_m < end  # wraps past midnight (the default 22:00-06:00)


def _parse_hhmm(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def _type_enabled(settings: dict, type_: str) -> bool:
    return bool(settings["notifications"]["types"].get(type_, True))


def _sent_today(session: Session, type_: str, today: date | None = None) -> bool:
    today = today or date.today()
    rows = session.exec(select(NotificationLog).where(NotificationLog.type == type_)).all()
    return any(r.sent_at.astimezone().date() == today for r in rows)


def _gated_notify(session: Session, settings: dict, *, type_: str, title: str, body: str, deep_link: str | None = None) -> bool:
    """The one gate every trigger below goes through: type toggle, then quiet hours. Returns
    whether it actually sent (so a caller can decide whether to mark its own per-episode
    "already handled" state — a suppressed send should usually be retried on a later tick,
    not treated as delivered)."""
    if not _type_enabled(settings, type_):
        return False
    if _in_quiet_hours(settings, _now_local()):
        return False
    push.notify(session, type=type_, title=title, body=body, deep_link=deep_link)
    return True


# -- Morning brief ------------------------------------------------------------


def check_morning_brief(session: Session) -> None:
    settings = get_settings(session)
    if not _type_enabled(settings, "morning_brief") or _sent_today(session, "morning_brief"):
        return
    cutoff = date.today() - timedelta(days=_WAKE_LOOKBACK_DAYS)
    samples = session.exec(
        select(DailyWellness.wake_time_minutes).where(
            DailyWellness.date >= cutoff, DailyWellness.wake_time_minutes.is_not(None)
        )
    ).all()
    baseline = average_wake_time_minutes(list(samples))
    target = (baseline if baseline is not None else _DEFAULT_WAKE_MINUTES) + 30
    now_m = _minutes_of_day(_now_local())
    if not (target <= now_m < target + _MORNING_BRIEF_GRACE_MINUTES):
        return

    # Without this, the brief would almost always describe yesterday — `run_sync` (and the
    # `recompute_scores` it triggers) is what actually fills in *today's* DailyWellness/
    # DailyScore rows, and the regular 2h-interval sync job may not have run yet this soon
    # after waking. Non-blocking (skips instantly if the regular job is already mid-run — see
    # scheduler.py's per-source lock) and cheap (days=1).
    from catch.sync.scheduler import run_sync

    run_sync("garmin", days=1)

    from catch.api.routes_analytics import today as get_today

    payload = get_today(db=session)
    recovery = payload.get("recovery") or {}
    strain_range = payload.get("strain_target_range") or [None, None]
    value = recovery.get("value")
    band = recovery.get("band") or "calibrating"
    recovery_line = f"Recovery {round(value)}% ({band})" if value is not None else f"Recovery: {band}"
    strain_line = (
        f"Strain target {strain_range[0]}-{strain_range[1]}" if strain_range[0] is not None else "Strain target: n/a"
    )
    body = f"{recovery_line}. {strain_line}. {payload.get('recommendation', '')} Tap to check in."
    _gated_notify(session, settings, type_="morning_brief", title="Morning brief", body=body, deep_link="/")


# -- Illness early warning -----------------------------------------------------


def check_illness(session: Session) -> None:
    """Only ever notifies about *today's* or *yesterday's* flag — on first deploy (or after
    any illness-threshold tuning that re-flags an old date), `recompute_scores` can leave
    `first_flagged_at` set with `notified_at` still NULL on any number of historical
    `IllnessAck` rows (it only ever inserts, never overwrites — see the model's docstring).
    Without this date guard, the very first tick after deploy would fire one push per
    historical flag. An old, out-of-window row is marked `notified_at` without ever sending,
    so it stops being reconsidered every tick forever."""
    settings = get_settings(session)
    acks = session.exec(
        select(IllnessAck).where(
            IllnessAck.first_flagged_at.is_not(None),
            IllnessAck.notified_at.is_(None),
            IllnessAck.dismissed == False,  # noqa: E712 - SQLAlchemy needs `== False`, not `is False`
        )
    ).all()
    cutoff = date.today() - timedelta(days=1)
    for ack in acks:
        if ack.date < cutoff:
            ack.notified_at = datetime.now(timezone.utc)
            session.add(ack)
            session.commit()
            continue

        # The flag's own explanation string lives in daily_scores.illness_json, not on the
        # ack row itself (see IllnessAck's docstring) — read it back rather than recomputing,
        # and re-check the *current* level: a later recompute (new history, a tuned
        # threshold) may have since downgraded this date away from "likely" without ever
        # touching this insert-only ack row.
        from catch.core.models import DailyScore

        score_row = session.get(DailyScore, ack.date)
        level = None
        explanation = "An early-warning signal flagged this morning's numbers."
        if score_row and score_row.illness_json:
            import json as _json

            illness = _json.loads(score_row.illness_json)
            level = illness.get("level")
            explanation = illness.get("explanation", explanation)
        if level != "likely":
            ack.notified_at = datetime.now(timezone.utc)
            session.add(ack)
            session.commit()
            continue

        sent = _gated_notify(
            session,
            settings,
            type_="illness",
            title="Possible illness/overtraining",
            body=explanation,
            deep_link="/",
        )
        if sent:
            ack.notified_at = datetime.now(timezone.utc)
            session.add(ack)
            session.commit()


# -- Garmin key expiry ----------------------------------------------------------


def check_garmin_key_expiring(session: Session) -> None:
    settings = get_settings(session)
    expires_on = settings.get("garmin_key_expires_on")
    if not expires_on or _sent_today(session, "garmin_key_expiring"):
        return
    days_left = (date.fromisoformat(str(expires_on)) - date.today()).days
    if days_left not in _GARMIN_KEY_WARN_DAYS:
        return
    _gated_notify(
        session,
        settings,
        type_="garmin_key_expiring",
        title="Garmin key expiring",
        body=f"Your Garmin personal API key expires in {days_left} day{'s' if days_left != 1 else ''} ({expires_on}).",
        deep_link="/settings/status",
    )


# -- Sync broken ----------------------------------------------------------------


def alert_sync_broken(session: Session, source: str, reason: str) -> bool:
    """Called at the exact moment a source's `SyncState.consecutive_failures` crosses the
    3-in-a-row threshold (catch/sync/state.py), or by `check_sync_stale` below for the
    "no successful sync in 36h" condition. Returns whether it actually sent — the caller
    (state.py) only marks the episode as alerted when this returns True, so a send
    suppressed by quiet hours gets retried on the episode's next failure/tick rather than
    silently never firing."""
    settings = get_settings(session)
    sent = _gated_notify(
        session,
        settings,
        type_="sync_broken",
        title=f"{source} sync is broken",
        body=reason,
        deep_link="/settings/status",
    )
    if sent:
        ntfy.send(f"Catch: {source} sync is broken — {reason}")
    return sent


def check_sync_stale(session: Session) -> None:
    """The task's second sync_broken condition: "no new data for 36h," read as no *successful*
    sync in 36h for a source — distinct from (and in addition to) the 3-consecutive-failures
    condition, which fires immediately rather than waiting 36h. Concept2 (an account with zero
    logged results is a real, documented possibility — see PLAN.md session 2) and Withings
    (normal multi-day gaps between weigh-ins) both still run on a schedule regardless of
    whether they find anything new, so `last_success_at` going stale always means the sync
    itself stopped happening, never "nothing new to sync."""
    from catch.core.models import SyncState
    from catch.sync.scheduler import SOURCES

    cutoff = datetime.now(timezone.utc) - timedelta(hours=_SYNC_STALE_HOURS)
    for source in SOURCES:
        row = session.get(SyncState, source)
        if row is None or row.alert_sent_at is not None:
            continue
        if row.last_success_at is not None and row.last_success_at >= cutoff:
            continue
        if row.last_attempt_at is None:
            continue  # never even tried yet (fresh instance) — nothing to alert about
        sent = alert_sync_broken(session, source, f"no successful sync in over {_SYNC_STALE_HOURS}h")
        if sent:
            row.alert_sent_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()


# -- Test-center day-before reminder --------------------------------------------


def check_test_reminder(session: Session) -> None:
    settings = get_settings(session)
    if not _type_enabled(settings, "test_reminder") or _sent_today(session, "test_reminder"):
        return
    tomorrow = date.today() + timedelta(days=1)
    events = session.exec(
        select(Event).where(Event.date == tomorrow, Event.result.is_(None)).order_by(Event.id)
    ).all()
    relevant = [e for e in events if e.type == "2k_test" or (e.type == "race" and e.priority == "A")]
    if not relevant:
        return

    lines = []
    for event in relevant:
        line = event.name
        if event.plan_json:
            import json as _json

            plan = _json.loads(event.plan_json)
            goal_s = plan.get("goal_time_s")
            if goal_s is not None:
                m, s = divmod(round(goal_s), 60)
                line += f" — pacing plan ready, goal {m}:{s:02d}"
        lines.append(line)
    title = "Test/race tomorrow" if len(relevant) == 1 else "Tests/races tomorrow"
    _gated_notify(session, settings, type_="test_reminder", title=title, body="; ".join(lines), deep_link="/tests")
