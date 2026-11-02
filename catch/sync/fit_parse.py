from __future__ import annotations

"""FIT file I/O (device info + per-record samples) — the sync-side counterpart to
catch/analytics/zones_samples.py's pure math. Streams the file with `fitdecode` (a pure-
Python, universal-wheel package — checked against PyPI before adding, per CLAUDE.md's Pi/ARM
rule) rather than loading it whole, matching CLAUDE.md's "stream downloads, never load years
of data into RAM" rule (one activity's FIT file is at most a few thousand records).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fitdecode

logger = logging.getLogger("catch.fit_parse")

# file_id.manufacturer is the FIT file's own creator (confirmed against this account's two
# real indoor_cycling/indoor_rowing files: both are "garmin", the watch itself) — the only
# reliable "who wrote this FIT file" signal; device_info can legitimately list a third-party
# paired sensor (e.g. this account's real files pair a "cardiosport" ANT+ HR strap) on an
# otherwise watch-recorded activity, so it's not used for this check. No live Peloton-pushed
# activity exists in this account to confirm its exact file_id.manufacturer string (see
# docs/peloton.md) — detection is implemented per this documented FIT-spec mechanism but
# unverified against a real Peloton-origin file.
_WATCH_MANUFACTURERS = {"garmin", None}

# FIT's local_device_type names for a true ANT+ chest-strap HR sensor vs. the watch's own
# built-in wrist-optical sensor (confirmed against this account's real FIT files).
_CHEST_STRAP_DEVICE_TYPES = {"heart_rate"}
_WRIST_DEVICE_TYPES = {"whr"}

# A gap this short in Garmin's smart-recording record stream is forward-filled (the value
# genuinely hasn't changed); anything longer is treated as a real sensor dropout (left None)
# rather than smeared forward.
_MAX_FORWARD_FILL_GAP_S = 10


@dataclass
class FitSamples:
    start: Optional[datetime]
    duration_s: float
    hr: list[Optional[float]] = field(default_factory=list)
    power: list[Optional[float]] = field(default_factory=list)
    cadence: list[Optional[float]] = field(default_factory=list)
    is_peloton_like: bool = False
    hr_source_type: Optional[str] = None  # "chest_strap" | "wrist" | None


def parse_fit(path: str | Path) -> Optional[FitSamples]:
    path = Path(path)
    if not path.exists():
        return None

    file_id_manufacturer: Optional[str] = None
    hr_device_types: set[str] = set()
    records: list[tuple[datetime, Optional[float], Optional[float], Optional[float]]] = []

    try:
        with fitdecode.FitReader(str(path)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name == "file_id":
                    # The file's own creator, not a paired sensor's brand (device_info can
                    # legitimately list a third-party HR strap/power meter on an otherwise
                    # watch-recorded activity — only file_id says who wrote the FIT file).
                    file_id_manufacturer = _field_value(frame, "manufacturer")
                elif frame.name == "device_info":
                    local_type = _field_value(frame, "local_device_type")
                    if local_type in _CHEST_STRAP_DEVICE_TYPES or local_type in _WRIST_DEVICE_TYPES:
                        hr_device_types.add(local_type)
                elif frame.name == "record":
                    ts = _field_value(frame, "timestamp")
                    if ts is None:
                        continue
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    records.append(
                        (
                            ts,
                            _field_value(frame, "heart_rate"),
                            _field_value(frame, "power"),
                            _field_value(frame, "cadence"),
                        )
                    )
    except Exception:
        logger.exception("failed to parse FIT file %s", path)
        return None

    if not records:
        return None

    records.sort(key=lambda r: r[0])
    start = records[0][0]
    end = records[-1][0]
    duration_s = max(0.0, (end - start).total_seconds())
    n = int(duration_s) + 1

    hr = _resample(records, start, n, 1)
    power = _resample(records, start, n, 2)
    cadence = _resample(records, start, n, 3)

    is_peloton_like = file_id_manufacturer not in _WATCH_MANUFACTURERS
    hr_source_type = None
    if _CHEST_STRAP_DEVICE_TYPES & hr_device_types:
        hr_source_type = "chest_strap"
    elif _WRIST_DEVICE_TYPES & hr_device_types:
        hr_source_type = "wrist"

    return FitSamples(
        start=start,
        duration_s=duration_s,
        hr=hr,
        power=power,
        cadence=cadence,
        is_peloton_like=is_peloton_like,
        hr_source_type=hr_source_type,
    )


def _field_value(frame: "fitdecode.FitDataMessage", name: str):
    try:
        return frame.get_field(name).value
    except KeyError:
        return None


def _resample(
    records: list[tuple[datetime, Optional[float], Optional[float], Optional[float]]],
    start: datetime,
    n: int,
    col: int,
) -> list[Optional[float]]:
    known: dict[int, float] = {}
    for rec in records:
        value = rec[col]
        if value is None:
            continue
        offset = int(round((rec[0] - start).total_seconds()))
        if 0 <= offset < n:
            known[offset] = float(value)

    out: list[Optional[float]] = [None] * n
    last_value: Optional[float] = None
    last_offset: Optional[int] = None
    for offset in sorted(known):
        value = known[offset]
        if last_offset is not None and offset - last_offset <= _MAX_FORWARD_FILL_GAP_S:
            for fill in range(last_offset, offset):
                out[fill] = last_value
        out[offset] = value
        last_value, last_offset = value, offset
    return out
