"""Session 30 (docs/mobile/health-data.md): pure rules for importing from Apple Health / Health Connect. No I/O.

Three jobs: (1) decide whether an incoming record is really ANOTHER provider's data that Catch already fetches from the source
(Garmin Connect writes every workout to Apple Health, Withings writes its weigh-ins, Whoop its workouts) — importing it again would
double a session; (2) validate what the phone sent, because the client is untrusted; (3) map a platform workout type onto Catch's
sport families. Provenance is never dropped: the originating app is kept on every imported row."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

SOURCES = ("apple_health", "health_connect")
CATEGORIES = ("workouts", "sleep", "resting_hr", "spo2", "hrv")
# HealthKit's variability measure is SDNN; Catch's recovery formula is built on RMSSD (analytics/wellness_inputs.py). They are not
# interchangeable, so Apple Health can never supply `hrv`; Health Connect's HeartRateVariabilityRmssd is RMSSD and can.
CATEGORIES_BY_SOURCE = {
    "apple_health": ("workouts", "sleep", "resting_hr", "spo2"),
    "health_connect": ("workouts", "sleep", "resting_hr", "spo2", "hrv"),
}
MAX_WORKOUTS_PER_REQUEST = 200
MAX_READINGS_PER_REQUEST = 500
MAX_HISTORY_DAYS = 400
MAX_ORIGIN_CHARS = 120

# Substrings (lower-cased, matched against the originating app's name and id) of apps whose data belongs to a provider Catch syncs
# directly. A record from one of them is skipped while that provider is connected, and imported (labelled) when it is not.
PROVIDER_APP_MARKERS: dict[str, tuple[str, ...]] = {
    "garmin": ("garmin",),
    "withings": ("withings", "health mate", "healthmate"),
    "concept2": ("concept2", "concept 2", "logbook"),
    "whoop": ("whoop",),
}


def duplicate_of(origin_app: Optional[str], origin_id: Optional[str], connected: set[str]) -> Optional[str]:
    """The connected provider this record duplicates, or None."""
    haystack = f"{origin_app or ''} {origin_id or ''}".lower()
    for provider, markers in PROVIDER_APP_MARKERS.items():
        if provider in connected and any(m in haystack for m in markers):
            return provider
    return None


_FAMILY = {
    "rowing": "rowing", "rowingMachine": "rowing", "paddling": "rowing", "paddleSports": "rowing",
    "running": "running", "runningTreadmill": "running", "walking": "running", "hiking": "running", "trackAndField": "running",
    "cycling": "cycling", "bikingStationary": "cycling", "handCycling": "cycling",
    "strengthTraining": "strength", "traditionalStrengthTraining": "strength", "functionalStrengthTraining": "strength", "weightlifting": "strength",
    "crossTraining": "strength", "coreTraining": "strength", "calisthenics": "strength", "benchPress": "strength", "deadlift": "strength",
}
_INDOOR = {"rowingMachine": True, "runningTreadmill": True, "bikingStationary": True}


def sport_family(workout_type: Optional[str]) -> str:
    return _FAMILY.get(workout_type or "", "other")


def is_indoor(workout_type: Optional[str]) -> Optional[bool]:
    return _INDOOR.get(workout_type or "")


class Invalid(ValueError):
    """A record the server refuses; the text is fixed and never echoes the submitted value."""


def _num(v: Any, lo: float, hi: float, what: str, *, required: bool = False) -> Optional[float]:
    if v is None:
        if required:
            raise Invalid(f"{what} is missing")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise Invalid(f"{what} is not a number")
    if not lo <= float(v) <= hi:
        raise Invalid(f"{what} is out of range")
    return float(v)


def parse_instant(v: Any, what: str) -> datetime:
    if not isinstance(v, str) or len(v) > 40:
        raise Invalid(f"{what} is not a time")
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise Invalid(f"{what} is not a time") from None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso_offset_minutes(v: Any) -> Optional[int]:
    """The UTC offset a phone wrote into a workout's local start time ("…T07:00:00+09:00"), kept so the workout's day is the day
    where it happened (session 32, docs/time.md). None for "Z"/UTC-only or offset-less strings: nothing was said about the zone."""
    if not isinstance(v, str) or v.endswith("Z"):
        return None
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    off = d.utcoffset()
    return int(off.total_seconds() // 60) if off is not None else None


def _text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise Invalid("a label is not text")
    return v.strip()[:MAX_ORIGIN_CHARS] or None


def validate_workout(w: dict, *, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ext = w.get("external_id")
    if not isinstance(ext, str) or not 1 <= len(ext) <= 200:
        raise Invalid("a workout has no id")
    start, end = parse_instant(w.get("start"), "start"), parse_instant(w.get("end"), "end")
    offset = _iso_offset_minutes(w.get("start"))
    if end <= start or end - start > timedelta(hours=24):
        raise Invalid("a workout's length is not plausible")
    if start > now + timedelta(hours=1) or start < now - timedelta(days=MAX_HISTORY_DAYS):
        raise Invalid("a workout is outside the importable range")
    avg_hr, max_hr = _num(w.get("avg_hr"), 30, 250, "average heart rate"), _num(w.get("max_hr"), 30, 250, "max heart rate")
    if avg_hr is not None and max_hr is not None and avg_hr > max_hr:
        raise Invalid("average heart rate is above max")
    return {
        "external_id": ext, "type": _text(w.get("type")) or "other", "start": start, "duration": (end - start).total_seconds(),
        "distance": _num(w.get("distance_m"), 0, 500_000, "distance"), "calories": _num(w.get("energy_kcal"), 0, 20_000, "energy"),
        "avg_hr": avg_hr, "max_hr": max_hr, "origin_app": _text(w.get("origin_app")), "origin_id": _text(w.get("origin_id")),
        "utc_offset_minutes": offset,
    }


# category -> (Catch wellness signal, plausible range). Sleep is handled separately (stages ride along as meta).
_READING_SIGNALS = {"resting_hr": ("resting_hr", 25, 120), "spo2": ("spo2", 70, 100), "hrv": ("hrv_rmssd", 5, 300)}


def validate_reading(r: dict, *, today: Optional[date] = None) -> dict:
    cat = r.get("category")
    day_text = r.get("date")
    try:
        day = date.fromisoformat(day_text) if isinstance(day_text, str) and len(day_text) == 10 else None
    except ValueError:
        day = None
    if day is None:
        raise Invalid("a reading has no date")
    today = today or datetime.now(timezone.utc).date()
    if day > today + timedelta(days=1) or day < today - timedelta(days=MAX_HISTORY_DAYS):
        raise Invalid("a reading is outside the importable range")
    origin = {"origin_app": _text(r.get("origin_app")), "origin_id": _text(r.get("origin_id"))}
    if cat == "sleep":
        total = _num(r.get("sleep_seconds"), 1800, 20 * 3600, "sleep", required=True)
        stages = {k: _num(r.get(k), 0, 20 * 3600, k) for k in ("deep_sleep_seconds", "light_sleep_seconds", "rem_sleep_seconds", "awake_sleep_seconds")}
        return {"category": "sleep", "date": day, "signal": "sleep_seconds", "value": total, "meta": {k: v for k, v in stages.items() if v is not None}, **origin}
    if cat not in _READING_SIGNALS:
        raise Invalid("an unknown reading type")
    signal, lo, hi = _READING_SIGNALS[cat]
    return {"category": cat, "date": day, "signal": signal, "value": _num(r.get("value"), lo, hi, "a reading", required=True), "meta": {}, **origin}
