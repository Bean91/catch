from __future__ import annotations

"""Session 17 (task called itself "session 13" — see PLAN.md for why the repo keeps its own
sequence, same resolution sessions 8/12 used for an identical collision) Part A/B/C: adding a
piece (a segment of a canonical activity, e.g. a 2k inside a longer row) from a photo of the
PM5 screen or typed splits. Pure functions, no I/O — mirrors catch/analytics/erg_test.py's
split/style/validation shape so the two features (standalone confirmed tests vs. pieces
embedded in a longer activity) read as one vocabulary, not two.
"""

from typing import Optional

from catch.analytics.erg_math import watts_from_pace

# Reuses erg_test.py's TEST_SPECS vocabulary exactly (routes_activities.py's TEST_TYPES is the
# same list) plus "custom" — a piece and a confirmed test are the same set of shapes, just
# attached differently (a piece lives inside an activity; a test *is* one). 30min_r20's
# `max_avg_rate` gate is a test-detection heuristic that doesn't apply here: a piece's type is
# always explicitly chosen by the athlete (photo/typed entry), never auto-detected.
PIECE_TYPES = ("500m", "1000m", "2000m", "5000m", "6000m", "30min_r20", "60min", "custom")
_DISTANCE_BY_TYPE = {"500m": 500, "1000m": 1000, "2000m": 2000, "5000m": 5000, "6000m": 6000}
_DURATION_BY_TYPE = {"30min_r20": 1800, "60min": 3600}

_MIN_PLAUSIBLE_RATE = 14.0
_MAX_PLAUSIBLE_RATE = 50.0
# PM5 watts are integers, splits are tenths of a second — at a 1:38/500m split, 0.1s is
# ~1.1W (see watts_from_pace's slope there), so a couple of watts of "natural" rounding
# disagreement between a typed/photo split and its implied watts is expected, not a real
# mismatch. Scaled up slightly at low wattage, where the same time rounding implies a larger
# proportional watts swing.
_WATTS_TOLERANCE_FLOOR = 2.0
_WATTS_TOLERANCE_PCT = 0.01
_DEFAULT_SPLIT_DISTANCE_M = 500.0
_DEFAULT_TIME_SPLIT_S = 300.0  # 5-minute default rows for a duration-only piece with no fixed splits


def standard_distance_m(piece_type: str) -> Optional[float]:
    """The fixed distance a standard piece type implies (2000m is always 2000m), or None for
    a duration-based type ("30min_r20"/"60min") or "custom". Used as a last-resort fallback
    when a caller's splits carry no distance at all (e.g. a pure paste-only entry whose rows
    were never merged against a distance template) — without this, a real 2k piece could be
    saved with `distance_m=None` and silently fall out of every distance-keyed reader
    (piece_pb_candidates, confirmed_piece_pace_candidates, the Part D.4 absorb match), found
    by an advisor review of the frontend's paste flow."""
    return _DISTANCE_BY_TYPE.get(piece_type)


def default_splits(piece_type: str, distance_m: Optional[float] = None, duration_s: Optional[float] = None) -> list[dict]:
    """Template rows to seed the typed-entry form (task Part C.1 — "piece type sets
    defaults, e.g. 2k = 4 x 500m rows"). Every value is None (nothing timed yet); the caller
    fills in real numbers as the athlete types or pastes."""
    if piece_type in _DISTANCE_BY_TYPE:
        distance_m = _DISTANCE_BY_TYPE[piece_type]
    if piece_type in _DURATION_BY_TYPE:
        duration_s = _DURATION_BY_TYPE[piece_type]

    if distance_m:
        n = max(1, round(distance_m / _DEFAULT_SPLIT_DISTANCE_M))
        per_split_distance = distance_m / n
        return [
            {"split_index": i + 1, "distance_m": round(per_split_distance * (i + 1), 1), "split_s": None, "rate": None, "watts": None, "hr": None}
            for i in range(n)
        ]
    if duration_s:
        n = max(1, round(duration_s / _DEFAULT_TIME_SPLIT_S))
        return [{"split_index": i + 1, "distance_m": None, "split_s": None, "rate": None, "watts": None, "hr": None} for i in range(n)]
    return [{"split_index": 1, "distance_m": None, "split_s": None, "rate": None, "watts": None, "hr": None}]


def _row_distance_delta(rows: list[dict], i: int) -> Optional[float]:
    """This row's own distance (not cumulative) — the difference from the previous row's
    cumulative distance, or this row's value itself if it's the first. None if either row is
    missing a distance (a duration-only piece, or a row not yet filled in)."""
    d = rows[i].get("distance_m")
    if d is None:
        return None
    prev = rows[i - 1].get("distance_m") if i > 0 else 0.0
    if prev is None:
        return None
    return d - prev


def watts_for_split(split_s: float, distance_delta_m: float = _DEFAULT_SPLIT_DISTANCE_M) -> float:
    """The watts a `split_s`-second split over `distance_delta_m` metres implies, via
    Concept2's published pace<->watts formula (catch/analytics/erg_math.py)."""
    pace_per_500 = split_s / distance_delta_m * _DEFAULT_SPLIT_DISTANCE_M
    return watts_from_pace(pace_per_500)


def validate_splits(rows: list[dict], total_distance_m: Optional[float], total_duration_s: Optional[float]) -> dict:
    """Task Part B.3: never silently "corrects" a row — just flags which ones disagree, with
    the specific tolerance that triggered, so the athlete can go fix the one real misread
    rather than guess which of several numbers is wrong. `issues` is empty (and `ok: True`)
    when every check passes or there isn't enough data filled in yet to check it."""
    issues: list[dict] = []
    n = len(rows)
    defined_splits = [r["split_s"] for r in rows if r.get("split_s") is not None]

    if total_duration_s is not None and defined_splits and len(defined_splits) == n:
        total_of_splits = sum(defined_splits)
        tolerance = 0.5 * n
        if abs(total_of_splits - total_duration_s) > tolerance:
            issues.append(
                {
                    "split_index": None,
                    "field": "total_time",
                    "message": (
                        f"Splits sum to {total_of_splits:.1f}s but the total is {total_duration_s:.1f}s "
                        f"(off by {abs(total_of_splits - total_duration_s):.1f}s, tolerance is {tolerance:.1f}s)."
                    ),
                }
            )

    if total_distance_m is not None and rows and rows[-1].get("distance_m") is not None:
        last = rows[-1]["distance_m"]
        tolerance_d = max(1.0 * n, total_distance_m * 0.005)
        if abs(last - total_distance_m) > tolerance_d:
            issues.append(
                {
                    "split_index": None,
                    "field": "total_distance",
                    "message": f"Splits add up to {last:.0f}m but the total is {total_distance_m:.0f}m.",
                }
            )

    for i, row in enumerate(rows):
        split_s, rate, watts = row.get("split_s"), row.get("rate"), row.get("watts")
        if rate is not None and not (_MIN_PLAUSIBLE_RATE <= rate <= _MAX_PLAUSIBLE_RATE):
            issues.append(
                {
                    "split_index": row["split_index"],
                    "field": "rate",
                    "message": f"{rate:g} spm is outside the plausible {_MIN_PLAUSIBLE_RATE:g}-{_MAX_PLAUSIBLE_RATE:g} range.",
                }
            )
        if split_s is not None and watts is not None and split_s > 0:
            distance_delta = _row_distance_delta(rows, i) or _DEFAULT_SPLIT_DISTANCE_M
            expected = watts_for_split(split_s, distance_delta)
            tolerance_w = max(_WATTS_TOLERANCE_FLOOR, expected * _WATTS_TOLERANCE_PCT)
            if abs(expected - watts) > tolerance_w:
                issues.append(
                    {
                        "split_index": row["split_index"],
                        "field": "watts",
                        "message": f"{watts:g}W doesn't match the split ({expected:.0f}W implied by {split_s:.1f}s/{distance_delta:.0f}m).",
                    }
                )

    return {"ok": len(issues) == 0, "issues": issues}


def aggregate_from_splits(rows: list[dict]) -> dict:
    """Totals/averages for the piece's own summary fields, derived from its splits rather
    than re-entered separately — avg_split_s is time-weighted (the mean of a piece's actual
    splits, not distance/time, since a short last partial split would otherwise skew it)."""
    defined_splits = [r["split_s"] for r in rows if r.get("split_s") is not None]
    rates = [r["rate"] for r in rows if r.get("rate") is not None]
    watts = [r["watts"] for r in rows if r.get("watts") is not None]
    duration_s = sum(defined_splits) if len(defined_splits) == len(rows) and rows else None
    distance_m = rows[-1]["distance_m"] if rows and rows[-1].get("distance_m") is not None else None
    return {
        "duration_s": duration_s,
        "distance_m": distance_m,
        "avg_split_s": (sum(defined_splits) / len(defined_splits)) if defined_splits else None,
        "avg_rate": (sum(rates) / len(rates)) if rates else None,
        "avg_watts": (sum(watts) / len(watts)) if watts else None,
    }


_PASTE_TOKEN_SEP = "/"


def parse_time_token(time_str: str, label: str = "time") -> float:
    """"m:ss[.t]" -> seconds. Shared by parse_splits_paste below and
    catch/coach/tools.py's free-text add_piece parser, so the two input paths (pasted splits,
    a coach chat message) can never silently drift on what counts as a valid time token."""
    if ":" not in time_str:
        raise ValueError(f"Can't parse {label} '{time_str}' — expected m:ss or m:ss.t.")
    minutes_str, _, seconds_str = time_str.partition(":")
    try:
        return int(minutes_str) * 60 + float(seconds_str)
    except ValueError as exc:
        raise ValueError(f"Can't parse {label} '{time_str}' — expected m:ss or m:ss.t.") from exc


def parse_splits_paste(text: str) -> list[dict]:
    """Task Part C.1: a line like "1:38.2 32 / 1:41.0 30 / 1:39.5 31" -> split rows (rate
    optional per token). Tokens separate on "/" or a newline; each token is "m:ss[.t]" with an
    optional trailing rate. Raises ValueError on a token that isn't parseable, naming which
    one, rather than silently skipping it."""
    raw = text.replace("\n", _PASTE_TOKEN_SEP)
    tokens = [t.strip() for t in raw.split(_PASTE_TOKEN_SEP) if t.strip()]
    rows = []
    for i, token in enumerate(tokens):
        parts = token.split()
        if not parts:
            continue
        time_str = parts[0]
        rate = float(parts[1]) if len(parts) > 1 else None
        split_s = parse_time_token(time_str, f"split {i + 1}")
        rows.append({"split_index": i + 1, "distance_m": None, "split_s": split_s, "rate": rate, "watts": None, "hr": None})
    return rows


def points_from_splits(rows: list[dict]) -> list[dict]:
    """Splits -> the {distance_cum, t_cum} point shape catch/analytics/erg_test.py's
    actual_splits/pacing_analysis already expect (session 17 Part A.2/D) — lets a piece's own
    splits_json feed the same pacing-analysis pipeline a confirmed Concept2 test's raw strokes
    do, with no second analysis path to keep in sync."""
    points = []
    cum_t = 0.0
    for row in rows:
        split_s = row.get("split_s")
        if split_s is None:
            continue
        cum_t += split_s
        points.append({"distance_cum": row.get("distance_m"), "t_cum": cum_t})
    return points


def find_best_window(hr_samples: list[Optional[float]], window_len_s: int) -> Optional[int]:
    """Task Part D.1: auto-suggest the window (of this piece's own total time) whose average
    HR is highest — the piece is presumed to be the hardest stretch of the activity. Returns
    the start offset (seconds into the recording), or None if the recording is shorter than
    the piece or has no HR at all. A plain O(n) scan — a Pi-scale sample array (a few thousand
    points) makes anything fancier unnecessary."""
    n = len(hr_samples)
    if window_len_s <= 0 or n < window_len_s:
        return None

    defined = [0.0 if v is None else v for v in hr_samples]
    has_value = [0 if v is None else 1 for v in hr_samples]
    prefix_sum = [0.0] * (n + 1)
    prefix_count = [0] * (n + 1)
    for i in range(n):
        prefix_sum[i + 1] = prefix_sum[i] + defined[i]
        prefix_count[i + 1] = prefix_count[i] + has_value[i]

    best_start, best_avg, best_count = None, -1.0, 0
    for start in range(0, n - window_len_s + 1):
        end = start + window_len_s
        count = prefix_count[end] - prefix_count[start]
        if count == 0:
            continue
        avg = (prefix_sum[end] - prefix_sum[start]) / count
        # Tie-break toward more defined samples — a window that's mostly dropout overlapping
        # a handful of real high readings shouldn't beat one with the same average backed by
        # a full window of real data (test_find_best_window_skips_missing_samples).
        if avg > best_avg or (avg == best_avg and count > best_count):
            best_avg, best_count, best_start = avg, count, start
    return best_start
