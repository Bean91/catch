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

from catch.analytics.cycling_load import best_rolling_power, cycling_tss, estimate_ftp_watts
from catch.analytics.matching import category_for_canonical, is_indoor
from catch.analytics.matching import sport_family as _sport_family
from catch.analytics.samples_codec import unpack_series
from catch.analytics.zones_samples import (
    banister_trimp_from_samples,
    detect_trailing_idle,
    drop_dropouts,
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


def _humanize_type(type_key: Optional[str]) -> str:
    return type_key.replace("_", " ").title() if type_key else ""


def _is_generic_garmin_title(title_hint: Optional[str], type_key: Optional[str]) -> bool:
    """Garmin Connect's own generic per-type label (confirmed live: a plain watch-recorded
    "indoor_cycling" activity's `activityName` is exactly "Indoor Cycling") isn't useful as a
    title — but a *real* class name (Peloton's own, once one exists — see docs/peloton.md)
    or a user-renamed activity in Garmin Connect is. Compares case/spacing-insensitively so
    "Indoor Cycling" == humanize("indoor_cycling") without being thrown by punctuation."""
    if not title_hint:
        return True
    return title_hint.strip().casefold() == _humanize_type(type_key).casefold()


def auto_title(sport_family: str, members: list[Activity], title_priority: list[str] | None = None) -> str:
    """Part C.3 — only used when no user override is set. Honors `field_priority.title`
    (default peloton > concept2 > garmin, task Part A.3/B.2's "keep the class name ... as the
    default title") for *which source's own title wins*; a non-generic `title_hint` (Garmin's
    `activityName`) from that source is used verbatim, else a synthesized label."""
    title_priority = title_priority or ["peloton", "concept2", "garmin"]
    by_provenance: dict[str, list[Activity]] = {}
    for m in members:
        by_provenance.setdefault(provenance(m), []).append(m)

    for label in title_priority:
        group = by_provenance.get(label)
        if not group:
            continue
        if label == "peloton":
            real_title = next((m.title_hint for m in group if not _is_generic_garmin_title(m.title_hint, m.type)), None)
            if real_title:
                return real_title.strip()
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
            real_title = next((m.title_hint for m in group if not _is_generic_garmin_title(m.title_hint, m.type)), None)
            if real_title:
                return real_title.strip()
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

    resolved_sport = overrides.get("sport_family") or sport
    canonical.sport_family = resolved_sport
    # Persisted (not recomputed per request) so GET /api/activities' category filter can run
    # entirely in SQL — see the model field's own docstring for why that matters.
    indoor = is_indoor(members[0].source, members[0].type) if members else None
    canonical.category = category_for_canonical(resolved_sport, indoor)
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

    _resolve_zones(session, canonical, members, avg_hr, power_src, settings)

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


def _trim_tail(session: Session, settings: dict, samples: dict) -> float:
    if not settings.get("auto_trim_enabled") or not any(v is not None for v in samples["cadence"]):
        return 0.0
    return detect_trailing_idle(samples["cadence"], settings.get("auto_trim_min_idle_s", 120))


def _resolve_zones(
    session: Session,
    canonical: CanonicalActivity,
    members: list[Activity],
    avg_hr: Optional[float],
    power_member: Optional[Activity],
    settings: dict,
) -> None:
    """HR-based zones/strain (every sport, Part E) and cycling power-based TSS-style strain
    (Part B.3) are resolved independently — the HR-contributing member and the
    power-contributing member can be two *different* source records once a Peloton (power)
    and a watch (HR-only) have been merged, with their own separate sample timelines, so
    there's no single shared "usable_n" to align them on. Power-based strain wins for
    cycling when it's available (task Part B.3's "power-based ... when power exists,
    HR-based otherwise"); HR zones/label still use whichever member has HR, independently."""
    hr_member = next((m for m in members if m.avg_hr == avg_hr and avg_hr is not None), members[0] if members else None)
    hr_samples = _activity_samples(session, hr_member.id) if hr_member and hr_member.id else None
    has_hr = bool(hr_samples) and any(v is not None for v in hr_samples["hr"])

    power_samples = _activity_samples(session, power_member.id) if power_member and power_member.id else None
    has_power = bool(power_samples) and any(v is not None for v in power_samples["power"])

    if not has_hr and not has_power:
        canonical.zones_json = None
        canonical.strain_trimp = None
        canonical.session_label = None
        canonical.auto_trimmed_tail_s = None
        return

    max_hr = settings.get("max_hr")
    hr_zones: dict = {}
    hr_trimp: Optional[float] = None
    hr_moving_s = 0.0
    hr_trimmed_s = 0.0
    if has_hr:
        hr_trimmed_s = _trim_tail(session, settings, hr_samples)
        usable_n = len(hr_samples["hr"]) - int(hr_trimmed_s)
        hr_for_ui = hr_samples["hr"][:usable_n] if hr_trimmed_s else hr_samples["hr"]
        # Part E.2: drop obvious dropouts (0 or flatlined) *before* smoothing/integrating —
        # a stuck sensor must never count as real low-intensity time. Validated against this
        # account's real backfill: ~0.5% of real HR samples get dropped on average, so the
        # default 30s flatline threshold isn't eating legitimate steady-state HR.
        hr_cleaned = drop_dropouts(hr_for_ui)
        hr_zones = time_in_zone_seconds(smooth(hr_cleaned), max_hr, settings)
        hr_moving_s = float(usable_n)
        resting_hr = _resting_hr_for(session, canonical.start)
        hr_trimp = banister_trimp_from_samples(hr_cleaned, resting_hr, max_hr, settings["trimp_exponent"])

    power_zones: Optional[dict] = None
    power_tss: Optional[float] = None
    power_moving_s = 0.0
    if canonical.sport_family == "cycling" and has_power:
        power_trimmed_s = _trim_tail(session, settings, power_samples)
        p_usable_n = len(power_samples["power"]) - int(power_trimmed_s)
        power_for_ui = power_samples["power"][:p_usable_n] if power_trimmed_s else power_samples["power"]
        power_moving_s = float(p_usable_n)

        ftp = settings.get("ftp_watts")
        ftp_is_estimated = False
        if not ftp:
            ftp = estimate_ftp_watts(best_rolling_power(power_for_ui))
            ftp_is_estimated = True
        if ftp:
            power_zones = power_time_in_zone_seconds(smooth(power_for_ui), ftp, settings)
            defined = [v for v in power_for_ui if v is not None]
            avg_power = sum(defined) / len(defined) if defined else None
            power_tss = cycling_tss(power_moving_s, avg_power, ftp)
            canonical.strain_method = "cycling_tss_estimated_ftp" if ftp_is_estimated else "cycling_tss"

    label = _session_label(
        hr_zones, hr_moving_s or power_moving_s, power_zones, settings["min_zone_minutes"], settings["min_zone_pct"]
    )

    # Power-based strain wins for cycling when available; HR Banister trimp otherwise —
    # the two are kept on the same 0-21 log-saturation scale as an approximation (see
    # catch/analytics/cycling_load.py's module docstring).
    trimp = power_tss if power_tss is not None else hr_trimp
    if trimp is not None and power_tss is None:
        canonical.strain_method = "trimp_samples"

    canonical.zones_json = json.dumps({"hr": hr_zones or None, "power": power_zones})
    canonical.strain_trimp = trimp
    canonical.session_label = label
    canonical.auto_trimmed_tail_s = hr_trimmed_s or None


def resolve_all_canonicals(session: Session) -> int:
    """Re-resolves every canonical activity — needed whenever a Settings change could change
    an *already-resolved* canonical's cached fields (max_hr, ftp_watts, field_priority,
    min_zone_minutes/pct, auto_trim_*), none of which `run_matching`'s own resolve calls cover
    (those only touch orphaned, blank, or newly-merged canonicals — a real gap this session's
    own advisor review caught: a Settings-page max_hr change used to silently stop affecting
    any activity's cached strain/zones/label at all). One canonical at a time, each its own
    commit (`resolve_canonical` already commits internally), to stay memory-bounded on the Pi
    even with a long real history (this account's real backfill produced 451 canonicals)."""
    ids = session.exec(select(CanonicalActivity.id)).all()
    for canonical_id in ids:
        resolve_canonical(session, canonical_id)
    return len(ids)
