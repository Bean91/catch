"""Pure mapping helpers for Whoop v2 payloads (see docs/whoop-endpoints.md). No I/O."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from catch.analytics.wellness_inputs import wake_date_for

_OFFSET = re.compile(r"^(?:Z|([+-])(\d{2}):?(\d{2}))$")


def parse_offset_minutes(value: str | None) -> int:
    """Whoop's `timezone_offset` is `+hh:mm`, `-hh:mm` or `Z`. Anything unparseable is treated as
    UTC rather than guessed."""
    m = _OFFSET.match((value or "Z").strip())
    if not m or m.group(1) is None:
        return 0
    minutes = int(m.group(2)) * 60 + int(m.group(3))
    return -minutes if m.group(1) == "-" else minutes


def parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def sleep_wake_date(sleep: dict) -> date | None:
    """The wake day a Whoop sleep belongs to: the local date of its `end`, using that record's own
    `timezone_offset`. Never the cycle's start (the previous evening)."""
    end = parse_instant(sleep.get("end"))
    return wake_date_for(end, parse_offset_minutes(sleep.get("timezone_offset"))) if end else None


# Whoop `sport_name` -> Catch sport family (catch.analytics.matching.SPORT_FAMILIES). Names are
# matched case-insensitively; anything unlisted becomes "other" rather than a guess.
_FAMILY = {
    "rowing": "rowing",
    "running": "running",
    "cycling": "cycling",
    "spinning": "cycling",
    "assault bike": "cycling",
    "weightlifting": "strength",
    "powerlifting": "strength",
    "functional fitness": "strength",
}
_INDOOR = {"spinning": True, "assault bike": True}


def sport_family(sport_name: str | None) -> str:
    return _FAMILY.get((sport_name or "").strip().lower(), "other")


def is_indoor(sport_name: str | None) -> bool | None:
    return _INDOOR.get((sport_name or "").strip().lower())


def kj_to_kcal(kilojoule: float | None) -> float | None:
    return kilojoule / 4.184 if kilojoule is not None else None
