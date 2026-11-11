from __future__ import annotations

"""Compact 1 Hz sample storage (Part E.1) — pure functions, no I/O. A 90-minute session is
~5,400 samples; packed as unsigned 16-bit ints (0xFFFF = missing) and zlib-compressed, that's
a few KB per activity rather than thousands of SQLite rows (CLAUDE.md's Pi-memory rule)."""

import struct
import zlib
from typing import Optional

_MISSING = 0xFFFF
_FMT1 = "<H"  # one unsigned short, little-endian


def pack_series(values: list[Optional[float]]) -> bytes:
    """Rounds to the nearest int (HR/power/cadence are all whole-number-ish in practice;
    sub-integer precision isn't needed for zone/strain math) and clamps to a uint16."""
    buf = bytearray()
    for v in values:
        if v is None:
            buf += struct.pack(_FMT1, _MISSING)
        else:
            buf += struct.pack(_FMT1, max(0, min(_MISSING - 1, round(v))))
    return zlib.compress(bytes(buf), level=6)


def unpack_series(blob: Optional[bytes], n: int) -> list[Optional[float]]:
    if not blob:
        return [None] * n
    raw = zlib.decompress(blob)
    out = []
    for i in range(n):
        (v,) = struct.unpack_from(_FMT1, raw, i * 2)
        out.append(None if v == _MISSING else float(v))
    return out


# Session 20 (GPS tracks). Coordinates can't live in pack_series' whole-number uint16: a
# degree*1e7 int32 is ~1 cm resolution, and consecutive fixes are close, so a delta-coded int32
# stream compresses far better than raw values. Same zlib-and-struct approach, no numpy (Pi).
_INT32_MISSING = -(2**31)
_FMT_I32 = "<i"
_FMT_U16 = "<H"


def pack_int32_delta(values: list[Optional[int]]) -> bytes:
    """None -> the INT32_MIN sentinel, stored as-is (not delta-coded against) so a missing value
    never corrupts the running delta of the points around it."""
    buf = bytearray()
    prev = 0
    for v in values:
        if v is None:
            buf += struct.pack(_FMT_I32, _INT32_MISSING)
            continue
        buf += struct.pack(_FMT_I32, v - prev)
        prev = v
    return zlib.compress(bytes(buf), level=6)


def unpack_int32_delta(blob: Optional[bytes], n: int) -> list[Optional[int]]:
    if not blob:
        return [None] * n
    raw = zlib.decompress(blob)
    out: list[Optional[int]] = []
    prev = 0
    for i in range(n):
        (d,) = struct.unpack_from(_FMT_I32, raw, i * 4)
        if d == _INT32_MISSING:
            out.append(None)
        else:
            prev += d
            out.append(prev)
    return out


def pack_scaled(values: list[Optional[float]], scale: float, offset: float = 0.0) -> bytes:
    """uint16 of round((v + offset) * scale), 0xFFFF = missing — for speed (0.01 m/s) and
    altitude ((m + 500) * 10, i.e. -500..6053 m at 0.1 m)."""
    buf = bytearray()
    for v in values:
        if v is None:
            buf += struct.pack(_FMT_U16, _MISSING)
        else:
            buf += struct.pack(_FMT_U16, max(0, min(_MISSING - 1, round((v + offset) * scale))))
    return zlib.compress(bytes(buf), level=6)


def unpack_scaled(blob: Optional[bytes], n: int, scale: float, offset: float = 0.0) -> list[Optional[float]]:
    if not blob:
        return [None] * n
    raw = zlib.decompress(blob)
    out: list[Optional[float]] = []
    for i in range(n):
        (v,) = struct.unpack_from(_FMT_U16, raw, i * 2)
        out.append(None if v == _MISSING else v / scale - offset)
    return out


def pack_uint32(values: list[Optional[int]]) -> bytes:
    """Whole-number uint32 (seconds offsets, centimetre distances); 0xFFFFFFFF = missing."""
    buf = bytearray()
    for v in values:
        buf += struct.pack("<I", 0xFFFFFFFF if v is None else max(0, min(0xFFFFFFFE, int(v))))
    return zlib.compress(bytes(buf), level=6)


def unpack_uint32(blob: Optional[bytes], n: int) -> list[Optional[int]]:
    if not blob:
        return [None] * n
    raw = zlib.decompress(blob)
    out: list[Optional[int]] = []
    for i in range(n):
        (v,) = struct.unpack_from("<I", raw, i * 4)
        out.append(None if v == 0xFFFFFFFF else v)
    return out
