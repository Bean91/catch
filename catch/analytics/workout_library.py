from __future__ import annotations

"""Session 22 (see PLAN.md, docs/library.md): workout-template validation and arithmetic. Pure, no I/O.

A template's `structure` is
    {"warmup": {...}?, "blocks": [...], "cooldown": {...}?, "strength_items": [...]}
A block is {reps, work_s | work_m, rest_s?, zone?, rate_min?, rate_max?, split_s?, watts?, note?}.
Units are seconds and metres (rest in seconds), like the piece-interval rows; `to_planned_fields`
converts to the calendar's minutes-based `structure` vocabulary.

Rules that matter more than they look:
  * Rest follows every rep *except the last rep of the last block* — "4 x 500m r1:00" has three
    rests. (Not piece_intervals.expand_repeat, which also drops the last rest of every block and
    would wrongly erase the rest between ladder steps.)
  * A duration or distance is only reported when it can be known. A distance block with no
    split/watts target has no duration, and nothing is invented: `duration_basis` says
    exact | estimated | unknown, and a template with unknown duration schedules without one.
  * Validation never corrects a value; it returns `{ok, issues}` naming each problem."""

from typing import Any, Optional

from catch.analytics.erg_math import pace_from_watts
from catch.analytics.piece import SPLIT_M_BY_MODALITY
from catch.analytics.piece_intervals import MAX_DURATION_S, MAX_WORK_DISTANCE_M, RATE_RANGE
from catch.analytics.planning import SESSION_TYPES
from catch.analytics.zones import ZONE_ORDER

WORKOUT_TYPES = (
    "erg_intervals", "steady_state", "rate_ladder", "distance_piece", "time_piece", "strength", "on_water", "custom",
)
DIFFICULTIES = ("easy", "moderate", "hard")
MAX_BLOCKS = 30
MAX_REPS = 100
MAX_STRENGTH_ITEMS = 30
MAX_TAGS = 10
SPLIT_RANGE = (60.0, 300.0)  # seconds per 500 m (rowing erg / on the water)
# Session 36: a bike's split is per 1000 m, its own display unit (the piece convention, analytics/piece.py), never a rowing pace.
SPLIT_RANGE_BY_BASIS = {500.0: SPLIT_RANGE, 1000.0: (60.0, 480.0)}
WATTS_RANGE = (20.0, 1500.0)
HR_RANGE = (40, 230)
CADENCE_RANGE = (30.0, 150.0)  # a bike's rate target is pedal cadence (rpm), not a stroke rate

_DEFAULT_SESSION_TYPE = {
    "erg_intervals": "erg", "steady_state": "erg", "rate_ladder": "erg", "distance_piece": "erg",
    "time_piece": "erg", "strength": "strength", "on_water": "on_water", "custom": "other",
}
_ALLOWED_SESSION_TYPES = {
    "erg_intervals": ("erg",), "steady_state": ("erg", "on_water", "run", "bike", "cross", "other"),
    "rate_ladder": ("erg", "on_water"), "distance_piece": ("erg", "on_water"), "time_piece": ("erg", "on_water"),
    "strength": ("strength",), "on_water": ("on_water",), "custom": tuple(t for t in SESSION_TYPES if t != "rest"),
}
_SEGMENT_KEYS = ("duration_min", "distance_m", "zone", "note", "rate_min", "rate_max", "hr_min", "hr_max")
_BLOCK_KEYS = ("reps", "work_s", "work_m", "rest_s", "zone", "rate_min", "rate_max", "split_s", "watts", "hr_min", "hr_max", "note")


def split_basis_m(session_type: Optional[str] = None, sport_family: Optional[str] = None) -> float:
    """The distance a split target is quoted per: 1000 m for a bike, 500 m for everything rowed."""
    if session_type == "bike" or sport_family == "cycling":
        return SPLIT_M_BY_MODALITY["bike"]
    return SPLIT_M_BY_MODALITY["rowing_erg"]


def _watts_from_pace_applies(split_m: float) -> bool:
    # The Concept2 power formula describes a rowing erg; a bike's watts are measured, never derived from its pace.
    return split_m == SPLIT_M_BY_MODALITY["rowing_erg"]
_STRENGTH_KEYS = ("exercise_id", "target_sets", "target_reps", "note")


def default_session_type(workout_type: str) -> str:
    return _DEFAULT_SESSION_TYPE.get(workout_type, "other")


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_template(fields: dict) -> dict:
    """`{ok, issues: [{path, message}]}`. `fields` holds name, workout_type, optional session_type,
    difficulty, target_zone, tags, purpose, description and `structure`."""
    issues: list[dict] = []

    def add(path: str, message: str) -> None:
        issues.append({"path": path, "message": message})

    name = fields.get("name")
    if not isinstance(name, str) or not name.strip():
        add("name", "A name is required.")
    elif len(name) > 120:
        add("name", "Keep the name under 120 characters.")
    for key, limit in (("description", 2000), ("purpose", 500)):
        v = fields.get(key)
        if v is not None and (not isinstance(v, str) or len(v) > limit):
            add(key, f"{key} must be text up to {limit} characters.")

    wt = fields.get("workout_type")
    if wt not in WORKOUT_TYPES:
        add("workout_type", f"workout_type must be one of {list(WORKOUT_TYPES)}.")
    st = fields.get("session_type")
    if st is not None and st not in SESSION_TYPES:
        add("session_type", f"session_type must be one of {[t for t in SESSION_TYPES if t != 'rest']}.")
    elif st is not None and wt in WORKOUT_TYPES and st not in _ALLOWED_SESSION_TYPES[wt]:
        add("session_type", f"A {wt} template can't be session_type '{st}'.")
    d = fields.get("difficulty")
    if d is not None and d not in DIFFICULTIES:
        add("difficulty", f"difficulty must be one of {list(DIFFICULTIES)}.")
    z = fields.get("target_zone")
    if z is not None and z not in ZONE_ORDER:
        add("target_zone", f"target_zone must be one of {ZONE_ORDER}.")
    tags = fields.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or len(tags) > MAX_TAGS or not all(isinstance(t, str) and 0 < len(t.strip()) <= 30 for t in tags):
            add("tags", f"tags must be up to {MAX_TAGS} short text labels.")

    structure = fields.get("structure") or {}
    if not isinstance(structure, dict):
        add("structure", "structure must be an object.")
        return {"ok": False, "issues": issues}
    unknown = set(structure) - {"warmup", "blocks", "cooldown", "strength_items"}
    if unknown:
        add("structure", f"Unknown structure key(s): {sorted(unknown)}.")

    split_m = split_basis_m(st or (default_session_type(wt) if wt in WORKOUT_TYPES else None), fields.get("sport_family"))
    for seg in ("warmup", "cooldown"):
        _validate_segment(structure.get(seg), f"structure.{seg}", add, split_m)

    blocks = structure.get("blocks") or []
    if not isinstance(blocks, list):
        add("structure.blocks", "blocks must be a list.")
        blocks = []
    if len(blocks) > MAX_BLOCKS:
        add("structure.blocks", f"At most {MAX_BLOCKS} blocks.")
    for i, b in enumerate(blocks):
        _validate_block(b, f"structure.blocks[{i}]", add, split_m)

    items = structure.get("strength_items") or []
    if not isinstance(items, list):
        add("structure.strength_items", "strength_items must be a list.")
        items = []
    if len(items) > MAX_STRENGTH_ITEMS:
        add("structure.strength_items", f"At most {MAX_STRENGTH_ITEMS} exercises.")
    for i, it in enumerate(items):
        _validate_strength_item(it, f"structure.strength_items[{i}]", add)

    if wt in WORKOUT_TYPES:
        _validate_shape(wt, fields, blocks, items, add)
    return {"ok": not issues, "issues": issues}


def _validate_segment(seg: Any, path: str, add, split_m: float = 500.0) -> None:
    if seg is None:
        return
    if not isinstance(seg, dict):
        add(path, "Must be an object.")
        return
    for k in set(seg) - set(_SEGMENT_KEYS):
        add(f"{path}.{k}", "Unknown field.")
    dur, dist = seg.get("duration_min"), seg.get("distance_m")
    if dur is not None and dist is not None:
        add(path, "Give a duration or a distance, not both.")
    if dur is not None and (not _is_num(dur) or dur <= 0 or dur * 60 > MAX_DURATION_S):
        add(f"{path}.duration_min", "Duration must be greater than zero and under 12 hours.")
    if dist is not None and (not _is_num(dist) or dist <= 0 or dist > MAX_WORK_DISTANCE_M):
        add(f"{path}.distance_m", "Distance must be greater than zero and under 100 km.")
    if seg.get("zone") is not None and seg["zone"] not in ZONE_ORDER:
        add(f"{path}.zone", f"zone must be one of {ZONE_ORDER}.")
    if seg.get("note") is not None and (not isinstance(seg["note"], str) or len(seg["note"]) > 200):
        add(f"{path}.note", "note must be text up to 200 characters.")
    _validate_rate_hr(seg, path, add, split_m)


def _validate_rate_hr(b: dict, path: str, add, split_m: float = 500.0) -> None:
    rmin, rmax = b.get("rate_min"), b.get("rate_max")
    bike = not _watts_from_pace_applies(split_m)
    lo, hi = CADENCE_RANGE if bike else RATE_RANGE
    for key, v in (("rate_min", rmin), ("rate_max", rmax)):
        if v is not None and (not _is_num(v) or not lo <= v <= hi):
            add(f"{path}.{key}", f"Cadence should be {lo:.0f}-{hi:.0f} rpm." if bike else f"Stroke rate should be {lo:.0f}-{hi:.0f} spm.")
    if _is_num(rmin) and _is_num(rmax) and rmin > rmax:
        add(f"{path}.rate_min", "rate_min can't be above rate_max.")
    hmin, hmax = b.get("hr_min"), b.get("hr_max")
    for key, v in (("hr_min", hmin), ("hr_max", hmax)):
        if v is not None and (not _is_num(v) or not HR_RANGE[0] <= v <= HR_RANGE[1]):
            add(f"{path}.{key}", f"Heart-rate target should be {HR_RANGE[0]}-{HR_RANGE[1]} bpm.")
    if _is_num(hmin) and _is_num(hmax) and hmin > hmax:
        add(f"{path}.hr_min", "hr_min can't be above hr_max.")


def _validate_block(b: Any, path: str, add, split_m: float = 500.0) -> None:
    if not isinstance(b, dict):
        add(path, "Each block must be an object.")
        return
    for k in set(b) - set(_BLOCK_KEYS):
        add(f"{path}.{k}", "Unknown field.")
    reps = b.get("reps", 1)
    if not _is_int(reps) or not 1 <= reps <= MAX_REPS:
        add(f"{path}.reps", f"reps must be a whole number from 1 to {MAX_REPS}.")
    ws, wm = b.get("work_s"), b.get("work_m")
    if (ws is None) == (wm is None):
        add(path, "Give exactly one of work_s (time) or work_m (distance).")
    if ws is not None and (not _is_num(ws) or ws <= 0 or ws > MAX_DURATION_S):
        add(f"{path}.work_s", "Work time must be greater than zero and under 12 hours.")
    if wm is not None and (not _is_num(wm) or wm <= 0 or wm > MAX_WORK_DISTANCE_M):
        add(f"{path}.work_m", "Work distance must be greater than zero and under 100 km.")
    rest = b.get("rest_s")
    if rest is not None and (not _is_num(rest) or rest < 0 or rest > MAX_DURATION_S):
        add(f"{path}.rest_s", "Rest can't be negative or longer than 12 hours.")
    _validate_rate_hr(b, path, add, split_m)
    split = b.get("split_s")
    lo, hi = SPLIT_RANGE_BY_BASIS.get(split_m, SPLIT_RANGE)
    if split is not None and (not _is_num(split) or not lo <= split <= hi):
        add(f"{path}.split_s", f"Target split should be {int(lo // 60)}:{int(lo % 60):02d}-{int(hi // 60)}:{int(hi % 60):02d} per {int(split_m)}m.")
    watts = b.get("watts")
    if watts is not None and (not _is_num(watts) or not WATTS_RANGE[0] <= watts <= WATTS_RANGE[1]):
        add(f"{path}.watts", f"Target watts should be {WATTS_RANGE[0]:.0f}-{WATTS_RANGE[1]:.0f}.")
    if split is not None and watts is not None:
        add(path, "Give a split or watts target, not both.")
    if b.get("zone") is not None and b["zone"] not in ZONE_ORDER:
        add(f"{path}.zone", f"zone must be one of {ZONE_ORDER}.")
    if b.get("note") is not None and (not isinstance(b["note"], str) or len(b["note"]) > 200):
        add(f"{path}.note", "note must be text up to 200 characters.")


def _validate_strength_item(it: Any, path: str, add) -> None:
    if not isinstance(it, dict):
        add(path, "Each exercise must be an object.")
        return
    for k in set(it) - set(_STRENGTH_KEYS):
        add(f"{path}.{k}", "Unknown field.")
    if not _is_int(it.get("exercise_id")):
        add(f"{path}.exercise_id", "exercise_id is required.")
    for k, hi in (("target_sets", 20), ("target_reps", 100)):
        v = it.get(k)
        if v is not None and (not _is_int(v) or not 1 <= v <= hi):
            add(f"{path}.{k}", f"{k} must be a whole number from 1 to {hi}.")
    if it.get("note") is not None and (not isinstance(it["note"], str) or len(it["note"]) > 200):
        add(f"{path}.note", "note must be text up to 200 characters.")


def _validate_shape(wt: str, fields: dict, blocks: list, items: list, add) -> None:
    structure = fields.get("structure") or {}
    if wt == "strength":
        if blocks:
            add("structure.blocks", "A strength template lists exercises, not timed blocks.")
        if not items:
            add("structure.strength_items", "Add at least one exercise.")
        return
    if items:
        add("structure.strength_items", "Exercises belong in a strength template.")
    if wt == "steady_state":
        if len(blocks) != 1 or (isinstance(blocks[0], dict) and blocks[0].get("reps", 1) != 1):
            add("structure.blocks", "A steady-state session is one continuous block.")
        elif isinstance(blocks[0], dict) and blocks[0].get("rest_s"):
            add("structure.blocks[0].rest_s", "A steady-state session has no rest.")
    elif wt == "distance_piece":
        if len(blocks) != 1 or not isinstance(blocks[0], dict) or blocks[0].get("reps", 1) != 1 or blocks[0].get("work_m") is None:
            add("structure.blocks", "A distance piece is one block with a distance.")
    elif wt == "time_piece":
        if len(blocks) != 1 or not isinstance(blocks[0], dict) or blocks[0].get("reps", 1) != 1 or blocks[0].get("work_s") is None:
            add("structure.blocks", "A time piece is one block with a time.")
    elif wt == "rate_ladder":
        if len(blocks) < 2:
            add("structure.blocks", "A rate ladder needs at least two steps.")
        for i, b in enumerate(blocks):
            if isinstance(b, dict) and b.get("rate_min") is None and b.get("rate_max") is None:
                add(f"structure.blocks[{i}]", "Every step of a rate ladder needs a rate target.")
    elif wt == "erg_intervals":
        multi = len(blocks) > 1 or any(isinstance(b, dict) and isinstance(b.get("reps"), int) and b["reps"] > 1 for b in blocks)
        if not multi:
            add("structure.blocks", "Intervals need more than one rep or more than one block.")
    elif wt == "on_water":
        if not blocks:
            add("structure.blocks", "Add at least one block.")
    elif wt == "custom":
        if not blocks and not (fields.get("description") or "").strip():
            add("description", "A custom session needs blocks or a description.")
    _ = structure


# --- Arithmetic -------------------------------------------------------------------------------


def _split_for(block: dict, split_m: float = 500.0) -> Optional[float]:
    if block.get("split_s"):
        return float(block["split_s"])
    if block.get("watts") and _watts_from_pace_applies(split_m):
        return pace_from_watts(float(block["watts"]))
    return None


def _segment_amounts(work_s: Optional[float], work_m: Optional[float], split: Optional[float], split_m: float = 500.0) -> tuple[Optional[float], Optional[float], bool]:
    """(duration_s, distance_m, estimated) for one rep from whichever side is prescribed. The
    prescribed side is exact; the other is derived from the split/watts target, so `estimated`
    describes the derived side only."""
    if work_s is not None:
        if split:
            return work_s, work_s / split * split_m, True
        return work_s, None, False
    if work_m is not None:
        if split:
            return work_m / split_m * split, work_m, True
        return None, work_m, False
    return None, None, False


def summarize_template(structure: dict, target_zone: Optional[str] = None, split_m: float = 500.0) -> dict:
    """Totals for a *valid* structure. Every figure is None when it can't be known. `split_m` is the
    split basis (500 m rowed, 1000 m on a bike — `split_basis_m`)."""
    structure = structure or {}
    blocks = structure.get("blocks") or []
    work_s = work_m = rest_s = 0.0
    work_s_known = work_m_known = True
    duration_estimated = distance_estimated = False
    zone_minutes = {z: 0.0 for z in ZONE_ORDER}
    reps_total = sum(b.get("reps", 1) for b in blocks)
    seen = 0
    work_time_known = 0.0
    for b in blocks:
        reps = b.get("reps", 1)
        d, m, est = _segment_amounts(b.get("work_s"), b.get("work_m"), _split_for(b, split_m), split_m)
        if est:
            duration_estimated = duration_estimated or b.get("work_s") is None
            distance_estimated = distance_estimated or b.get("work_s") is not None
        if d is None:
            work_s_known = False
        else:
            work_s += reps * d
        if m is None:
            work_m_known = False
        else:
            work_m += reps * m
        if b.get("work_s") is not None:
            work_time_known += reps * b["work_s"]
            zone = b.get("zone") or target_zone
            if zone in zone_minutes:
                zone_minutes[zone] += reps * b["work_s"] / 60.0
        elif d is not None:
            zone = b.get("zone") or target_zone
            if zone in zone_minutes:
                zone_minutes[zone] += reps * d / 60.0
        seen += reps
        is_last_block_rep = seen == reps_total
        rests = reps - (1 if is_last_block_rep else 0)
        rest_s += max(rests, 0) * (b.get("rest_s") or 0.0)

    seg_s = seg_m = 0.0
    seg_s_known = seg_m_known = True
    for key in ("warmup", "cooldown"):
        seg = structure.get(key)
        if not seg:
            continue
        if seg.get("duration_min") is not None:
            seg_s += seg["duration_min"] * 60.0
            seg_m_known = False
        elif seg.get("distance_m") is not None:
            seg_m += seg["distance_m"]
            seg_s_known = False
    duration_known = work_s_known and seg_s_known and bool(blocks or structure.get("warmup") or structure.get("cooldown"))
    distance_known = work_m_known and seg_m_known and bool(blocks or structure.get("warmup") or structure.get("cooldown"))
    if not blocks:
        # Nothing timed or measured to total (strength / description-only custom sessions).
        duration_known = distance_known = False
    total_s = (work_s + rest_s + seg_s) if duration_known else None
    total_m = (work_m + seg_m) if distance_known else None
    basis = "unknown" if total_s is None else ("estimated" if duration_estimated else "exact")
    dist_basis = "unknown" if total_m is None else ("estimated" if distance_estimated else "exact")
    return {
        "block_count": len(blocks),
        "rep_count": reps_total,
        "work_duration_s": work_s if work_s_known and blocks else None,
        "rest_duration_s": rest_s if blocks else None,
        "warmup_duration_s": _seg_seconds(structure.get("warmup")),
        "cooldown_duration_s": _seg_seconds(structure.get("cooldown")),
        "work_distance_m": work_m if work_m_known and blocks else None,
        "total_duration_s": total_s,
        "total_distance_m": total_m,
        "duration_basis": basis,
        "distance_basis": dist_basis,
        "work_rest_ratio": (work_s / rest_s) if work_s_known and rest_s > 0 and work_s > 0 else None,
        "zone_minutes": {z: round(v, 2) for z, v in zone_minutes.items() if v > 0},
        "strength_exercise_count": len(structure.get("strength_items") or []),
    }


def _seg_seconds(seg: Optional[dict]) -> Optional[float]:
    if seg and seg.get("duration_min") is not None:
        return seg["duration_min"] * 60.0
    return None


def template_signature(structure: dict) -> Optional[str]:
    """Equivalence key like "4x500m/r60" (uniform) or "500m/r60+1000m/r0" — same convention as
    piece_intervals.interval_signature, so a template can be compared with a completed piece."""
    blocks = (structure or {}).get("blocks") or []
    if not blocks:
        return None
    parts = []
    for b in blocks:
        target = f"{_n(b['work_m'])}m" if b.get("work_m") is not None else f"{_n(b['work_s'])}s"
        parts.append((target, b.get("reps", 1), int(round(b.get("rest_s") or 0))))
    if len(parts) == 1:
        t, reps, rest = parts[0]
        return f"{reps}x{t}/r{rest}"
    return "+".join(f"{r}x{t}/r{rest}" for t, r, rest in parts)


def _n(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


# --- Calendar conversion ----------------------------------------------------------------------


_TARGET_KEYS = ("split_s", "watts", "rate_min", "rate_max", "hr_min", "hr_max")


def _targets(src: dict) -> dict:
    return {k: float(src[k]) for k in _TARGET_KEYS if src.get(k) is not None}


def to_planned_fields(template: dict) -> dict:
    """The calendar-planning fields (minus date) a scheduled copy of `template` carries.
    `duration_min`/`distance_m` are set only when summarize_template knows them, so the week
    summary and the plan-to-workout matcher see exactly the template's own figures. The
    structure uses planning's vocabulary (work_min/work_m/rest_min); a distance block whose
    duration is known also carries work_min so the planner's zone minutes agree with ours.

    Session 36: every target (split, watts, rate, heart rate) travels with its block, and the
    warm-up and cool-down are blocks of their own (`kind`), so a plan keeps what was prescribed and
    can be compared with what was done. They used to be folded into a free-text note and the
    description, which nothing could read back."""
    structure = template.get("structure") or {}
    split_m = split_basis_m(template.get("session_type"), template.get("sport_family"))
    summary = summarize_template(structure, template.get("target_zone"), split_m)
    blocks_out = []

    def segment(key: str) -> None:
        seg = structure.get(key)
        if not seg:
            return
        out: dict = {"reps": 1, "kind": key}
        if seg.get("duration_min") is not None:
            out["work_min"] = float(seg["duration_min"])
        if seg.get("distance_m") is not None:
            out["work_m"] = float(seg["distance_m"])
        if seg.get("zone"):
            out["zone"] = seg["zone"]
        out.update(_targets(seg))
        if seg.get("note"):
            out["note"] = str(seg["note"])[:200]
        blocks_out.append(out)

    segment("warmup")
    for b in structure.get("blocks") or []:
        out = {"reps": b.get("reps", 1)}
        d, _m, _est = _segment_amounts(b.get("work_s"), b.get("work_m"), _split_for(b, split_m), split_m)
        if b.get("work_s") is not None:
            out["work_min"] = b["work_s"] / 60.0
        elif d is not None:
            out["work_min"] = d / 60.0
        if b.get("work_m") is not None:
            out["work_m"] = float(b["work_m"])
        if b.get("rest_s"):
            out["rest_min"] = b["rest_s"] / 60.0
        if b.get("zone"):
            out["zone"] = b["zone"]
        out.update(_targets(b))
        if b.get("note"):
            out["note"] = str(b["note"])[:200]
        blocks_out.append(out)
    segment("cooldown")
    desc = template.get("description") or ""
    extra = []
    if structure.get("strength_items"):
        extra.append(f"{len(structure['strength_items'])} exercises")
    description = "\n".join(p for p in [desc, *extra] if p) or None
    fields: dict = {
        "session_type": template["session_type"],
        "title": template["name"],
        "description": description,
        "target_zone": template.get("target_zone"),
        "intensity_note": template.get("purpose"),
    }
    if summary["total_duration_s"] is not None:
        fields["duration_min"] = summary["total_duration_s"] / 60.0
    if summary["total_distance_m"] is not None:
        fields["distance_m"] = summary["total_distance_m"]
    if blocks_out:
        fields["structure"] = blocks_out
    return {k: v for k, v in fields.items() if v is not None}
