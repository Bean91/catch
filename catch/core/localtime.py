"""Session 32 (docs/time.md): the one place Catch decides which local day, and which "today", something belongs to.

Every caller that buckets by day goes through here (a test bans argument-less `date.today()`, `.astimezone()` and `datetime.now()`
elsewhere in catch/). The rules themselves are pure, in catch.analytics.localtime; this module loads the signed-in athlete's
timeline (home zone + follow switch on user_profiles, periods in user_zone_periods) once per database session, stamps
`local_date`/`local_tz` on records as they are written, and grows the timeline from what devices and watches report.

Fallback when the athlete has chosen nothing: the Pi's host zone (so a personal install behaves exactly as before), UTC on the
public build until a phone or browser reports a zone."""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import event, inspect as sa_inspect
from sqlmodel import Session, select

from catch.analytics import localtime as lt
from catch.core import tenant

_CTX_KEY = "catch_timeline"
# The zone the current request last resolved for its owner — for the few pure formatters (a planned workout's "days to go") that
# are handed no session. Never consulted across owners.
_ambient: ContextVar[tuple[str | None, str] | None] = ContextVar("catch_ambient_zone", default=None)
# A phone or browser zone that disagrees with a watch-observed offset this recent is ignored: a laptop left on home time must not
# drag "today" back while the phone and watch are abroad.
DEVICE_CONFLICT_WINDOW = timedelta(hours=12)


# --- Fallback zones -------------------------------------------------------------------------


@lru_cache(maxsize=1)
def host_zone_name() -> str:
    """The Pi's own zone as an IANA name: $TZ, else the /etc/localtime link target, else /etc/timezone, else UTC."""
    tz = os.environ.get("TZ", "").lstrip(":")
    if lt.is_valid_iana(tz):
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            name = target.split("zoneinfo/", 1)[1]
            if lt.is_valid_iana(name):
                return name
    except OSError:
        pass
    try:
        name = Path("/etc/timezone").read_text().strip()
        if lt.is_valid_iana(name):
            return name
    except OSError:
        pass
    return "UTC"


def fallback_zone_name() -> str:
    return "UTC" if tenant.is_public() else host_zone_name()


# --- The per-session timeline ---------------------------------------------------------------


def _profile(session: Session):
    from catch.core.models import UserProfile

    owner = tenant.owner_or_none()
    if owner is None:
        return None
    with session.no_autoflush:
        return session.get(UserProfile, owner)


def timeline(session: Session) -> lt.Timeline:
    cached = session.info.get(_CTX_KEY)
    owner = tenant.owner_or_none()
    if cached is not None and cached[0] == owner:
        return cached[1]
    from catch.core.models import UserZonePeriod

    profile = _profile(session)
    home = profile.timezone if profile is not None and lt.is_valid_iana(profile.timezone) else None
    follow = True if profile is None or profile.follow_device_zone is None else bool(profile.follow_device_zone)
    periods: list[tuple[datetime, str]] = []
    if owner is not None and follow:
        with session.no_autoflush:
            periods = [(p.start_utc, p.tz) for p in session.exec(select(UserZonePeriod).order_by(UserZonePeriod.start_utc)).all()]
    tl = lt.Timeline(fallback_name=home or fallback_zone_name(), periods=periods, follow=follow)
    session.info[_CTX_KEY] = (owner, tl)
    _ambient.set((owner, tl.name_at(_now())))
    return tl


def ambient_zone_name() -> str:
    v = _ambient.get()
    return v[1] if v is not None and v[0] == tenant.owner_or_none() else fallback_zone_name()


def ambient_today(now: datetime | None = None) -> date:
    return lt.local_date(now or _now(), lt.tz_for(ambient_zone_name()) or timezone.utc)


def invalidate(session: Session) -> None:
    session.info.pop(_CTX_KEY, None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def current_zone_name(session: Session, now: datetime | None = None) -> str:
    return timeline(session).name_at(now or _now())


def current_tz(session: Session, now: datetime | None = None):
    return lt.tz_for(current_zone_name(session, now)) or timezone.utc


def today(session: Session, now: datetime | None = None) -> date:
    now = now or _now()
    return lt.local_date(now, timeline(session).tz_at(now))


def now_local(session: Session, now: datetime | None = None) -> datetime:
    now = now or _now()
    return now.astimezone(timeline(session).tz_at(now))


def local_date_at(session: Session, instant: datetime) -> date:
    """The local day of a bare instant with no record attached (a notification's send time, a coach usage event)."""
    return lt.local_date(instant, timeline(session).tz_at(instant))


def day_range(session: Session, day: date) -> tuple[datetime, datetime]:
    return timeline(session).day_range(day)


def zone_for_day(session: Session, day: date):
    return timeline(session).zone_for_day(day)


def naive_to_utc(session: Session, value: datetime | None) -> datetime | None:
    """A `?from=`/`?to=` query value: an aware datetime is taken as given; a naive one (including a bare date) is the athlete's
    local wall-clock time, never silently UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=zone_for_day(session, value.date())).astimezone(timezone.utc)


def date_bounds(session: Session, from_day: date | None, to_day: date | None) -> tuple[datetime | None, datetime | None]:
    """A `?from=…&to=…` pair of local calendar days as an inclusive-from / exclusive-to pair of UTC instants."""
    lo = day_range(session, from_day)[0] if from_day else None
    hi = day_range(session, to_day)[1] if to_day else None
    return lo, hi


# --- What a record says about its own zone --------------------------------------------------


def _garmin_offset(raw: dict) -> int | None:
    local, gmt = raw.get("startTimeLocal"), raw.get("startTimeGMT")
    if not local or not gmt:
        return None
    parsed = []
    for value in (local, gmt):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                parsed.append(datetime.strptime(str(value), fmt))
                break
            except ValueError:
                continue
    if len(parsed) != 2:
        return None
    minutes = round((parsed[0] - parsed[1]).total_seconds() / 60 / 15) * 15
    return minutes if abs(minutes) <= 14 * 60 else None


def activity_provider_zone(source: str | None, raw_json: str | None) -> tuple[str | None, str | None]:
    """(zone name, grade) a source record carries about where it happened, or (None, None). Garmin's local-minus-GMT start and
    Whoop's `timezone_offset` are watch/phone observations ('device' grade); Concept2's `timezone` is an account setting."""
    if not raw_json or not source:
        return None, None
    try:
        raw = json.loads(raw_json)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(raw, dict):
        return None, None
    if source == "garmin":
        minutes = _garmin_offset(raw)
        return (lt.offset_name(minutes), "garmin") if minutes is not None else (None, None)
    if source == "whoop":
        minutes = lt.parse_offset_minutes(raw.get("timezone_offset"))
        return (lt.offset_name(minutes), "whoop") if minutes is not None else (None, None)
    if source == "concept2":
        name = raw.get("timezone")
        return (name, "concept2") if lt.is_valid_iana(name) else (None, None)
    if source in ("apple_health", "health_connect"):
        minutes = lt.parse_offset_minutes(raw.get("utc_offset_minutes"))
        return (lt.offset_name(minutes), source) if minutes is not None else (None, None)
    return None, None


def stamp(session: Session, row) -> None:
    """Set `local_date`/`local_tz` on an Activity, FoodLog or BodyComp from its own instant. A canonical is stamped by
    `stamp_canonical` from its members."""
    from catch.core.models import Activity, BodyComp, FoodLog

    if isinstance(row, Activity):
        if row.start is None:
            return
        zone, grade = activity_provider_zone(row.source, row.raw_json)
        row.local_date, row.local_tz = timeline(session).local_date(row.start, zone, grade)
    elif isinstance(row, (FoodLog, BodyComp)):
        if row.ts is None:
            return
        row.local_date, row.local_tz = timeline(session).local_date(row.ts)


_GRADE_RANK = {g: 0 for g in lt.DEVICE_GRADE} | {g: 2 for g in lt.ACCOUNT_GRADE}


def stamp_canonical(session: Session, canonical, members=None) -> None:
    """A canonical takes its day from the athlete's "Change day" override, else the best member: a watch-observed zone beats the
    timeline beats an account zone."""
    if canonical.start is None:
        canonical.local_date, canonical.local_tz = None, None
        return
    overrides = {}
    if canonical.overrides_json:
        try:
            overrides = json.loads(canonical.overrides_json) or {}
        except (TypeError, ValueError):
            overrides = {}
    best_zone, best_grade, best_rank = None, None, 9
    for m in members or ():
        zone, grade = activity_provider_zone(m.source, m.raw_json)
        rank = _GRADE_RANK.get(grade or "", 9)
        if zone and rank < best_rank:
            best_zone, best_grade, best_rank = zone, grade, rank
    day, zone = timeline(session).local_date(canonical.start, best_zone, best_grade)
    override = overrides.get("local_date")
    if override:
        try:
            day = date.fromisoformat(str(override))
        except ValueError:
            pass
    canonical.local_date, canonical.local_tz = day, zone


def day_of(session: Session, row) -> date | None:
    """A record's local day: its stamp, else computed now (rows written before session 32's backfill ran)."""
    if getattr(row, "local_date", None) is not None:
        return row.local_date
    instant = getattr(row, "start", None) or getattr(row, "ts", None)
    if instant is None:
        return None
    return timeline(session).local_date(instant)[0]


# --- Growing the timeline -------------------------------------------------------------------


def _insert_period(session: Session, start: datetime, zone: str, source: str) -> bool:
    from catch.core.models import UserZonePeriod

    tl = timeline(session)
    start = lt.aware(start)
    if not lt.observation_changes_zone(tl, start, zone):
        _maybe_upgrade_name(session, start, zone)
        return False
    session.add(UserZonePeriod(start_utc=start, tz=zone, source=source))
    session.flush()
    invalidate(session)
    _restamp_window(session, start)
    return True


def _maybe_upgrade_name(session: Session, instant: datetime, zone: str) -> None:
    """An offset-only period ('+09:00') whose offset an IANA report now matches becomes that IANA name (DST rules from then on)."""
    from catch.core.models import UserZonePeriod

    if lt.tz_for(zone) is None or not lt.is_valid_iana(zone):
        return
    rows = session.exec(select(UserZonePeriod).where(UserZonePeriod.start_utc <= instant).order_by(UserZonePeriod.start_utc.desc())).first()
    if rows is not None and not lt.is_valid_iana(rows.tz) and lt.utc_offset_minutes(rows.tz, instant) == lt.utc_offset_minutes(zone, instant):
        rows.tz = zone
        session.add(rows)
        session.flush()
        invalidate(session)


def observe(session: Session, instant: datetime | None, zone: str | None, source: str) -> bool:
    """A watch or phone recorded `zone` at `instant` (a workout's start, a night's wake-up). Opens a period if that disagrees with
    the timeline; past records from then until the next period are re-stamped and their days recomputed. Returns whether it did."""
    if instant is None or not zone or lt.tz_for(zone) is None or tenant.owner_or_none() is None:
        return False
    tl = timeline(session)
    if not tl.follow:
        return False
    named = tl._prefer_named(zone, instant)
    return _insert_period(session, instant, named, source)


def report_device_zone(session: Session, zone: str, now: datetime | None = None) -> dict:
    """The app (web or native) reports the phone/computer's IANA zone on open. Starts a period now unless it would contradict a
    watch observation from the last 12 h (a laptop still on home time while the athlete is abroad)."""
    from catch.core.models import UserZonePeriod

    now = now or _now()
    if not lt.is_valid_iana(zone):
        raise ValueError("unknown time zone")
    tl = timeline(session)
    changed = False
    if tl.follow and lt.observation_changes_zone(tl, now, zone):
        recent = session.exec(
            select(UserZonePeriod).where(UserZonePeriod.start_utc >= now - DEVICE_CONFLICT_WINDOW, UserZonePeriod.source != "device")
            .order_by(UserZonePeriod.start_utc.desc())
        ).first()
        if recent is None or lt.utc_offset_minutes(recent.tz, now) == lt.utc_offset_minutes(zone, now):
            changed = _insert_period(session, now, zone, "device")
    elif tl.follow:
        _maybe_upgrade_name(session, now, zone)
    session.commit()
    return {"changed": changed, "current_zone": current_zone_name(session, now), "today": today(session, now).isoformat()}


def _observations(session: Session, updated_since: datetime | None) -> list[tuple[datetime, str, str]]:
    """(instant, zone, source) a watch or phone recorded: a workout's start (Garmin, Whoop, phone health) and a night's wake-up (a
    Whoop sleep's offset). Concept2's account zone is not an observation of where the athlete was."""
    from sqlalchemy.orm import load_only

    from catch.core.models import Activity, WellnessReading

    out: list[tuple[datetime, str, str]] = []
    stmt = select(Activity).options(load_only(Activity.id, Activity.source, Activity.start, Activity.raw_json)).where(
        Activity.source.in_(("garmin", "whoop", "apple_health", "health_connect")), Activity.start.is_not(None)
    )
    if updated_since is not None:
        stmt = stmt.where(Activity.updated_at >= updated_since)
    for a in session.exec(stmt).all():
        zone, grade = activity_provider_zone(a.source, a.raw_json)
        if zone and grade in lt.DEVICE_GRADE:
            out.append((lt.aware(a.start), zone, a.source))
    stmt = select(WellnessReading).where(WellnessReading.recorded_at.is_not(None), WellnessReading.meta_json.is_not(None))
    if updated_since is not None:
        stmt = stmt.where(WellnessReading.fetched_at >= updated_since)
    for r in session.exec(stmt).all():
        try:
            minutes = lt.parse_offset_minutes((json.loads(r.meta_json) or {}).get("timezone_offset"))
        except (TypeError, ValueError):
            minutes = None
        if minutes is not None:
            out.append((lt.aware(r.recorded_at), lt.offset_name(minutes), r.source))
    out.sort(key=lambda o: o[0])
    return out


def learn_from_records(session: Session, updated_since: datetime | None = None) -> int:
    """Grow the timeline from what watches recorded on records synced since `updated_since` (all history when None). Periods are
    planned in memory and inserted together, then records from the earliest change on are re-stamped once — so a three-year
    history is one pass, not one re-stamp per trip. Returns the number of periods added."""
    from catch.core.models import UserZonePeriod

    if tenant.owner_or_none() is None:
        return 0
    tl = timeline(session)
    if not tl.follow:
        return 0
    planned = list(tl.periods)
    added: list[tuple[datetime, str, str]] = []
    for instant, zone, source in _observations(session, updated_since):
        probe = lt.Timeline(fallback_name=tl.fallback_name, periods=planned, follow=True)
        if not lt.observation_changes_zone(probe, instant, zone):
            continue
        named = probe._prefer_named(zone, instant)
        planned.append((instant, named))
        added.append((instant, named, source))
    if not added:
        return 0
    for instant, zone, source in added:
        session.add(UserZonePeriod(start_utc=instant, tz=zone, source=source))
    session.flush()
    invalidate(session)
    restamp(session, since=min(a[0] for a in added))
    return len(added)


def needs_backfill(session: Session) -> bool:
    from catch.core.models import Activity, BodyComp, CanonicalActivity, FoodLog

    for model, col in ((Activity, Activity.start), (CanonicalActivity, CanonicalActivity.start), (FoodLog, FoodLog.ts), (BodyComp, BodyComp.ts)):
        if session.exec(select(model.id).where(model.local_date.is_(None), col.is_not(None)).limit(1)).first() is not None:
            return True
    return False


def ensure_backfilled(session: Session) -> bool:
    """Session 32's one-time upgrade for data written before per-record days existed: learn the timeline from the whole history,
    stamp every record, and leave a full recompute pending. Idempotent — a no-op (one small query per table) once done."""
    if tenant.owner_or_none() is None or not needs_backfill(session):
        return False
    from catch.core.models import UserZonePeriod

    if session.exec(select(UserZonePeriod.id).where(UserZonePeriod.source != "device").limit(1)).first() is None:
        learn_from_records(session, None)
    restamp(session)
    session.commit()
    return True


# --- Re-stamping ----------------------------------------------------------------------------


def _restamp_window(session: Session, start: datetime) -> None:
    """Re-stamp the records from `start` to the next period, and note the earliest day whose scores must be recomputed."""
    from catch.core.models import UserZonePeriod

    nxt = session.exec(select(UserZonePeriod.start_utc).where(UserZonePeriod.start_utc > start).order_by(UserZonePeriod.start_utc)).first()
    restamp(session, since=start, until=nxt)


def restamp(session: Session, since: datetime | None = None, until: datetime | None = None) -> date | None:
    """Re-stamp every Activity, canonical, food log and weigh-in in [since, until). Returns the earliest local day that changed,
    and records it so the caller's next recompute starts there (`pending_recompute_from`)."""
    from catch.core.models import Activity, BodyComp, CanonicalActivity, FoodLog

    invalidate(session)
    earliest: date | None = None
    for model, col in ((Activity, Activity.start), (FoodLog, FoodLog.ts), (BodyComp, BodyComp.ts)):
        stmt = select(model).where(col.is_not(None))
        if since is not None:
            stmt = stmt.where(col >= since)
        if until is not None:
            stmt = stmt.where(col < until)
        for row in session.exec(stmt).all():
            before = row.local_date
            stamp(session, row)
            if row.local_date != before:
                session.add(row)
                for d in (before, row.local_date):
                    if d is not None and (earliest is None or d < earliest):
                        earliest = d
    session.flush()
    stmt = select(CanonicalActivity).where(CanonicalActivity.start.is_not(None))
    if since is not None:
        stmt = stmt.where(CanonicalActivity.start >= since)
    if until is not None:
        stmt = stmt.where(CanonicalActivity.start < until)
    canonicals = session.exec(stmt).all()
    members_by_c: dict[int, list] = {}
    if canonicals:
        ids = [c.id for c in canonicals]
        for i in range(0, len(ids), 500):
            for a in session.exec(select(Activity).where(Activity.canonical_id.in_(ids[i : i + 500]))).all():
                members_by_c.setdefault(a.canonical_id, []).append(a)
    for c in canonicals:
        before = c.local_date
        stamp_canonical(session, c, members_by_c.get(c.id, ()))
        if c.local_date != before:
            session.add(c)
            for d in (before, c.local_date):
                if d is not None and (earliest is None or d < earliest):
                    earliest = d
    session.flush()
    if earliest is not None:
        mark_recompute_from(session, earliest)
    return earliest


def mark_recompute_from(session: Session, day: date) -> None:
    prev = session.info.get("catch_recompute_from")
    session.info["catch_recompute_from"] = day if prev is None or day < prev else prev


def pending_recompute_from(session: Session) -> date | None:
    return session.info.pop("catch_recompute_from", None)


# --- Settings: home zone and follow switch --------------------------------------------------


def set_preferences(session: Session, *, home: str | None = ..., follow: bool | None = ...) -> dict:
    """Change the home zone and/or the follow switch. Records are re-stamped (their absolute times never change) and the
    derived days recomputed by the caller from `pending_recompute_from`."""
    from catch.core.models import UserProfile

    owner = tenant.current_owner()
    profile = session.get(UserProfile, owner)
    if profile is None:
        profile = UserProfile(id=owner)
    if home is not ...:
        if home is not None and not lt.is_valid_iana(home):
            raise ValueError("unknown time zone")
        profile.timezone = home
    if follow is not ...:
        profile.follow_device_zone = follow
    session.add(profile)
    session.flush()
    invalidate(session)
    restamp(session)
    session.commit()
    return preferences(session)


def preferences(session: Session) -> dict:
    profile = _profile(session)
    tl = timeline(session)
    now = _now()
    return {
        "timezone": profile.timezone if profile is not None else None,
        "follow_device_zone": tl.follow,
        "current_zone": tl.name_at(now),
        "fallback_zone": fallback_zone_name(),
        "today": today(session, now).isoformat(),
    }


# --- Write-time stamping (installed on Session, like tenant_hooks) -------------------------

_installed = False


def _instant_changed(obj, attr: str) -> bool:
    try:
        return sa_inspect(obj).attrs[attr].history.has_changes()
    except Exception:
        return False


def _before_flush(session: Session, flush_context, instances) -> None:
    if tenant.owner_or_none() is None or session.info.get("catch_no_stamp"):
        return
    from catch.core.models import Activity, BodyComp, CanonicalActivity, FoodLog

    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Activity):
            if obj.start is not None and (obj.local_date is None or _instant_changed(obj, "start") or _instant_changed(obj, "raw_json")):
                stamp(session, obj)
        elif isinstance(obj, (FoodLog, BodyComp)):
            if obj.ts is not None and (obj.local_date is None or _instant_changed(obj, "ts")):
                stamp(session, obj)
        elif isinstance(obj, CanonicalActivity):
            if obj.start is not None and obj.local_date is None:
                stamp_canonical(session, obj)


def install() -> None:
    global _installed
    if _installed:
        return
    event.listen(Session, "before_flush", _before_flush)
    _installed = True
