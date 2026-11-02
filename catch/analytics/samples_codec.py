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
