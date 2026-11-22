from __future__ import annotations

from catch.core import tenant
import json
from copy import deepcopy
from datetime import date, datetime, timezone

from sqlmodel import Session

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.core.models import AppSettings

SETTINGS_ID = 1

_ALLOWED_VALUES = {"zone_mode": {"hr", "power"}, "units": {"metric", "imperial"}, "hr_zone_method": {"hrr", "max_pct"}}
_ZONE_ORDER = ("UT2", "UT1", "AT", "TR", "AN")


def _validate_heart_rate(patch: dict, merged: dict, before: dict) -> None:
    """Session 33: the values heart-rate zones are built from. Checked on the merged result, so a patch can't leave max and
    resting heart rate inconsistent with each other — but only for values this patch actually changes: Settings saves its whole
    form, and a value stored before these rules existed (say a max HR seeded from a provider) must not block an unrelated save."""
    def number(v) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    patch = {k: v for k, v in patch.items() if before.get(k) != merged.get(k)}

    max_hr, rest = merged.get("max_hr"), merged.get("resting_hr")
    if "max_hr" in patch and max_hr is not None and not (number(max_hr) and 120 <= max_hr <= 230):
        raise ValueError("Max heart rate must be between 120 and 230 bpm.")
    if "resting_hr" in patch and rest is not None and not (number(rest) and 30 <= rest <= 100):
        raise ValueError("Resting heart rate must be between 30 and 100 bpm.")
    if ("max_hr" in patch or "resting_hr" in patch) and number(max_hr) and number(rest) and max_hr - rest < 40:
        raise ValueError("Max heart rate must be at least 40 bpm above resting heart rate.")
    if "zones" in patch:
        for table in ("hr_pct", "hrr_pct", "power_pct"):
            if merged["zones"][table] == before["zones"][table]:
                continue
            values = [merged["zones"][table].get(z) for z in _ZONE_ORDER]
            if not all(number(v) and 0 < v <= 150 for v in values) or any(b <= a for a, b in zip(values, values[1:])):
                raise ValueError(f"Zone percentages ({table}) must be numbers that increase from UT2 to AN.")
            if table != "power_pct" and values[-1] > 100:
                raise ValueError("Heart-rate zone percentages can't be above 100.")


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


_MAINTENANCE = "_maintenance"  # one-time data upgrades done for this owner; never a user setting (a PUT naming it is an unknown key)


def get_settings(session: Session) -> dict:
    row = session.get(AppSettings, tenant.pk(SETTINGS_ID))
    overrides = json.loads(row.data_json) if row and row.data_json else {}
    overrides.pop(_MAINTENANCE, None)
    return _deep_merge(DEFAULT_SETTINGS, overrides)


def maintenance_marker(session: Session, key: str) -> int:
    row = session.get(AppSettings, tenant.pk(SETTINGS_ID))
    data = json.loads(row.data_json) if row and row.data_json else {}
    return int((data.get(_MAINTENANCE) or {}).get(key) or 0)


def set_maintenance_marker(session: Session, key: str, value: int) -> None:
    """Recorded beside the settings, in the caller's transaction (committed with the upgrade it marks)."""
    row = session.get(AppSettings, tenant.pk(SETTINGS_ID))
    if row is None:
        row = AppSettings(id=SETTINGS_ID, data_json="{}")
        session.add(row)
    data = json.loads(row.data_json) if row.data_json else {}
    data.setdefault(_MAINTENANCE, {})[key] = value
    row.data_json = json.dumps(data)


def _validate_patch(patch: dict) -> None:
    unknown = set(patch) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ValueError(f"Unknown setting key(s): {sorted(unknown)}")
    for key, value in patch.items():
        if isinstance(DEFAULT_SETTINGS[key], dict):
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be an object")
            unknown_nested = set(value) - set(DEFAULT_SETTINGS[key])
            if unknown_nested:
                raise ValueError(f"Unknown key(s) under {key}: {sorted(unknown_nested)}")
        elif key in _ALLOWED_VALUES and value not in _ALLOWED_VALUES[key]:
            raise ValueError(f"{key} must be one of {sorted(_ALLOWED_VALUES[key])}")
        elif key == "garmin_key_expires_on" and value is not None:
            try:
                date.fromisoformat(str(value))
            except ValueError:
                raise ValueError("garmin_key_expires_on must be an ISO date (YYYY-MM-DD) or null")


def update_settings(session: Session, patch: dict) -> dict:
    _validate_patch(patch)
    row = session.get(AppSettings, tenant.pk(SETTINGS_ID))
    if row is None:
        row = AppSettings(id=SETTINGS_ID, data_json="{}")
        session.add(row)
    current_overrides = json.loads(row.data_json) if row.data_json else {}
    merged_overrides = _deep_merge(current_overrides, patch)
    _validate_heart_rate(patch, _deep_merge(DEFAULT_SETTINGS, merged_overrides), _deep_merge(DEFAULT_SETTINGS, current_overrides))
    row.data_json = json.dumps(merged_overrides)
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return _deep_merge(DEFAULT_SETTINGS, merged_overrides)
