from __future__ import annotations

import statistics
from datetime import date as date_, timedelta

WINDOW_DAYS = 7


def smooth_weight(readings: list[tuple[date_, float]]) -> list[tuple[date_, float]]:
    """readings: [(date, weight_kg), ...], any order, possibly several per day (multiple
    Withings syncs the same day). Collapses same-day readings to their mean, then takes a
    trailing 7-calendar-day rolling *median* (not mean) over whatever readings actually fall
    in each window — median is what makes a single-day outlier (phone scale fat-finger, a
    post-long-row dehydration dip) not move the smoothed line, which a mean would."""
    if not readings:
        return []
    by_day: dict[date_, list[float]] = {}
    for day, weight in readings:
        by_day.setdefault(day, []).append(weight)
    daily = sorted((day, statistics.mean(values)) for day, values in by_day.items())

    out = []
    for day, _ in daily:
        window_start = day - timedelta(days=WINDOW_DAYS - 1)
        window_values = [w for d, w in daily if window_start <= d <= day]
        out.append((day, statistics.median(window_values)))
    return out
