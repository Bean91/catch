from __future__ import annotations

"""The DB-facing half of routes (session 20, docs/analytics.md §28.4). Rowing only: other sports
get a map but no route matching, because the thresholds were validated against rowing tracks.

A Route is formed only when a *second* session aligns with an unassigned one — a single session
is never promoted, so the Routes page never fills with one-off outings. The athlete can always
name/tag a route, pin or unpin a session by hand, or create a route from one session.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.routes import eligible, history_stats, match, path_length_m, signature
from catch.core.models import Activity, ActivityTrack, ActivityWeather, Route
from catch.core.settings_store import get_settings
from catch.sync.tracks import family_of

logger = logging.getLogger("catch.routes")


def attach_signature(summary: dict, session: Session, activity: Activity, row: ActivityTrack) -> None:
    """Rowing only: other sports get a map but not route matching."""
    from catch.sync.tracks import filtered_for

    if family_of(activity) != "rowing":
        return

    ft = filtered_for(session, activity, row)
    if ft is not None:
        summary["signature"] = signature(ft)


def _summary(row: ActivityTrack) -> Optional[dict]:
    return json.loads(row.summary_json) if row.summary_json else None


def _usable(summary: Optional[dict], ow: dict) -> bool:
    return bool(summary and summary.get("signature")) and eligible(summary.get("gap_fraction"), ow)


def _auto_label(row: ActivityTrack, length_m: float) -> str:
    prov = json.loads(row.provider_json) if row.provider_json else {}
    place = prov.get("location_name")
    return f"{place} · {length_m / 1000:.1f} km" if place else f"Route · {length_m / 1000:.1f} km"


def _windows_overlap(a: ActivityTrack, asum: dict, b: ActivityTrack, bsum: dict) -> bool:
    if "t_start_s" not in asum or "t_start_s" not in bsum:
        return False
    a0 = a.start.timestamp() + asum["t_start_s"]
    a1 = a.start.timestamp() + asum["t_end_s"]
    b0 = b.start.timestamp() + bsum["t_start_s"]
    b1 = b.start.timestamp() + bsum["t_end_s"]
    return a0 < b1 and b0 < a1


def _route_has_same_outing(session: Session, route_id: int, row: ActivityTrack, summary: dict) -> bool:
    """A second device's recording of an outing already on the route must not join it as a repeat."""
    for member in session.exec(select(ActivityTrack).where(ActivityTrack.route_id == route_id)).all():
        msum = _summary(member)
        if msum and _windows_overlap(row, summary, member, msum):
            return True
    return False


def assign_route(session: Session, activity: Activity) -> Optional[int]:
    """Joins the activity to a route it aligns with, or forms a new route with an unassigned
    session it aligns with. Does nothing for a pinned track. Returns the route id or None."""
    row = session.get(ActivityTrack, activity.id)
    if row is None or row.route_pinned:
        return row.route_id if row else None
    if row.route_id is not None:
        return row.route_id
    ow = get_settings(session)["on_water"]
    summary = _summary(row)
    if not _usable(summary, ow):
        return None

    for route in session.exec(select(Route).where(Route.sport_family == "rowing")).all():
        if match(summary["signature"], json.loads(route.signature_json), ow)["aligned"]:
            if _route_has_same_outing(session, route.id, row, summary):
                continue
            row.route_id = route.id
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            return route.id

    others = session.exec(
        select(ActivityTrack)
        .where(ActivityTrack.activity_id != row.activity_id)
        .where(ActivityTrack.route_id.is_(None))  # type: ignore[union-attr]
        .where(ActivityTrack.route_pinned.is_(False))  # type: ignore[union-attr]
        .where(ActivityTrack.n_points >= 2)
        .order_by(ActivityTrack.start)
    ).all()
    for other in others:
        other_activity = session.get(Activity, other.activity_id)
        if other_activity is not None and activity.canonical_id is not None and other_activity.canonical_id == activity.canonical_id:
            continue  # already merged: one session, not a repeat
        osum = _summary(other)
        if osum and _windows_overlap(row, summary, other, osum):
            # Routes form at ingest, *before* matching merges two devices' recordings of one outing
            # into a canonical — overlapping time is the merge-independent sign it's the same outing.
            continue
        if not _usable(osum, ow):
            continue
        if match(osum["signature"], summary["signature"], ow)["aligned"]:
            length = path_length_m(osum["signature"])
            route = Route(sport_family="rowing", signature_json=json.dumps(osum["signature"]),
                          length_m=length, auto_label=_auto_label(other, length))
            session.add(route)
            session.commit()
            session.refresh(route)
            for r in (other, row):
                r.route_id = route.id
                r.updated_at = datetime.now(timezone.utc)
                session.add(r)
            session.commit()
            return route.id
    return None


def assign_all_routes(session: Session) -> dict:
    """Oldest first, so an early session anchors the route. Idempotent."""
    before = len(session.exec(select(Route)).all())
    rows = session.exec(select(ActivityTrack).where(ActivityTrack.n_points >= 2).order_by(ActivityTrack.start)).all()
    for row in rows:
        activity = session.get(Activity, row.activity_id)
        if activity is not None and family_of(activity) == "rowing":
            assign_route(session, activity)
    routes = session.exec(select(Route)).all()
    return {"routes": len(routes), "new": len(routes) - before}


# ---- manual control -------------------------------------------------------------------------

def set_route(session: Session, activity: Activity, route_id: Optional[int]) -> ActivityTrack:
    """Pins the session to a route (or to none). Raises KeyError for an unknown route/track."""
    row = session.get(ActivityTrack, activity.id)
    if row is None or row.n_points < 2:
        raise KeyError("no track")
    if route_id is not None and session.get(Route, route_id) is None:
        raise KeyError("no such route")
    row.route_id, row.route_pinned = route_id, True
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    return row


def unpin_route(session: Session, activity: Activity) -> Optional[int]:
    row = session.get(ActivityTrack, activity.id)
    if row is None:
        raise KeyError("no track")
    row.route_id, row.route_pinned = None, False
    session.add(row)
    session.commit()
    return assign_route(session, activity)


def create_route_from_activity(session: Session, activity: Activity, name: Optional[str]) -> Route:
    row = session.get(ActivityTrack, activity.id)
    summary = _summary(row) if row else None
    if not summary or not summary.get("signature"):
        raise KeyError("no route signature for this activity")
    length = path_length_m(summary["signature"])
    route = Route(sport_family="rowing", name=(name or "").strip() or None,
                  signature_json=json.dumps(summary["signature"]), length_m=length,
                  auto_label=_auto_label(row, length))
    session.add(route)
    session.commit()
    session.refresh(route)
    row.route_id, row.route_pinned = route.id, True
    session.add(row)
    session.commit()
    return route


def update_route(session: Session, route: Route, *, name: Optional[str] = None, tags: Optional[list] = None,
                 set_name: bool = False) -> Route:
    if set_name:
        route.name = (name or "").strip() or None
    if tags is not None:
        clean = []
        for t in tags:
            t = str(t).strip()
            if t and t not in clean:
                clean.append(t)
        route.tags_json = json.dumps(clean)
    route.updated_at = datetime.now(timezone.utc)
    session.add(route)
    session.commit()
    return route


# ---- reads ------------------------------------------------------------------------------------

def route_payload(route: Route, n_sessions: Optional[int] = None) -> dict:
    return {
        "id": route.id,
        "name": route.name,
        "auto_label": route.auto_label,
        "display_name": route.name or route.auto_label or f"Route {route.id}",
        "name_is_manual": route.name is not None,
        "tags": json.loads(route.tags_json or "[]"),
        "sport_family": route.sport_family,
        "length_m": route.length_m,
        "length_source": "gps_derived",
        "n_sessions": n_sessions,
    }


def _session_rows(session: Session, route_id: int) -> list[tuple[ActivityTrack, Activity]]:
    """One row per *outing*: members of the same canonical (two devices, one row) count once."""
    out = []
    seen: set[int] = set()
    for row in session.exec(select(ActivityTrack).where(ActivityTrack.route_id == route_id).order_by(ActivityTrack.activity_id)).all():
        activity = session.get(Activity, row.activity_id)
        if activity is None:
            continue
        if activity.canonical_id is not None:
            if activity.canonical_id in seen:
                continue
            seen.add(activity.canonical_id)
        out.append((row, activity))
    return out


def list_routes(session: Session) -> list[dict]:
    out = []
    for route in session.exec(select(Route)).all():
        rows = _session_rows(session, route.id)
        item = route_payload(route, len(rows))
        item["last_session"] = max((a.start for _, a in rows), default=None)
        out.append(item)
    out.sort(key=lambda r: (r["last_session"] is not None, r["last_session"]), reverse=True)
    return out


def weather_brief(session: Session, activity_id: int) -> Optional[dict]:
    w = session.get(ActivityWeather, activity_id)
    if w is None:
        return None
    s = json.loads(w.summary_json)
    return {
        "status": w.status,
        "temperature_avg_c": s["temperature_c"]["avg"],
        "wind_speed_kmh": s["wind"]["speed_kmh"],
        "wind_direction_from_label": s["wind"]["direction_from_label"],
        "precipitation_mm": s["precipitation_mm"],
        "condition": s["condition"]["text"],
    }


def route_history(session: Session, route: Route, settings: Optional[dict] = None) -> dict:
    from catch.analytics.training_intelligence import confidence_level
    from catch.sync.training_intelligence import _history_days

    settings = settings or get_settings(session)
    sessions = []
    for row, activity in _session_rows(session, route.id):
        summary = _summary(row) or {}
        sessions.append({
            "date": activity.start.isoformat() if activity.start else None,
            "canonical_id": activity.canonical_id,
            "activity_id": activity.id,
            "distance_m": summary.get("distance_m"),
            "moving_s": summary.get("moving_s"),
            "elapsed_s": summary.get("elapsed_s"),
            "avg_speed_mps": summary.get("avg_speed_mps"),
            "peak_speed_mps": summary.get("peak_speed_mps"),
            "avg_hr": summary.get("avg_hr"),
            "weather": weather_brief(session, activity.id),
            "pinned": row.route_pinned,
        })
    stats = history_stats(sessions)
    n_days = _history_days(session, datetime.now(timezone.utc).date())
    confidence = confidence_level(n_days, stats["n_sessions"], settings) if stats["n_sessions"] else "insufficient_data"
    note = None
    if stats["n_sessions"] < 2:
        note = "Only one session on this route so far — nothing to compare against yet."
    return {
        "route": route_payload(route, len(sessions)),
        "sessions": sorted(sessions, key=lambda s: s["date"] or "", reverse=True),
        "stats": stats,
        "confidence": confidence,
        "note": note,
        "comparison": "Compared only because each session's track aligned with this route's reference "
                      "course (matching start, end, length and coverage).",
    }


def route_for_activity(session: Session, activity: Activity) -> Optional[dict]:
    row = session.get(ActivityTrack, activity.id)
    if row is None or row.route_id is None:
        return None
    route = session.get(Route, row.route_id)
    if route is None:
        return None
    return {**route_payload(route), "pinned": row.route_pinned}
