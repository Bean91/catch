"""Session 36: training load and volume over time (docs/analytics.md §35). Built on what the rest of the app already counts:

  * the day's *training* load is the stored strain's load sum minus everyday movement (steps) — the same TRIMP-unit sum ATL/CTL use,
    without walking, which Foster's monotony describes training and not daily life;
  * sessions, minutes and metres come from completed workouts by their own local day, excluded workouts left out, and a recording
    merged into another workout counts once (one canonical workout = one session);
  * plans never appear here.

Every figure is descriptive; the recent-vs-baseline comparison is a plain percentage, with no threshold called good or bad."""

from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.load import weekly_monotony_strain
from catch.core import localtime
from catch.core.models import DailyScore
from catch.sync.activity_days import canonical_in_days

RECENT_WEEKS = 4
BASELINE_WEEKS = 12


def _training_load(strain_json: Optional[str]) -> Optional[float]:
    if not strain_json:
        return None
    s = json.loads(strain_json)
    if s.get("load") is None:
        return None
    return max(float(s["load"]) - float((s.get("daily_activity") or {}).get("load") or 0.0), 0.0)


def _recovery(recovery_json: Optional[str]) -> Optional[float]:
    if not recovery_json:
        return None
    v = json.loads(recovery_json).get("value")
    return float(v) if isinstance(v, (int, float)) else None


def _pct(recent: Optional[float], base: Optional[float]) -> Optional[float]:
    if recent is None or not base:
        return None
    return (recent - base) / base * 100.0


def load_history(session: Session, weeks: int = 26) -> dict:
    today = localtime.today(session)
    this_week = today - timedelta(days=today.weekday())
    weeks = max(RECENT_WEEKS + 1, min(int(weeks), 104))
    first = this_week - timedelta(weeks=weeks - 1)
    scores = {r.date: r for r in session.exec(select(DailyScore).where(DailyScore.date >= first, DailyScore.date <= today)).all()}
    workouts = [c for c in canonical_in_days(session, first, today) if c.start is not None and not json.loads(c.overrides_json or "{}").get("exclude_from_totals")]
    by_day: dict[date, list] = {}
    for c in workouts:
        by_day.setdefault(localtime.day_of(session, c), []).append(c)

    out_weeks = []
    for i in range(weeks):
        ws = first + timedelta(weeks=i)
        days = [ws + timedelta(days=d) for d in range(7) if ws + timedelta(days=d) <= today]
        loads = [(_training_load(scores[d].strain_json) if d in scores else None) for d in days]
        scored_days = sum(1 for x in loads if x is not None)
        ms = weekly_monotony_strain([x or 0.0 for x in loads]) if len(days) == 7 else {"load": sum(x or 0.0 for x in loads), "monotony": None, "strain": None, "reason": "week in progress"}
        sessions = [c for d in days for c in by_day.get(d, [])]
        recov = [v for v in ((_recovery(scores[d].recovery_json) if d in scores else None) for d in days) if v is not None]
        out_weeks.append({
            "week_start": ws,
            "complete": len(days) == 7,
            "load": ms["load"], "monotony": ms["monotony"], "strain": ms["strain"], "monotony_reason": ms["reason"],
            "days_scored": scored_days,
            "sessions": len(sessions),
            "minutes": sum((c.duration or 0.0) for c in sessions) / 60.0,
            "distance_m": sum((c.distance or 0.0) for c in sessions),
            "training_days": sum(1 for d in days if by_day.get(d)),
            "days_without_training": sum(1 for d in days if not by_day.get(d)),
            "rest_weekdays": [d.weekday() for d in days if not by_day.get(d)],
            "avg_recovery": statistics.mean(recov) if recov else None,
        })

    months: dict[str, dict] = {}
    for c in workouts:
        key = localtime.day_of(session, c).strftime("%Y-%m")
        m = months.setdefault(key, {"month": key, "sessions": 0, "minutes": 0.0, "distance_m": 0.0})
        m["sessions"] += 1
        m["minutes"] += (c.duration or 0.0) / 60.0
        m["distance_m"] += c.distance or 0.0

    complete = [w for w in out_weeks if w["complete"]]
    recent, base = complete[-RECENT_WEEKS:], complete[-(RECENT_WEEKS + BASELINE_WEEKS):-RECENT_WEEKS]
    def avg(rows, key):
        return statistics.mean([r[key] for r in rows]) if rows else None
    comparison = None
    if len(recent) == RECENT_WEEKS and len(base) >= 4:
        comparison = {
            "recent_weeks": len(recent), "baseline_weeks": len(base),
            "rows": [
                {"metric": k, "recent": avg(recent, k), "baseline": avg(base, k), "change_pct": _pct(avg(recent, k), avg(base, k))}
                for k in ("minutes", "sessions", "distance_m", "load")
            ],
        }
    rest_by_weekday = [0] * 7
    for w in complete:
        for d in w["rest_weekdays"]:
            rest_by_weekday[d] += 1
    return {
        "from": first, "to": today, "weeks": out_weeks, "months": sorted(months.values(), key=lambda m: m["month"]),
        "comparison": comparison, "rest_by_weekday": rest_by_weekday, "complete_weeks": len(complete),
    }
