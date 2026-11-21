from __future__ import annotations

"""The evidence for the 2k estimate (session 32 rewrite — docs/analytics.md §2), and the estimate itself for every reader: GET
/api/predict/2k, Today, the coach/MCP tool, an event's race projection, and catch/sync/canonical.py's rowing power-zone threshold.

Evidence = confirmed tests and confirmed single-effort pieces ("declared"), plus continuous Concept2 rows with no rest whose heart
rate shows a hard effort ("hr_verified") or that have no heart rate at all ("effort_unknown", weak). Read through canonical activities
so the athlete's own "exclude from totals" is respected; a rate-capped piece (30 min at r20) and interval work never count."""

import json
from datetime import date, datetime

from sqlalchemy import event
from sqlalchemy.orm import defer
from sqlmodel import Session, select

from catch.analytics.erg_math import watts_from_pace
from catch.analytics.predict import LOOKBACK_DAYS, MAX_DISTANCE_M, MIN_DISTANCE_M, effort_class, predict_2k
from catch.core import localtime
from catch.core.models import Activity, CanonicalActivity

# Continuous single efforts. Concept2 stores interval rest inside Activity.duration while distance is work-only, so an untyped
# result ("unknown"/None) only counts when its raw record shows no rest time.
CONTINUOUS_WORKOUT_TYPES = {None, "unknown", "JustRow", "FixedDistanceSplits", "FixedTimeSplits"}
_UNTYPED = {None, "unknown"}
RATE_CAPPED_PIECE_TYPES = {"30min_r20"}
_CACHE_KEY = "catch_2k_evidence"


def _overrides(c: CanonicalActivity | None) -> dict:
    return json.loads(c.overrides_json) if c is not None and c.overrides_json else {}


def _no_rest(a: Activity) -> bool:
    if a.workout_type not in _UNTYPED:
        return True
    try:
        raw = json.loads(a.raw_json or "{}")
    except ValueError:
        return False
    return not raw.get("rest_time") and not (a.intervals_json and '"intervals"' in a.intervals_json)


def evidence(session: Session, settings: dict) -> list[dict]:
    """Every qualifying performance, newest first, with its instant (`start`) so an as-of question can filter it. Cached on the
    session: resolving every canonical asks for the threshold as of each one's date."""
    cached = session.info.get(_CACHE_KEY)
    if cached is not None and cached[0] == settings.get("max_hr"):
        return cached[1]
    from catch.sync.erg_test import list_tests

    points: list[dict] = []
    declared_canonicals: set[int] = set()
    for row in list_tests(session):
        if not row.get("date") or not row.get("distance_m") or not row.get("duration_s") or row.get("start") is None:
            continue
        if row.get("test_type") in RATE_CAPPED_PIECE_TYPES:
            continue
        if row["kind"] == "test":
            declared_canonicals.add(row["canonical_id"])
        points.append({
            "distance_m": row["distance_m"], "duration_s": row["duration_s"], "date": date.fromisoformat(row["date"]), "start": row["start"],
            "effort": "declared", "label": f"{'Test' if row['kind'] == 'test' else 'Piece'}: {row.get('test_type') or 'custom'}",
            "canonical_id": row["canonical_id"], "source": row["kind"],
        })

    max_hr = settings.get("max_hr")
    rows = session.exec(
        select(Activity).options(defer(Activity.raw_json)).where(
            Activity.source == "concept2", Activity.type == "rower", Activity.distance >= MIN_DISTANCE_M, Activity.distance <= MAX_DISTANCE_M,
            Activity.duration.is_not(None), Activity.start.is_not(None),
        )
    ).all()
    canonical_ids = sorted({a.canonical_id for a in rows if a.canonical_id is not None})
    canonicals = {}
    for i in range(0, len(canonical_ids), 500):
        for c in session.exec(select(CanonicalActivity).where(CanonicalActivity.id.in_(canonical_ids[i : i + 500]))).all():
            canonicals[c.id] = c
    for a in rows:
        c = canonicals.get(a.canonical_id)
        if a.canonical_id in declared_canonicals or a.workout_type not in CONTINUOUS_WORKOUT_TYPES:
            continue
        if c is not None and (_overrides(c).get("exclude_from_totals") or c.absorbed_into_piece_id is not None):
            continue
        if not _no_rest(a):
            continue
        effort = effort_class(declared=False, avg_hr=a.avg_hr, max_hr=max_hr)
        if effort is None:
            continue
        day = localtime.day_of(session, c) if c is not None else localtime.day_of(session, a)
        points.append({
            "distance_m": a.distance, "duration_s": a.duration, "date": day, "start": a.start, "effort": effort,
            "label": f"{a.distance:.0f} m row", "canonical_id": a.canonical_id, "source": "concept2",
        })
    points.sort(key=lambda p: p["start"], reverse=True)
    session.info[_CACHE_KEY] = (max_hr, points)
    return points


def invalidate(session: Session) -> None:
    session.info.pop(_CACHE_KEY, None)


def estimate_2k(session: Session, settings: dict, before: datetime | None = None) -> dict:
    """The 2k estimate as it stood on the day of `before` (an activity's start), or now. Always carries the latest *measured* 2k separately — an estimate never replaces or hides one."""
    if before is None:
        as_of = localtime.today(session)
        pts = evidence(session, settings)
    else:
        # Everything up to that day, the session's own efforts included: zones as % of a 2k are defined by the test that day too.
        as_of = localtime.local_date_at(session, before)
        pts = [p for p in evidence(session, settings) if p["date"] <= as_of]
    result = predict_2k(pts, as_of)
    result["as_of"] = as_of.isoformat()
    result["measured_2k"] = measured_2k(session, settings, as_of, pts)
    return result


def measured_2k(session: Session, settings: dict, as_of: date, pts: list[dict] | None = None) -> dict | None:
    """The athlete's latest confirmed 2,000 m test (and their best in the last year), exactly as recorded."""
    pts = evidence(session, settings) if pts is None else pts
    tests = [p for p in pts if p["effort"] == "declared" and abs(p["distance_m"] - 2000.0) < 0.5 and (as_of - p["date"]).days <= LOOKBACK_DAYS]
    if not tests:
        return None
    latest = max(tests, key=lambda p: p["start"])
    best = min(tests, key=lambda p: p["duration_s"])
    as_dict = lambda p: {"time_s": p["duration_s"], "date": p["date"].isoformat(), "canonical_id": p["canonical_id"], "label": p["label"]}  # noqa: E731
    return {"kind": "measured", "latest": as_dict(latest), "best_last_year": as_dict(best)}


def implied_2k_history(session: Session, settings: dict, from_: date | None = None, to: date | None = None) -> list[dict]:
    """One point per qualifying effort: the 2k that effort alone implies (historical, per effort — never the current estimate)."""
    from catch.analytics.predict import implied_2k_time

    out = []
    for p in sorted(evidence(session, settings), key=lambda p: p["start"]):
        if (from_ and p["date"] < from_) or (to and p["date"] > to):
            continue
        out.append({"date": p["date"], "value": implied_2k_time(p["distance_m"], p["duration_s"]), "activity_id": p["canonical_id"],
                    "effort": p["effort"], "distance_m": p["distance_m"]})
    return out


def rowing_watts_2k(session: Session, settings: dict, before: datetime | None = None) -> float | None:
    """The estimated 2k pace as watts, as of the day of `before` — the erg power-zone threshold. As-of (session 32) so a later
    full re-resolve doesn't rewrite an old session's zones with today's fitness. None until there is evidence."""
    result = estimate_2k(session, settings, before)
    if result["value"] is None:
        return None
    return watts_from_pace(result["value"])


def _drop_cache_on_change(session: Session, flush_context, instances) -> None:
    from catch.core.models import Piece

    if _CACHE_KEY in session.info and any(isinstance(o, (Activity, CanonicalActivity, Piece)) for o in (*session.new, *session.dirty, *session.deleted)):
        session.info.pop(_CACHE_KEY, None)


event.listen(Session, "before_flush", _drop_cache_on_change)
