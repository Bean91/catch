from __future__ import annotations

"""Session 15 (see PLAN.md Part A): subjective morning check-in -> a 0-100 recovery
sub-score. Pure, no I/O — mirrors catch/analytics/recovery.py's other components."""


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _slider_to_100(value: int, invert: bool) -> float:
    # Sliders are 1-5. soreness/stress: 1 = none/low (good), 5 = severe/high (bad) -> invert.
    # mood/sleep_quality: 1 = low/poor (bad), 5 = high/great (good) -> direct.
    scaled = (value - 1) / 4 * 100
    return _clip(100 - scaled if invert else scaled, 0, 100)


def checkin_recovery_score(
    soreness: int | None, stress: int | None, mood: int | None, sleep_quality: int | None
) -> float | None:
    """Mean of whichever sliders were filled in — a check-in that only answers some of the
    four questions still contributes (the sheet is one screen, but nothing requires every
    slider to be touched before saving). None if nothing was recorded at all."""
    parts = []
    if soreness is not None:
        parts.append(_slider_to_100(soreness, invert=True))
    if stress is not None:
        parts.append(_slider_to_100(stress, invert=True))
    if mood is not None:
        parts.append(_slider_to_100(mood, invert=False))
    if sleep_quality is not None:
        parts.append(_slider_to_100(sleep_quality, invert=False))
    if not parts:
        return None
    return sum(parts) / len(parts)


def checkin_badness(soreness: int | None, mood: int | None) -> float | None:
    """Session 15 Part B: a 0-100 "how bad" figure from soreness/mood only (the two sliders
    the illness task names explicitly), higher = worse — the inverse direction of
    checkin_recovery_score, and deliberately not stress/sleep_quality (those already feed
    recovery directly; illness wants the two that plausibly track feeling unwell)."""
    parts = []
    if soreness is not None:
        parts.append(_slider_to_100(soreness, invert=False))
    if mood is not None:
        parts.append(_slider_to_100(mood, invert=True))
    if not parts:
        return None
    return sum(parts) / len(parts)
