from __future__ import annotations

"""Part B.3 — power-based, TSS-style load for cycling (Peloton/Garmin bike). Pure functions,
no I/O; catch/sync/canonical.py supplies the FTP (configured, or estimated here) and the
power samples.

TSS itself (Coggan/TrainingPeaks' standard formula, using plain average power here rather
than a lag-filtered "normalized power" — this app doesn't compute NP, so this is a documented
simplification) is on roughly the same order of magnitude as a Banister trimp_like for a
comparably hard session (e.g. ~100 for an hour at IF=1.0 vs. Banister's ~100-150 for an hour
hard effort), so it's fed into the same 0-21 log-saturation strain scale as every other sport
(catch/analytics/strain.py) rather than inventing a second, cycling-only strain number —
flagged as an approximation in docs/analytics.md, not a validated equivalence.
"""

from typing import Optional

_FTP_FROM_20MIN_FACTOR = 0.95
_BEST_20MIN_WINDOW_S = 20 * 60


def estimate_ftp_watts(best_20min_power: Optional[float]) -> Optional[float]:
    if not best_20min_power or best_20min_power <= 0:
        return None
    return best_20min_power * _FTP_FROM_20MIN_FACTOR


def best_rolling_power(power_samples: list[Optional[float]], window_s: int = _BEST_20MIN_WINDOW_S) -> Optional[float]:
    """Best `window_s`-second rolling *average* power (1 Hz samples) — skips a window with
    more than 20% missing samples rather than silently averaging over fewer real readings
    than claimed."""
    n = len(power_samples)
    if n < window_s:
        return None
    min_defined = int(window_s * 0.8)

    best = None
    window_sum = 0.0
    window_count = 0
    for i in range(n):
        v = power_samples[i]
        if v is not None:
            window_sum += v
            window_count += 1
        if i >= window_s:
            old = power_samples[i - window_s]
            if old is not None:
                window_sum -= old
                window_count -= 1
        if i >= window_s - 1 and window_count >= min_defined:
            avg = window_sum / window_count
            if best is None or avg > best:
                best = avg
    return best


def cycling_tss(duration_s: Optional[float], avg_power: Optional[float], ftp_watts: Optional[float]) -> Optional[float]:
    """TSS = 100 * hours * IF^2, IF = avg_power / FTP — the standard simplified formula."""
    if not duration_s or not avg_power or not ftp_watts or ftp_watts <= 0:
        return None
    hours = duration_s / 3600.0
    intensity_factor = avg_power / ftp_watts
    return 100.0 * hours * intensity_factor**2
