from __future__ import annotations

"""Resolves one `CanonicalActivity`'s display fields from its member `Activity` source
records (Part A.3's field priority) and, where samples exist, its zones/strain/session label
(Part E) — the one place that merges N source records into the one thing every reader
(Trends, Workouts, PBs, coach, MCP) sees. Called after every sync's matching pass and after
any manual merge/split/edit so the cache in `canonical_activities` never goes stale."""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.matching import sport_family as _sport_family
from catch.analytics.samples_codec import unpack_series
from catch.analytics.zones_samples import (
    banister_trimp_from_samples,
    detect_trailing_idle,
    power_time_in_zone_seconds,
    session_label as _session_label,
    smooth,
    time_in_zone_seconds,
)
from catch.core.models import Activity, ActivitySamples, CanonicalActivity
from catch.core.settings_store import get_settings

_DEFAULT_PRIORITY = ["concept2", "peloton", "garmin"]


def provenance(activity: Activity) -> str:
    return "peloton" if activity.origin == "peloton" else activity.source


def _pick(members: list[Activity], field: str, priority: list[str]) -> tuple[Optional[object], Optional[Activity]]:
    by_provenance: dict[str, list[Activity]] = {}
    for m in members:
        by_provenance.setdefault(provenance(m), []).append(m)
    for label in priority:
        for m in by_provenance.get(label, []):
            value = getattr(m, field)
            if value is not None:
                return value, m
    return None, None


def pick_hr(members: list[Activity]) -> tuple[Optional[float], Optional[float], Optional[Activity]]:
    """HR field priority (Part A.3): whichever source has a chest-strap HR, else the Garmin
    watch. Concept2 results are assumed chest-strap whenever they carry HR at all (a PM5 has
    no wrist sensor of its own — see catch/core/models.py's Activity.hr_source_type docstring)."""
    chest_strap = [
        m for m in members if m.avg_hr is not None and (m.hr_source_type == "chest_strap" or m.source == "concept2")
    ]
    if chest_strap:
        m = chest_strap[0]
        return m.avg_hr, m.max_hr, m
    watch = [m for m in members if m.avg_hr is not None and provenance(m) in ("garmin", "peloton")]
    if watch:
        m = watch[0]
        return m.avg_hr, m.max_hr, m
    any_hr = [m for m in members if m.avg_hr is not None]
    if any_hr:
        m = any_hr[0]
        return m.avg_hr, m.max_hr, m
    return None, None, None


def _key(m: Activity) -> str:
    return f"{m.source}:{m.external_id}"


def auto_title(sport_family: str, members: list[Activity], title_priority: list[str] | None = None) -> str:
    """Part C.3 — only used when no user override is set. Honors `field_priority.title`
    (default peloton > concept2 > garmin, task Part A.3/B.2's "keep the class name and
    instructor as the default title") for *which source's own title wins*, but each
    source's title is itself synthesized (no Garmin `activityName`/Peloton class-name field
    has been confirmed live — see docs/peloton.md — so nothing here parses raw_json for one)."""
    title_priority = title_priority or ["peloton", "concept2", "garmin"]
    by_provenance: dict[str, list[Activity]] = {}
    for m in members:
        by_provenance.setdefault(provenance(m), []).append(m)

    for label in title_priority:
        group = by_provenance.get(label)
        if not group:
            continue
        if label == "peloton":
            minutes = round((group[0].duration or 0) / 60.0) if group[0].duration else None
            return f"Peloton {minutes} min Just Ride" if minutes else "Peloton ride"
        if label == "concept2":
            concept2 = group[0]
            workout = None
            if concept2.intervals_json:
                try:
                    workout = json.loads(concept2.intervals_json)
                except (TypeError, ValueError):
                    workout = None
            if isinstance(workout, dict) and workout.get("type") == "FixedDistanceInterval":
                reps = workout.get("splits", {}).get("count") or workout.get("intervals")
                dist = workout.get("splits", {}).get("distance")
                if reps and dist:
                    return f"Erg {reps} x {int(dist)}m"
            minutes = round((concept2.duration or 0) / 60.0)
            return f"Erg {minutes}'" if minutes else "Erg"
        if label == "garmin":
            if sport_family == "rowing":
                minutes = round((group[0].duration or 0) / 60.0) if group[0].duration else None
                return f"Steady state {minutes}'" if minutes else "Row"
            break  # fall through to the generic label below

    return {"cycling": "Ride", "running": "Run", "strength": "Strength", "rowing": "Row"}.get(sport_family, "Activity")


def _overrides(canonical: CanonicalActivity) -> dict:
    return json.loads(canonical.overrides_json) if canonical.overrides_json else {}


def _activity_samples(session: Session, activity_id: int) -> Optional[dict]:
    row = session.get(ActivitySamples, activity_id)
    if row is None:
        return None
    return {
        "hr": unpack_series(row.hr_blob, row.n_samples),
        "power": unpack_series(row.power_blob, row.n_samples),
        "cadence": unpack_series(row.cadence_blob, row.n_samples),
    }


def resolve_canonical(session: Session, canonical_id: int) -> Optional[CanonicalActivity]:
    canonical = session.get(CanonicalActivity, canonical_id)
    if canonical is None:
        return None
    members = session.exec(select(Activity).where(Activity.canonical_id == canonical_id)).all()
    if not members:
        return canonical

    settings = get_settings(session)
    priority = settings["field_priority"]
    overrides = _overrides(canonical)

    sport = members[0].sport_family or _sport_family(members[0].source, members[0].type)
    start, start_src = _pick(members, "start", _DEFAULT_PRIORITY)
    duration, duration_src = _pick(members, "duration", _DEFAULT_PRIORITY)
    distance_field = "distance"
    distance_priority = priority["distance_indoor_bike"] + _DEFAULT_PRIORITY if sport == "cycling" else _DEFAULT_PRIORITY
    distance, distance_src = _pick(members, distance_field, distance_priority)
    power, power_src = _pick(members, "avg_power", priority["power"] + _DEFAULT_PRIORITY)
    cadence, cadence_src = _pick(members, "avg_cadence", priority["cadence"] + _DEFAULT_PRIORITY)
    calories, calories_src = _pick(members, "calories", _DEFAULT_PRIORITY)
    avg_hr, max_hr, hr_src = pick_hr(members)

    field_sources = {}
    for name, value, src in (
        ("start", start, start_src),
        ("duration", duration, duration_src),
        ("distance", distance, distance_src),
        ("avg_power", power, power_src),
        ("avg_cadence", cadence, cadence_src),
        ("calories", calories, calories_src),
    ):
        if src is not None:
            field_sources[name] = _key(src)
    if hr_src is not None:
        field_sources["avg_hr"] = _key(hr_src)
        field_sources["max_hr"] = _key(hr_src)

    title = overrides.get("title") or auto_title(sport, members, priority["title"])
    field_sources["title"] = "override" if overrides.get("title") else "auto"

    canonical.sport_family = overrides.get("sport_family") or sport
    canonical.start = start
    canonical.duration = duration
    canonical.distance = distance
    canonical.avg_power = power
    canonical.avg_cadence = cadence
    canonical.calories = calories
    canonical.avg_hr = avg_hr
    canonical.max_hr = max_hr
    canonical.title = title
    canonical.field_sources_json = json.dumps(field_sources)

    _resolve_zones(session, canonical, members, avg_hr, max_hr, settings)

    canonical.updated_at = datetime.now(timezone.utc)
    session.add(canonical)
    session.commit()
    session.refresh(canonical)
    return canonical


def _resting_hr_for(session: Session, when: Optional[datetime]) -> Optional[float]:
    if when is None:
        return None
    from catch.core.models import DailyWellness

    row = session.get(DailyWellness, when.astimezone().date())
    return row.resting_hr if row else None


def _resolve_zones(
    session: Session,
    canonical: CanonicalActivity,
    members: list[Activity],
    avg_hr: Optional[float],
    _unused: Optional[float],
    settings: dict,
) -> None:
    hr_member = next((m for m in members if m.avg_hr == avg_hr and avg_hr is not None), members[0])
    samples = _activity_samples(session, hr_member.id) if hr_member.id else None
    max_hr = settings.get("max_hr")

    if not samples or not any(v is not None for v in samples["hr"]):
        canonical.zones_json = None
        canonical.strain_trimp = None
        canonical.session_label = None
        canonical.auto_trimmed_tail_s = None
        return

    hr_raw = samples["hr"]
    trimmed_s = 0.0
    if settings.get("auto_trim_enabled") and any(v is not None for v in samples["cadence"]):
        trimmed_s = detect_trailing_idle(samples["cadence"], settings.get("auto_trim_min_idle_s", 120))
    usable_n = len(hr_raw) - int(trimmed_s)
    hr_for_ui = hr_raw[:usable_n] if trimmed_s else hr_raw

    smoothed = smooth(hr_for_ui)
    hr_zones = time_in_zone_seconds(smoothed, max_hr, settings)

    # Power-zone time (Part E.5) is implemented for cycling (against FTP) only — no live
    # Concept2 data exists in this account to confirm an erg power-zone threshold against
    # (docs/peloton.md/PLAN.md), so threading predicted_2k's watts_2k through here is
    # deferred rather than built against zero real evidence.
    power_zones = None
    if canonical.sport_family == "cycling" and any(v is not None for v in samples["power"]):
        ftp = settings.get("ftp_watts")
        power_for_ui = samples["power"][:usable_n] if trimmed_s else samples["power"]
        if ftp:
            power_zones = power_time_in_zone_seconds(smooth(power_for_ui), ftp, settings)

    moving_time_s = float(usable_n)
    label = _session_label(hr_zones, moving_time_s, power_zones, settings["min_zone_minutes"], settings["min_zone_pct"])

    resting_hr = _resting_hr_for(session, canonical.start)
    trimp = banister_trimp_from_samples(hr_for_ui, resting_hr, max_hr, settings["trimp_exponent"])

    canonical.zones_json = json.dumps({"hr": hr_zones, "power": power_zones})
    canonical.strain_trimp = trimp
    canonical.session_label = label
    canonical.auto_trimmed_tail_s = trimmed_s or None
