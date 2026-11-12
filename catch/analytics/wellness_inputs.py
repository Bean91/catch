"""Provider-independent recovery inputs: the normalized signal model, the deterministic rule for
picking one provider's value per signal per day, and the data-availability/calibration report.

Pure functions, no I/O (catch/sync/wellness_readings.py is the DB half). Catch's recovery formula
(catch/analytics/recovery.py, docs/analytics.md §6) consumes these signals and nothing else; it
never reads a provider's own recovery score. See docs/analytics.md §30.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from catch.analytics.recovery import recovery_score

# Signal name -> (DailyWellness column the winning value is written to, plausible range).
SIGNALS: dict[str, tuple[str, tuple[float, float]]] = {
    "hrv_rmssd": ("hrv_rmssd", (5.0, 300.0)),  # ms, overnight RMSSD
    "resting_hr": ("resting_hr", (25.0, 120.0)),  # bpm
    "sleep_seconds": ("sleep_seconds", (1800.0, 20 * 3600.0)),
    "sleep_respiration": ("sleep_respiration_avg", (4.0, 40.0)),  # breaths/min, overnight
    "skin_temp_c": ("skin_temp_c", (20.0, 45.0)),
    "spo2": ("spo2", (70.0, 100.0)),
}

# Used for the sleep reading's stage breakdown and wake time, carried in Reading.meta.
SLEEP_META_COLUMNS = {
    "deep_sleep_seconds": "deep_sleep_seconds",
    "light_sleep_seconds": "light_sleep_seconds",
    "rem_sleep_seconds": "rem_sleep_seconds",
    "awake_sleep_seconds": "awake_sleep_seconds",
    "wake_time_minutes": "wake_time_minutes",
}

# Garmin first, so a Pi that has always run on Garmin keeps its scores exactly as they were.
# Skin temperature has no Garmin source, so the order only matters if one appears. Whoop's
# respiratory rate has no documented unit, so it ranks below Garmin's.
DEFAULT_WELLNESS_PRIORITY: dict[str, list[str]] = {
    "hrv_rmssd": ["garmin", "whoop"],
    "resting_hr": ["garmin", "whoop"],
    "sleep_seconds": ["garmin", "whoop"],
    "sleep_respiration": ["garmin", "whoop"],
    "skin_temp_c": ["whoop", "garmin"],
    "spo2": ["garmin", "whoop"],
}


@dataclass(frozen=True)
class Reading:
    source: str
    signal: str
    value: float
    fetched_at: datetime | None = None
    recorded_at: datetime | None = None
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Resolved:
    signal: str
    value: float
    source: str
    meta: dict
    alternatives: tuple[tuple[str, float], ...]  # other providers' plausible values, for display only
    conflict: bool  # providers disagree by more than the tolerance below


# Relative disagreement between two providers' values above which a day is flagged. Display only —
# the resolver never averages.
CONFLICT_TOLERANCE = {"hrv_rmssd": 0.35, "resting_hr": 0.10, "sleep_seconds": 0.20, "sleep_respiration": 0.25, "skin_temp_c": 0.05, "spo2": 0.03}


def is_plausible(signal: str, value: float | None) -> bool:
    if value is None or signal not in SIGNALS:
        return False
    lo, hi = SIGNALS[signal][1]
    return lo <= value <= hi


def _rank(source: str, order: list[str]) -> tuple[int, str]:
    # Listed sources by their position; an unlisted source after all of them, alphabetically, so the
    # order is total and the choice never depends on row order.
    return (order.index(source), source) if source in order else (len(order), source)


def resolve_signal(readings: list[Reading], priority: list[str]) -> Resolved | None:
    """One winner per signal per day: the highest-priority provider with a plausible value. Values
    from different providers are never averaged or summed — that is the no-double-counting rule."""
    usable = [r for r in readings if is_plausible(r.signal, r.value)]
    if not usable:
        return None
    usable.sort(key=lambda r: _rank(r.source, priority))
    winner = usable[0]
    others = tuple((r.source, r.value) for r in usable[1:])
    tol = CONFLICT_TOLERANCE.get(winner.signal, 0.25)
    conflict = any(abs(v - winner.value) / max(abs(winner.value), 1e-9) > tol for _, v in others)
    return Resolved(winner.signal, winner.value, winner.source, dict(winner.meta), others, conflict)


def pick_main_sleep(records: list[dict]) -> dict | None:
    """From one provider's sleep records that end on the same wake day, the main sleep: naps are
    excluded and the longest remaining record wins (ties: the later end). Each record needs
    `nap`, `seconds` and `end`."""
    candidates = [r for r in records if not r.get("nap") and (r.get("seconds") or 0) > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r["seconds"], r["end"]))


# -- Recovery inputs and report ------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryInputs:
    today_ln_hrv: float | None = None
    hrv_history_ln: list[float] = field(default_factory=list)
    today_resting_hr: float | None = None
    rhr_history: list[float] = field(default_factory=list)
    today_sleep_seconds: float | None = None
    prior_day_strain: float | None = None
    today_checkin_score: float | None = None


def recovery_from_inputs(inputs: RecoveryInputs, settings: dict) -> dict:
    return recovery_score(
        today_ln_hrv=inputs.today_ln_hrv,
        hrv_history_ln=inputs.hrv_history_ln,
        today_resting_hr=inputs.today_resting_hr,
        rhr_history=inputs.rhr_history,
        today_sleep_seconds=inputs.today_sleep_seconds,
        prior_day_strain=inputs.prior_day_strain,
        today_checkin_score=inputs.today_checkin_score,
        settings=settings,
    )


def baseline_mixed(sources_by_night: list[str | None], window: int = 7) -> bool:
    """True when the most recent `window` nights of a signal came from more than one provider — a
    baseline built that way compares one device's number against another's."""
    recent = [s for s in sources_by_night[-window:] if s]
    return len(set(recent)) > 1


def calibration_status(hrv_nights: int, settings: dict) -> dict:
    required = settings["min_hrv_nights_for_baseline"]
    return {
        "status": "calibrated" if hrv_nights >= required else "calibrating",
        "nights": hrv_nights,
        "required": required,
        "nights_remaining": max(required - hrv_nights, 0),
    }


def data_availability(
    *,
    today: dict[str, tuple[float | None, str | None]],
    history_counts: dict[str, int],
    prior_strain_available: bool,
    checkin_available: bool,
    settings: dict,
) -> list[dict]:
    """Per signal: is there a value today, which provider supplied it, and how many prior nights the
    baseline has. `in_score` says whether Catch's formula uses the signal at all."""
    need = settings["min_hrv_nights_for_baseline"]
    rows = []
    for signal, in_score, label in (
        ("hrv_rmssd", True, "Overnight HRV"),
        ("resting_hr", True, "Resting heart rate"),
        ("sleep_seconds", True, "Sleep duration"),
        ("sleep_respiration", False, "Sleep respiration"),
        ("skin_temp_c", False, "Skin temperature"),
        ("spo2", False, "Blood oxygen"),
    ):
        value, source = today.get(signal, (None, None))
        rows.append(
            {
                "signal": signal,
                "label": label,
                "available": value is not None,
                "source": source,
                "baseline_nights": history_counts.get(signal, 0),
                "baseline_needed": need if signal == "hrv_rmssd" else None,
                "in_score": in_score,
            }
        )
    rows.append({"signal": "prior_strain", "label": "Yesterday's strain", "available": prior_strain_available, "source": "catch", "baseline_nights": None, "baseline_needed": None, "in_score": True})
    rows.append({"signal": "checkin", "label": "Morning check-in", "available": checkin_available, "source": "you", "baseline_nights": None, "baseline_needed": None, "in_score": True})
    return rows


def wake_date_for(end: datetime, tz_offset_minutes: int) -> date:
    """The local calendar date a sleep that ended at `end` (a tz-aware instant) belongs to — the
    same wake-day convention Garmin's `calendarDate` uses."""
    return (end + timedelta(minutes=tz_offset_minutes)).date()
