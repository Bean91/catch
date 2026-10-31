from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timezone

from sqlmodel import Session

from catch.analytics.defaults import DEFAULT_SETTINGS
from catch.core.models import AppSettings

SETTINGS_ID = 1

_ALLOWED_VALUES = {"zone_mode": {"hr", "power"}, "units": {"metric", "imperial"}}


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_settings(session: Session) -> dict:
    row = session.get(AppSettings, SETTINGS_ID)
    overrides = json.loads(row.data_json) if row and row.data_json else {}
    return _deep_merge(DEFAULT_SETTINGS, overrides)


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
    row = session.get(AppSettings, SETTINGS_ID)
    if row is None:
        row = AppSettings(id=SETTINGS_ID, data_json="{}")
        session.add(row)
    current_overrides = json.loads(row.data_json) if row.data_json else {}
    merged_overrides = _deep_merge(current_overrides, patch)
    row.data_json = json.dumps(merged_overrides)
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return _deep_merge(DEFAULT_SETTINGS, merged_overrides)
