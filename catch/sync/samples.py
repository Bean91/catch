from __future__ import annotations

"""Builds and stores Part E's compact per-activity sample arrays — from a FIT file's record
messages (Garmin) or from Concept2's stroke data (forward-filled between strokes onto a 1 Hz
grid, since a stroke only fires an event, not a fixed-interval sample)."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session

from catch.analytics.samples_codec import pack_series
from catch.core.models import ActivitySamples


def store_samples(
    session: Session,
    activity_id: int,
    *,
    start: datetime,
    hr: list[Optional[float]],
    power: list[Optional[float]],
    cadence: list[Optional[float]],
) -> None:
    n = len(hr)
    row = session.get(ActivitySamples, activity_id)
    if row is None:
        row = ActivitySamples(activity_id=activity_id, start=start, n_samples=n)
        session.add(row)
    row.start = start
    row.n_samples = n
    row.hr_blob = pack_series(hr)
    row.power_blob = pack_series(power)
    row.cadence_blob = pack_series(cadence)
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()


def store_samples_from_fit(session: Session, activity_id: int, fit_samples) -> None:
    store_samples(
        session,
        activity_id,
        start=fit_samples.start,
        hr=fit_samples.hr,
        power=fit_samples.power,
        cadence=fit_samples.cadence,
    )


def store_samples_from_strokes(session: Session, activity_id: int, strokes: list[dict]) -> None:
    """`strokes` are the dicts catch/sync/concept2_client.py's `_extract_strokes` builds —
    `t` resets to 0 at each interval boundary. Resampled onto a 1 Hz grid across the whole
    recording (rest time included), forward-filling each stroke's reading until the next
    one — the natural reading of "a stroke's state holds until the next stroke" for an
    event-based sample stream, rather than per-fixed-interval telemetry like a FIT record."""
    if not strokes:
        return
    t_cum = 0.0
    last_interval = None
    rows: list[tuple[float, Optional[float], Optional[float], Optional[float]]] = []
    for s in sorted(strokes, key=lambda x: x.get("seq", 0)):
        idx = s.get("interval_index") or 0
        if last_interval is not None and idx != last_interval:
            # A new interval starts right after the last stroke of the previous one.
            t_cum = rows[-1][0] if rows else t_cum
        last_interval = idx
        t = t_cum + (s.get("t") or 0.0)
        rows.append((t, s.get("hr"), s.get("watts"), s.get("stroke_rate")))

    if not rows:
        return
    duration_s = rows[-1][0]
    n = int(duration_s) + 1
    hr: list[Optional[float]] = [None] * n
    power: list[Optional[float]] = [None] * n
    cadence: list[Optional[float]] = [None] * n

    prev_offset = 0
    for t, h, w, r in rows:
        offset = min(n - 1, max(0, int(round(t))))
        for fill in range(prev_offset, offset + 1):
            hr[fill] = h if h else hr[fill]
            power[fill] = w if w is not None else power[fill]
            cadence[fill] = r if r is not None else cadence[fill]
        prev_offset = offset

    # A placeholder "now" start is fine here — Concept2 samples are keyed off the activity's
    # own t-offset grid, not wall-clock time; catch/sync/canonical.py only reads hr/power/
    # cadence arrays, never `ActivitySamples.start`, for a Concept2-sourced canonical.
    store_samples(session, activity_id, start=datetime.now(timezone.utc), hr=hr, power=power, cadence=cadence)
