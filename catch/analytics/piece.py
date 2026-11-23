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
PIECE_TYPES = ("500m", "1000m", "2000m", "5000m", "6000m", "10000m", "30min_r20", "30min", "60min", "custom")

# Session 33: a piece is on a rowing erg or a bike. The split basis is the machine's own display
# unit (a PM5 on a RowErg shows pace per 500 m, on a BikeErg per 1000 m), so every pace below is
# "seconds per split_m metres" for the piece's modality, never a rowing pace relabelled.
MODALITIES = ("rowing_erg", "bike")
DEFAULT_MODALITY = "rowing_erg"
SPLIT_M_BY_MODALITY = {"rowing_erg": 500.0, "bike": 1000.0}
# "30min_r20" is a rowing rate-capped test; it has no bike meaning.
PIECE_TYPES_BY_MODALITY = {"rowing_erg": PIECE_TYPES, "bike": tuple(t for t in PIECE_TYPES if t != "30min_r20")}
_DISTANCE_BY_TYPE = {"500m": 500, "1000m": 1000, "2000m": 2000, "5000m": 5000, "6000m": 6000, "10000m": 10000}
_DURATION_BY_TYPE = {"30min_r20": 1800, "30min": 1800, "60min": 3600}

_MIN_PLAUSIBLE_RATE = 14.0
_MAX_PLAUSIBLE_RATE = 50.0
# A bike's "rate" is pedal cadence in rpm, a different range from a stroke rate in spm.
_RATE_RANGE_BY_MODALITY = {"rowing_erg": (_MIN_PLAUSIBLE_RATE, _MAX_PLAUSIBLE_RATE, "spm"), "bike": (30.0, 150.0, "rpm")}
# PM5 watts are integers, splits are tenths of a second — at a 1:38/500m split, 0.1s is
# ~1.1W (see watts_from_pace's slope there), so a couple of watts of "natural" rounding
# disagreement between a typed/photo split and its implied watts is expected, not a real
# mismatch. Scaled up slightly at low wattage, where the same time rounding implies a larger
# proportional watts swing.
_WATTS_TOLERANCE_FLOOR = 2.0
_WATTS_TOLERANCE_PCT = 0.01
_DEFAULT_SPLIT_DISTANCE_M = 500.0
_DEFAULT_TIME_SPLIT_S = 300.0  # 5-minute default rows for a duration-only piece with no fixed splits


def split_m_for(modality: Optional[str]) -> float:
    return SPLIT_M_BY_MODALITY.get(modality or DEFAULT_MODALITY, _DEFAULT_SPLIT_DISTANCE_M)


def check_modality(modality: Optional[str], piece_type: str) -> Optional[str]:
    """A sentence when this modality/type pair is not allowed, else None."""
    if modality not in MODALITIES:
        return f"modality must be one of {list(MODALITIES)}"
    if piece_type not in PIECE_TYPES_BY_MODALITY[modality]:
        return f"{piece_type} is a rowing-only piece type; choose another type for a bike piece."
    return None


def totals_only_splits(distance_m: Optional[float], duration_s: Optional[float], rate: Optional[float] = None, watts: Optional[float] = None) -> list[dict]:
    """One whole-piece row for a piece known only by its totals (a PM5 screen with no splits table,
    which is what the vision call returns for many photos). Without it such a piece could never be
    saved — the session 33 photo bug."""
    if distance_m is None and duration_s is None:
        return []
    return [{"split_index": 1, "distance_m": distance_m, "split_s": duration_s, "rate": rate, "watts": watts, "hr": None}]


def standard_distance_m(piece_type: str) -> Optional[float]:
    """The fixed distance a standard piece type implies (2000m is always 2000m), or None for
    a duration-based type ("30min_r20"/"60min") or "custom". Used as a last-resort fallback
    when a caller's splits carry no distance at all (e.g. a pure paste-only entry whose rows
    were never merged against a distance template) — without this, a real 2k piece could be
    saved with `distance_m=None` and silently fall out of every distance-keyed reader
    (piece_pb_candidates, confirmed_piece_pace_candidates, the Part D.4 absorb match), found
    by an advisor review of the frontend's paste flow."""
    return _DISTANCE_BY_TYPE.get(piece_type)


def default_splits(
    piece_type: str, distance_m: Optional[float] = None, duration_s: Optional[float] = None, modality: Optional[str] = None
) -> list[dict]:
    """Template rows to seed the typed-entry form (task Part C.1 — "piece type sets
    defaults, e.g. 2k = 4 x 500m rows"). Every value is None (nothing timed yet); the caller
    fills in real numbers as the athlete types or pastes."""
    if piece_type in _DISTANCE_BY_TYPE:
        distance_m = _DISTANCE_BY_TYPE[piece_type]
    if piece_type in _DURATION_BY_TYPE:
        duration_s = _DURATION_BY_TYPE[piece_type]

    if distance_m:
        n = max(1, round(distance_m / split_m_for(modality)))
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


# Session 34 (docs/analytics.md §34): watts come from pace on a rowing erg only. A BikeErg or a road bike has no published pace→power
# model Catch trusts, so a bike piece's power is only ever what the athlete or the screen gave.
POWER_FROM_PACE_MODALITIES = frozenset({"rowing_erg"})
# Bumped when the stored-power rules change; sync/piece_power.py re-derives stored pieces once per owner per version.
PIECE_POWER_MODEL = 1


def derives_power(modality: Optional[str]) -> bool:
    return (modality or DEFAULT_MODALITY) in POWER_FROM_PACE_MODALITIES


def row_pace_500(rows: list[dict], i: int) -> Optional[float]:
    """Seconds per 500 m over this row's *own* distance, or None when the row has no time or no known distance. A time-only row
    (a 5:00 row of a 30-minute piece with no metres typed) has no pace — it is never assumed to be 500 m."""
    split_s = rows[i].get("split_s")
    delta = _row_distance_delta(rows, i)
    if split_s is None or split_s <= 0 or not delta or delta <= 0:
        return None
    return split_s / delta * _DEFAULT_SPLIT_DISTANCE_M


def watts_tolerance(expected: float) -> float:
    return max(_WATTS_TOLERANCE_FLOOR, expected * _WATTS_TOLERANCE_PCT)


def with_derived_watts(rows: list[dict], modality: Optional[str]) -> list[dict]:
    """Rowing: every row with a pace gets `watts` from it (`watts_source: "pace"`), full precision. A typed watts that disagreed with
    its split beyond rounding tolerance (only reachable through "Save anyway") is kept as `watts_entered`, never silently lost. A row
    with watts but no pace keeps them (`watts_source: "entered"`). Bike rows are never touched beyond the source tag. Idempotent."""
    out: list[dict] = []
    rowing = derives_power(modality)
    for i, original in enumerate(rows):
        row = dict(original)
        pace = row_pace_500(rows, i) if rowing else None
        if pace is not None:
            derived = watts_from_pace(pace)
            typed = row.get("watts")
            if typed is not None and row.get("watts_source") != "pace" and abs(typed - derived) > watts_tolerance(derived):
                row["watts_entered"] = typed
            row["watts"] = derived
            row["watts_source"] = "pace"
        elif row.get("watts") is not None:
            row["watts_source"] = "entered"
        else:
            row.pop("watts_source", None)
        out.append(row)
    return out


def without_derived_watts(rows: list[dict]) -> list[dict]:
    """Rows as the athlete gave them: a pace-derived watts is dropped (and an `watts_entered` original restored), so re-deriving under a
    different modality never keeps rowing-formula watts on a bike piece."""
    out = []
    for original in rows:
        row = dict(original)
        if row.get("watts_source") == "pace":
            row["watts"] = row.pop("watts_entered", None)
            row.pop("watts_source")
        out.append(row)
    return out


def _time_weighted_watts(rows: list[dict]) -> Optional[float]:
    """Mean of entered watts weighted by each row's time when every such row has one; else a plain mean."""
    with_watts = [r for r in rows if r.get("watts") is not None]
    if not with_watts:
        return None
    if all(r.get("split_s") for r in with_watts):
        total = sum(r["split_s"] for r in with_watts)
        return sum(r["watts"] * r["split_s"] for r in with_watts) / total
    return sum(r["watts"] for r in with_watts) / len(with_watts)


def piece_avg_watts(modality: Optional[str], avg_split_s: Optional[float], rows: list[dict], entered: Optional[float] = None) -> tuple[Optional[float], Optional[str]]:
    """(average watts, basis). Rowing with a known average pace: the power that pace implies — Concept2's own logbook and PM5 summary
    figure, and the brief's "watts from split pace". Otherwise (bike, or a rowing piece with no distance) the entered power: rows
    weighted by time, else the screen's own average. Basis is "pace", "entered" or None."""
    if derives_power(modality) and avg_split_s and avg_split_s > 0:
        return watts_from_pace(avg_split_s), "pace"
    entered_rows = _time_weighted_watts(rows)
    if entered_rows is not None:
        return entered_rows, "entered"
    if entered is not None and entered > 0:
        return float(entered), "entered"
    return None, None


def validate_splits(
    rows: list[dict], total_distance_m: Optional[float], total_duration_s: Optional[float], modality: Optional[str] = None
) -> dict:
    """Task Part B.3: never silently "corrects" a row — just flags which ones disagree, with
    the specific tolerance that triggered, so the athlete can go fix the one real misread
    rather than guess which of several numbers is wrong. `issues` is empty (and `ok: True`)
    when every check passes or there isn't enough data filled in yet to check it."""
    issues: list[dict] = []
    n = len(rows)
    modality = modality or DEFAULT_MODALITY
    rate_lo, rate_hi, rate_unit = _RATE_RANGE_BY_MODALITY[modality]
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
        if rate is not None and not (rate_lo <= rate <= rate_hi):
            issues.append(
                {
                    "split_index": row["split_index"],
                    "field": "rate",
                    "message": f"{rate:g} {rate_unit} is outside the plausible {rate_lo:g}-{rate_hi:g} range.",
                }
            )
        # The pace<->watts formula is Concept2's RowErg one; BikeErg and road-bike power don't follow it
        # (catch/sync/concept2_client.py WATTS_DERIVABLE_TYPES), so a bike's typed watts are never checked against its pace.
        # Session 34: only a row whose pace is known (time AND its own distance) can be checked — a time-only row used to be assumed
        # 500 m and every real watts on it was flagged. A value Catch itself derived (`watts_source: "pace"`) is recomputed, not checked.
        pace = row_pace_500(rows, i) if derives_power(modality) else None
        if pace is not None and watts is not None and row.get("watts_source") != "pace":
            expected = watts_from_pace(pace)
            if abs(expected - watts) > watts_tolerance(expected):
                issues.append(
                    {
                        "split_index": row["split_index"],
                        "field": "watts",
                        "message": (
                            f"{watts:g} W doesn't match the split: Catch calculates {expected:.0f} W from "
                            f"{split_s:.1f}s over {_row_distance_delta(rows, i):.0f} m. Fix the split, or clear the watts."
                        ),
                    }
                )

    return {"ok": len(issues) == 0, "issues": issues}


def aggregate_from_splits(rows: list[dict], modality: Optional[str] = None) -> dict:
    """Totals/averages for the piece's own summary fields, derived from its splits rather
    than re-entered separately. avg_split_s is pace per split_m (500 m rowing, 1000 m bike) — total time / total distance,
    what the PM5's own summary row shows. (Session 31, launch audit L-10: it used to be the
    plain mean of the split *durations*, which is only right when every split is exactly
    500 m — a short last split or 1000 m/timed splits gave a wrong average.) avg_rate stays an
    unweighted mean of the typed values. Session 34: avg_watts is `piece_avg_watts` — from the
    average pace on a rowing erg, never a mean of split watts (power is cubic in pace)."""
    defined_splits = [r["split_s"] for r in rows if r.get("split_s") is not None]
    rates = [r["rate"] for r in rows if r.get("rate") is not None]
    duration_s = sum(defined_splits) if len(defined_splits) == len(rows) and rows else None
    distance_m = rows[-1]["distance_m"] if rows and rows[-1].get("distance_m") is not None else None
    split_m = split_m_for(modality)
    avg_split_s = None
    if duration_s is not None and distance_m:
        avg_split_s = duration_s / distance_m * split_m
    else:
        timed = [(r["split_s"], _row_distance_delta(rows, i)) for i, r in enumerate(rows) if r.get("split_s") is not None]
        if timed and all(d for _, d in timed):
            avg_split_s = sum(t for t, _ in timed) / sum(d for _, d in timed) * split_m
    avg_watts, basis = piece_avg_watts(modality, avg_split_s, rows)
    return {
        "duration_s": duration_s,
        "distance_m": distance_m,
        "avg_split_s": avg_split_s,
        "avg_rate": (sum(rates) / len(rates)) if rates else None,
        "avg_watts": avg_watts,
        "avg_watts_basis": basis,
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
