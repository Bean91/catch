from __future__ import annotations


def average_wake_time_minutes(samples: list[int]) -> int | None:
    """A plain arithmetic mean over minutes-since-local-midnight — deliberately not a
    circular mean (handling a wrap past midnight): a rower's real wake times cluster well
    within a single day, and the extra complexity isn't worth it for this app's actual data.
    None with no samples, so the caller can fall back to a fixed default rather than divide
    by zero."""
    if not samples:
        return None
    return round(sum(samples) / len(samples))
