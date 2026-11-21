"""Session 32 (docs/time.md): the pure half of Catch's time-zone rules. No I/O.

Every absolute instant is stored in UTC. A *zone name* is either an IANA identifier ("Europe/Paris") or a fixed UTC offset written
"+09:00"/"-05:30" — what Garmin (local minus GMT start time) and Whoop (`timezone_offset`) give us for a past moment, which is exact
for that moment but carries no daylight-saving rules. A *timeline* is a list of `(start_utc, zone_name)` periods saying where the
athlete was from that instant on. The day a record belongs to is fixed by the zone it happened in, so travelling never moves
history around."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

_OFFSET = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


@lru_cache(maxsize=1)
def iana_names() -> frozenset[str]:
    return frozenset(available_timezones())


def is_valid_iana(name: str | None) -> bool:
    if not name or len(name) > 64 or name in ("localtime", "Factory"):
        return False
    return name in iana_names()


def offset_name(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(int(minutes))
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def parse_offset_minutes(value) -> int | None:
    """'-05:00', '+0530', '+09' or a number of minutes/seconds (Whoop has used both) -> minutes east of UTC, or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = int(value)
        return v // 60 if abs(v) > 18 * 60 else v
    s = str(value).strip()
    if re.fullmatch(r"[+-]\d{2}", s):
        s += ":00"
    m = _OFFSET.match(s)
    if not m:
        return None
    minutes = int(m.group(2)) * 60 + int(m.group(3))
    if minutes > 14 * 60:
        return None
    return -minutes if m.group(1) == "-" else minutes


@lru_cache(maxsize=512)
def tz_for(name: str | None) -> tzinfo | None:
    """The tzinfo for a zone name; None for anything unknown (the caller falls back)."""
    if not name:
        return None
    if name == "UTC":
        return timezone.utc
    minutes = parse_offset_minutes(name)
    if minutes is not None and _OFFSET.match(name):
        return timezone(timedelta(minutes=minutes))
    if not is_valid_iana(name):
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def aware(dt: datetime) -> datetime:
    """A naive datetime is read as UTC: every stored instant in Catch is UTC (never a local wall-clock time)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def utc_offset_minutes(name: str, instant: datetime) -> int | None:
    tz = tz_for(name)
    if tz is None:
        return None
    off = aware(instant).astimezone(tz).utcoffset()
    return int(off.total_seconds() // 60) if off is not None else None


def local_date(instant: datetime, tz: tzinfo) -> date:
    return aware(instant).astimezone(tz).date()


def day_utc_range(day: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day as UTC instants. DST-safe: the end is the next local midnight, so a spring-forward day
    is 23 h and a fall-back day 25 h. A local midnight that doesn't exist (a zone that skips midnight) resolves forward, by
    zoneinfo's fold rules."""
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def local_wall_to_utc(day: date, hour: int, minute: int, tz: tzinfo) -> datetime:
    """A wall-clock time on a local day as a UTC instant. A time skipped by spring-forward lands an hour later (fold=0 maps a
    gap forward); a time repeated by fall-back is the first occurrence."""
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
    return local.astimezone(timezone.utc)


def shift_local_days(instant: datetime, days: int, tz: tzinfo) -> datetime:
    """The same wall-clock time `days` local days later (a copied meal keeps 08:00 across a DST change, unlike +24 h)."""
    local = aware(instant).astimezone(tz)
    target = local.date() + timedelta(days=days)
    return datetime(target.year, target.month, target.day, local.hour, local.minute, local.second, tzinfo=tz).astimezone(timezone.utc)


# --- The timeline ---------------------------------------------------------------------------

DEVICE_GRADE = ("garmin", "whoop", "apple_health", "health_connect", "device")  # observed where the athlete actually was
ACCOUNT_GRADE = ("concept2",)  # a provider *account* setting: right at home, wrong on a hotel erg


@dataclass
class Timeline:
    """Where the athlete was, as periods. `fallback` is used before the first period (and always when `follow` is off):
    the home zone, else the Pi's host zone / UTC."""

    fallback_name: str
    periods: list[tuple[datetime, str]] = field(default_factory=list)
    follow: bool = True

    def __post_init__(self) -> None:
        self.periods = sorted(((aware(s), n) for s, n in self.periods if tz_for(n) is not None), key=lambda p: p[0])
        self._starts = [p[0] for p in self.periods]

    def name_at(self, instant: datetime) -> str:
        if not self.follow or not self.periods:
            return self.fallback_name
        i = bisect_right(self._starts, aware(instant)) - 1
        return self.periods[i][1] if i >= 0 else self.fallback_name

    def tz_at(self, instant: datetime) -> tzinfo:
        return tz_for(self.name_at(instant)) or timezone.utc

    def record_zone(self, instant: datetime, provider_zone: str | None = None, grade: str | None = None) -> str:
        """The zone a record happened in. Priority: a watch/phone-observed offset carried on the record itself > the timeline >
        an account-level provider zone (Concept2) > the fallback. With `follow` off, always the fallback (one zone for all)."""
        if not self.follow:
            return self.fallback_name
        if provider_zone and tz_for(provider_zone) is not None and grade in DEVICE_GRADE:
            return self._prefer_named(provider_zone, instant)
        covered = bool(self.periods) and aware(instant) >= self.periods[0][0]
        if covered:
            return self.name_at(instant)
        if provider_zone and tz_for(provider_zone) is not None:
            return self._prefer_named(provider_zone, instant)
        return self.fallback_name

    def _prefer_named(self, zone: str, instant: datetime) -> str:
        """An offset that equals the timeline's (or the fallback's) IANA zone at that moment is reported under the IANA name,
        so a label reads 'Europe/Paris' rather than '+01:00' and later DST is right."""
        if not _OFFSET.match(zone):
            return zone
        off = utc_offset_minutes(zone, instant)
        for candidate in (self.name_at(instant), self.fallback_name):
            if not _OFFSET.match(candidate) and utc_offset_minutes(candidate, instant) == off:
                return candidate
        return zone

    def local_date(self, instant: datetime, provider_zone: str | None = None, grade: str | None = None) -> tuple[date, str]:
        zone = self.record_zone(instant, provider_zone, grade)
        return local_date(instant, tz_for(zone) or timezone.utc), zone

    def zone_for_day(self, day: date) -> tzinfo:
        """The zone a calendar day is read in when only a day is known (a manual weigh-in date, a date-range filter): the zone
        in effect at that day's noon UTC, which is inside the day for every zone from UTC-12 to UTC+12."""
        return self.tz_at(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc))

    def day_range(self, day: date) -> tuple[datetime, datetime]:
        return day_utc_range(day, self.zone_for_day(day))


def observation_changes_zone(timeline: Timeline, instant: datetime, zone: str) -> bool:
    """True when an observed zone at `instant` disagrees (by UTC offset at that moment) with the timeline."""
    have = utc_offset_minutes(timeline.name_at(instant), instant)
    got = utc_offset_minutes(zone, instant)
    return got is not None and have != got
