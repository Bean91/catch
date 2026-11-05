from __future__ import annotations

import json
import logging
from datetime import date as date_, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import httpx
from sqlmodel import Session

from catch.analytics.erg_math import watts_from_pace
from catch.core.config import settings
from catch.core.settings_store import get_settings, update_settings
from catch.sync.samples import store_samples_from_strokes
from catch.sync.upsert import upsert_activity, upsert_strokes

logger = logging.getLogger("catch.concept2")

BASE_URL = "https://log.concept2.com"
ACCEPT_HEADER = "application/vnd.c2logbook.v1+json"
SOURCE = "concept2"

# The pace->watts formula (see catch/analytics/erg_math.py) is Concept2's RowErg/SkiErg
# formula; BikeErg power doesn't follow it, so per-stroke watts are only derived for these.
WATTS_DERIVABLE_TYPES = {"rower", "dynamic", "slides", "skierg"}


class Concept2AuthError(RuntimeError):
    pass


def _headers() -> dict:
    if not settings.concept2_access_token:
        raise Concept2AuthError("CONCEPT2_ACCESS_TOKEN is not set")
    return {
        "Authorization": f"Bearer {settings.concept2_access_token}",
        "Accept": ACCEPT_HEADER,
    }


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, headers=_headers(), timeout=30.0)


def _check(resp: httpx.Response) -> httpx.Response:
    if resp.status_code == 401:
        raise Concept2AuthError(
            "Concept2 access token invalid or expired — generate a new one under "
            "Edit Profile > Applications > Concept2 Logbook API integration"
        )
    resp.raise_for_status()
    return resp


def list_results(
    http: httpx.Client,
    *,
    updated_after: datetime | None = None,
    from_date: date_ | None = None,
    to_date: date_ | None = None,
    page_size: int = 100,
) -> Iterable[dict]:
    page = 1
    while True:
        params: dict[str, Any] = {"page": page, "number": page_size}
        if updated_after:
            # Docs: "updated_after" is GMT, "YYYY-MM-DD HH:MM:SS" — our datetimes are UTC.
            params["updated_after"] = updated_after.strftime("%Y-%m-%d %H:%M:%S")
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()
        body = _check(http.get("/api/users/me/results", params=params)).json()
        for item in body.get("data", []):
            yield item
        pagination = (body.get("meta") or {}).get("pagination") or {}
        if page >= pagination.get("total_pages", 1):
            return
        page += 1


def get_result_detail(http: httpx.Client, result_id: int, include: str = "strokes,metadata") -> dict:
    body = _check(http.get(f"/api/users/me/results/{result_id}", params={"include": include})).json()
    return body.get("data", {})


def get_profile(http: httpx.Client) -> dict:
    return _check(http.get("/api/users/me")).json().get("data", {})


def _result_end_utc(item: dict) -> datetime | None:
    # Per the docs, `date` is the workout's *end* time as stored on the monitor, local time
    # unless `timezone`/`date_utc` are set (both can be null for older/simpler entries).
    date_utc = item.get("date_utc")
    date_str = date_utc or item.get("date")
    if not date_str:
        return None
    naive = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
    if date_utc:
        return naive.replace(tzinfo=timezone.utc)
    tz_name = item.get("timezone")
    if tz_name:
        try:
            return naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
        except Exception:
            pass
    # No tz info at all: best-effort assume UTC. Documented limitation (see
    # docs/concept2-endpoints.md) — revisit once real results carry a timezone.
    return naive.replace(tzinfo=timezone.utc)


def _result_duration_seconds(item: dict) -> float:
    work_time = (item.get("time") or 0) / 10.0
    rest_time = (item.get("rest_time") or 0) / 10.0
    return work_time + rest_time


def _result_start_utc(item: dict) -> datetime | None:
    end = _result_end_utc(item)
    if end is None:
        return None
    return end - timedelta(seconds=_result_duration_seconds(item))


def _avg_power(item: dict) -> float | None:
    wattminutes = item.get("wattminutes_total")
    time_seconds = (item.get("time") or 0) / 10.0
    if wattminutes and time_seconds:
        return wattminutes * 60.0 / time_seconds
    if item.get("type") in WATTS_DERIVABLE_TYPES:
        distance = item.get("distance")
        if distance and time_seconds:
            pace_s_per_500 = (time_seconds / distance) * 500.0
            return watts_from_pace(pace_s_per_500)
    return None


def _activity_fields(item: dict) -> dict:
    heart_rate = item.get("heart_rate") or {}
    workout = item.get("workout")
    raw = {k: v for k, v in item.items() if k not in ("stroke_data", "strokes")}
    return {
        "type": item.get("type"),
        "workout_type": item.get("workout_type"),
        "start": _result_start_utc(item),
        "duration": _result_duration_seconds(item) or None,
        "distance": item.get("distance"),
        "avg_hr": heart_rate.get("average"),
        "max_hr": heart_rate.get("max"),
        "avg_power": _avg_power(item),
        "calories": item.get("calories_total"),
        "drag_factor": item.get("drag_factor"),
        "stroke_rate": item.get("stroke_rate"),
        "intervals_json": json.dumps(workout) if workout else None,
        "raw_json": json.dumps(raw),
        # A PM5 only ever logs HR from a paired ANT+ strap — there's no wrist sensor on the
        # monitor itself — so any result with HR at all is chest-strap HR by construction
        # (see catch/core/models.py's Activity.hr_source_type docstring).
        "hr_source_type": "chest_strap" if heart_rate.get("average") else None,
    }


def _extract_strokes(item: dict) -> list[dict]:
    # A result with no stroke data has been observed to carry `stroke_data: false` rather than
    # omit the key (the embed's no-strokes shape isn't documented — see
    # docs/concept2-endpoints.md) — guard against treating that flag as the array itself.
    raw = item.get("stroke_data") or item.get("strokes") or []
    if not isinstance(raw, list):
        raw = []
    erg_type = item.get("type")
    can_derive_watts = erg_type in WATTS_DERIVABLE_TYPES
    out = []
    interval_index = 0
    prev_t = None
    for seq, s in enumerate(raw):
        t_tenths = s.get("t")
        if t_tenths is None:
            continue
        t = t_tenths / 10.0
        # t (and d) reset to 0 at the start of each interval/split (documented) — a drop is
        # how we detect the boundary since there's no explicit interval id per stroke.
        if prev_t is not None and t < prev_t:
            interval_index += 1
        prev_t = t
        d = s.get("d")
        distance_m = d / 10.0 if d is not None else None
        p = s.get("p")
        pace_500m = p / 10.0 if p else None
        hr = s.get("hr") or None  # Concept2 uses 0 for "no reading", not a real HR of 0
        out.append(
            {
                "seq": seq,
                "interval_index": interval_index,
                "t": t,
                "distance": distance_m,
                "pace_500m": pace_500m,
                "watts": watts_from_pace(pace_500m) if (pace_500m and can_derive_watts) else None,
                "stroke_rate": s.get("spm"),
                "hr": hr,
            }
        )
    return out


def _seed_max_hr(session: Session, http: httpx.Client) -> None:
    if get_settings(session).get("max_hr"):
        return
    try:
        profile = get_profile(http)
    except Exception:
        logger.exception("could not fetch Concept2 profile to seed max_hr")
        return
    max_hr = profile.get("max_heart_rate")
    if max_hr:
        update_settings(session, {"max_hr": max_hr})
        # The same already-resolved-canonical staleness `PUT /api/settings` fixes
        # (catch/api/routes_analytics.py's put_settings) applies here too: any canonical
        # already resolved before this first Concept2 sync (e.g. Garmin history on a fresh
        # install) was zoned/strained with max_hr unset, and needs recomputing now that it
        # isn't. Safe to run synchronously (unlike put_settings) — this already runs inside a
        # sync (scheduler.py, cli.py, or the already-long-running POST /api/sync/{source}
        # request), never on a routine request's hot path.
        from catch.sync.canonical import resolve_all_canonicals
        from catch.sync.scoring import recompute_scores

        resolve_all_canonicals(session)
        recompute_scores(session)


def sync(
    session: Session,
    updated_after: datetime | None = None,
    days: int | None = None,
    http: httpx.Client | None = None,
) -> dict:
    http = http or _client()
    _seed_max_hr(session, http)

    from_date = date_.today() - timedelta(days=days) if (days and not updated_after) else None
    results = 0
    strokes_total = 0
    for item in list_results(http, updated_after=updated_after, from_date=from_date):
        # The list endpoint doesn't carry workout/drag_factor/stroke_rate/heart_rate (per the
        # documented response shape), and a live account has shown `stroke_data` on a list
        # item as a bare presence flag (bool) rather than the embedded array — so a prior
        # "skip the fetch if stroke_data is already here" shortcut could mistake that flag for
        # real data and crash enumerating it. Always fetch the full result instead.
        detail = get_result_detail(http, item["id"], include="strokes,metadata")
        activity = upsert_activity(session, SOURCE, str(item["id"]), **_activity_fields(detail))
        strokes = _extract_strokes(detail)
        if strokes:
            strokes_total += upsert_strokes(session, activity.id, strokes)
            store_samples_from_strokes(session, activity.id, strokes)
        from catch.sync.canonical import resolve_canonical

        resolve_canonical(session, activity.canonical_id)
        results += 1
    # Cross-source matching (task Part A) — not per-activity linking anymore; one pass over
    # all unmatched activities, idempotent, logs every auto-merge (catch/sync/matching.py).
    from catch.sync.matching import run_matching

    match_result = run_matching(session)
    return {"results": results, "strokes": strokes_total, **match_result}
