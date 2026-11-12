from __future__ import annotations

"""Session 17 Part B.2: one-shot vision call (the athlete's own provider) that reads a photo of the PM5
monitor's screen into a piece draft. Mirrors catch/coach/nutrition_vision.py's shape
(lazy-imported `anthropic`, the athlete's own configured key/model/cap, a strict tool so the
reply is always structured) with one deliberate difference: every time value the model
returns is the screen's own display *string* (e.g. "1:36.8"), parsed into seconds here in
Python, rather than trusting the model to do time arithmetic — a model mis-adding m:ss.t
values would otherwise silently corrupt a number this app then validates as if it were exact.
"""

import re

from sqlmodel import Session

from catch.coach.providers.base import VisionRequest
from catch.coach.vision import VisionError, run_vision
from catch.core.principal import OWNER_ID

_MAX_TOKENS = 2048

_SPLIT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "distance_m": {"type": ["number", "null"], "description": "Cumulative distance shown for this split, or null if not visible."},
        "time": {"type": ["string", "null"], "description": "The split time exactly as displayed, e.g. '1:36.8'. Never compute or guess it."},
        "rate": {"type": ["number", "null"], "description": "Stroke rate (spm) for this split, or null if not shown."},
        "watts": {"type": ["number", "null"], "description": "Watts for this split, or null if not shown."},
        "hr": {"type": ["number", "null"], "description": "Heart rate for this split, or null if not shown."},
    },
    "required": ["distance_m", "time", "rate", "watts", "hr"],
    "additionalProperties": False,
}

# Same strict-tool rationale as nutrition_vision.py: an auto-chosen tool rather than forced
# tool_choice, since forced tool_choice 400s on several current models and this app's model
# is whatever the athlete configured, not one this code controls.
_TOOL = {
    "name": "record_piece_reading",
    "description": "Record exactly what's visible on the PM5 monitor screen in this photo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "total_time": {"type": ["string", "null"], "description": "Total elapsed time exactly as displayed, e.g. '6:32.4'. Null if not visible."},
            "total_distance_m": {"type": ["number", "null"]},
            "avg_split": {"type": ["string", "null"], "description": "Average split exactly as displayed, e.g. '1:38.2'. Null if not shown."},
            "avg_rate": {"type": ["number", "null"]},
            "avg_watts": {"type": ["number", "null"]},
            "drag_factor": {"type": ["integer", "null"]},
            "splits": {"type": "array", "items": _SPLIT_ITEM_SCHEMA},
            "notes": {"type": "string", "description": "Anything on screen that's ambiguous, partially obscured, or you're unsure how to read."},
        },
        "required": ["total_time", "total_distance_m", "avg_split", "avg_rate", "avg_watts", "drag_factor", "splits", "notes"],
        "additionalProperties": False,
    },
    "strict": True,
}

_SYSTEM_PROMPT = (
    "You are transcribing a photo of a Concept2 PM5 rowing monitor's screen for a rowing athlete's training log. "
    "Always call record_piece_reading with exactly what is visible on the screen — never guess, estimate, or compute "
    "a value that isn't directly readable. Use null for any field not shown or not legible in the photo. For every "
    "time value (total_time, avg_split, each split's time), transcribe the digits exactly as displayed (e.g. "
    "'1:36.8') — never convert, round, or do arithmetic on it. If the screen shows a splits table, include every row "
    "visible, in the order shown. Note anything ambiguous or partially obscured in `notes`."
)

_TIME_RE = re.compile(r"^(\d+):(\d+(?:\.\d+)?)$")


class PieceVisionError(RuntimeError):
    pass


def _parse_time_string(value: str | None, label: str, notes: list[str]) -> float | None:
    if value is None:
        return None
    m = _TIME_RE.match(value.strip())
    if not m:
        notes.append(f"Couldn't parse {label} '{value}' as m:ss — left blank, fill in by hand.")
        return None
    minutes, seconds = m.groups()
    return int(minutes) * 60 + float(seconds)


def _rows_from_splits(raw_splits: list[dict], notes: list[str]) -> list[dict]:
    rows = []
    for i, s in enumerate(raw_splits):
        rows.append(
            {
                "split_index": i + 1,
                "distance_m": s.get("distance_m"),
                "split_s": _parse_time_string(s.get("time"), f"split {i + 1} time", notes),
                "rate": s.get("rate"),
                "watts": s.get("watts"),
                "hr": s.get("hr"),
            }
        )
    return rows


def _normalize_splits(rows: list[dict], total_duration_s: float | None) -> list[dict]:
    """A PM5 screen (and the model's own transcription of it) isn't guaranteed to show the
    same two columns catch/analytics/piece.py's rows expect (cumulative distance, per-split
    time). Normalizes the two other real shapes a screen can show instead, found by an
    advisor review before any real photo was tried: a per-split *distance* column (500, 500,
    500, 500, repeated rather than cumulative) gets cumulated; a cumulative *elapsed time*
    column (1:36.8, 3:15.7, 5:14.7, 6:32.4 — recognized as strictly increasing with its last
    value close to the piece's own total) gets differenced into per-split durations. Neither
    transformation runs on a column that's already in the expected shape, since a real
    per-split distance sequence is essentially never constant and a real per-split time
    sequence essentially never sums exactly to its own last element."""
    distances = [r["distance_m"] for r in rows if r.get("distance_m") is not None]
    if len(distances) == len(rows) and len(distances) > 1 and len(set(distances)) == 1:
        cum = 0.0
        for r in rows:
            cum += r["distance_m"]
            r["distance_m"] = cum

    times = [r["split_s"] for r in rows if r.get("split_s") is not None]
    if (
        len(times) == len(rows)
        and len(times) > 1
        and all(times[i] <= times[i + 1] for i in range(len(times) - 1))
        and total_duration_s
        and abs(times[-1] - total_duration_s) <= max(1.0, 0.02 * total_duration_s)
    ):
        prev = 0.0
        for r in rows:
            cum_t = r["split_s"]
            r["split_s"] = cum_t - prev
            prev = cum_t
    return rows


async def estimate_piece_photo(session: Session, image_bytes: bytes, media_type: str, owner_id: str = OWNER_ID) -> dict:
    """Returns a piece draft: {splits, distance_m, duration_s, avg_rate, avg_watts,
    drag_factor, notes, validation, cost_usd} — never saved here (task Part B.2/B.4's "ending
    in the same editable review table" as typed entry; the photo itself is attached only
    after the athlete confirms, via catch/sync/piece.py's attach_photo). `validation` is
    computed here too (task Part B.3's "validate before showing" — the review table highlights
    issues immediately on the first render, not only after a later edit)."""
    try:
        result, turn_cost = await run_vision(
            session,
            "piece_photo_estimate",
            VisionRequest(
                system=_SYSTEM_PROMPT,
                user_text="Transcribe this PM5 screen exactly as shown.",
                image_bytes=image_bytes,
                media_type=media_type,
                tool={"name": _TOOL["name"], "description": _TOOL["description"], "input_schema": _TOOL["input_schema"]},
                max_tokens=_MAX_TOKENS,
            ),
            owner_id,
        )
    except VisionError as exc:
        raise PieceVisionError(str(exc)) from None

    notes: list[str] = [result.get("notes")] if result.get("notes") else []
    splits = _rows_from_splits(result.get("splits") or [], notes)
    total_duration_s = _parse_time_string(result.get("total_time"), "total time", notes)
    avg_split_s = _parse_time_string(result.get("avg_split"), "average split", notes)
    distance_m = result.get("total_distance_m")
    splits = _normalize_splits(splits, total_duration_s)

    from catch.analytics.piece import validate_splits

    return {
        "splits": splits,
        "distance_m": distance_m,
        "duration_s": total_duration_s,
        "avg_split_s": avg_split_s,
        "avg_rate": result.get("avg_rate"),
        "avg_watts": result.get("avg_watts"),
        "drag_factor": result.get("drag_factor"),
        "validation": validate_splits(splits, distance_m, total_duration_s),
        "notes": " ".join(notes) if notes else "",
        "cost_usd": turn_cost,
    }
