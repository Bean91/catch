"""Session 36: a planned session's targets against what was actually done. Pure, no I/O.

Rules that matter more than they look:
  * A row exists only for a target that was set. Nothing is compared against a target the plan
    didn't have, and no target is inferred.
  * Reps are paired by order, and only when the counts agree (work reps alone, or every planned
    block including the warm-up and cool-down). Anything else falls back to the whole session,
    and the reason is stated rather than guessed around.
  * Per-rep targets (split, watts, rate, heart rate) are compared with the whole session only when
    the plan is one continuous block with nothing around it; otherwise a whole-session average
    would mix in warm-up and rest, so it isn't offered.
  * Every actual value carries how it was obtained (`measured` by the device, or `derived`, e.g. a
    split worked out from time and distance, or rowing watts from pace).
  * Ranges (rate, heart rate) say below / in range / above; single values (split, watts, time,
    distance) give the signed difference only. There is no pass/fail verdict.
"""

from __future__ import annotations

from typing import Any, Optional

METRICS = ("duration_s", "distance_m", "split_s", "watts", "rate", "hr")


def expand_planned(blocks: list[dict]) -> list[dict]:
    """One entry per planned rep, in order, with its block index and targets."""
    out: list[dict] = []
    for bi, b in enumerate(blocks or []):
        for r in range(int(b.get("reps", 1) or 1)):
            out.append({**b, "block_index": bi, "rep_in_block": r, "kind": b.get("kind") or "work"})
    return out


def _range_status(actual: float, lo: Optional[float], hi: Optional[float]) -> str:
    if lo is not None and actual < lo:
        return "below"
    if hi is not None and actual > hi:
        return "above"
    return "in_range"


def _value(actual: dict, key: str) -> tuple[Optional[float], Optional[str]]:
    v = actual.get(key)
    if v is None:
        return None, None
    return float(v), (actual.get("basis") or {}).get(key, "measured")


def rep_metrics(target: dict, actual: dict) -> list[dict]:
    """The comparisons one planned rep supports against one recorded rep."""
    rows: list[dict] = []

    def single(metric: str, target_value: Optional[float], actual_key: str) -> None:
        if target_value is None:
            return
        a, basis = _value(actual, actual_key)
        rows.append({
            "metric": metric,
            "target": {"value": float(target_value)},
            "actual": a,
            "actual_basis": basis,
            "delta": (a - float(target_value)) if a is not None else None,
        })

    def ranged(metric: str, lo: Optional[float], hi: Optional[float], actual_key: str) -> None:
        if lo is None and hi is None:
            return
        a, basis = _value(actual, actual_key)
        rows.append({
            "metric": metric,
            "target": {"min": lo, "max": hi},
            "actual": a,
            "actual_basis": basis,
            "status": _range_status(a, lo, hi) if a is not None else None,
        })

    # A distance rep is described by its distance; a duration carried beside it is the planner's estimate, not a target.
    if target.get("work_m") is not None:
        single("distance_m", target["work_m"], "distance_m")
    elif target.get("work_min") is not None:
        single("duration_s", target["work_min"] * 60.0, "duration_s")
    single("split_s", target.get("split_s"), "split_s")
    single("watts", target.get("watts"), "watts")
    ranged("rate", target.get("rate_min"), target.get("rate_max"), "rate")
    ranged("hr", target.get("hr_min"), target.get("hr_max"), "hr")
    return rows


def _has_rep_targets(rep: dict) -> bool:
    return any(rep.get(k) is not None for k in ("split_s", "watts", "rate_min", "rate_max", "hr_min", "hr_max", "work_m", "work_min"))


def compare(planned: dict, actual_reps: list[dict], actual_whole: dict, *, reps_source: Optional[str] = None) -> dict:
    """`planned` is the planned row's dict (`structure`, `duration_min`, `distance_m`).
    `actual_reps`: recorded reps in order, each `{duration_s, distance_m, split_s, watts, rate, hr,
    basis: {metric: "measured"|"derived"}}` (missing values None). `actual_whole`: the same keys for
    the whole session. `reps_source` names where the reps came from, for the screen."""
    blocks = planned.get("structure") or []
    all_reps = expand_planned(blocks)
    work = [r for r in all_reps if r["kind"] == "work"]

    totals: list[dict] = []
    if planned.get("duration_min"):
        a, basis = _value(actual_whole, "duration_s")
        target = float(planned["duration_min"]) * 60.0
        totals.append({"metric": "duration_s", "target": {"value": target}, "actual": a, "actual_basis": basis, "delta": (a - target) if a is not None else None})
    if planned.get("distance_m"):
        a, basis = _value(actual_whole, "distance_m")
        target = float(planned["distance_m"])
        totals.append({"metric": "distance_m", "target": {"value": target}, "actual": a, "actual_basis": basis, "delta": (a - target) if a is not None else None})

    paired: list[tuple[dict, dict]] = []
    mode, reason = "whole", None
    if actual_reps and work and len(actual_reps) == len(work):
        paired = list(zip(work, actual_reps))
        mode = "per_rep"
    elif actual_reps and len(actual_reps) == len(all_reps) and len(all_reps) > len(work):
        paired = list(zip(all_reps, actual_reps))
        mode = "per_rep"
    elif not work:
        reason = "The plan has no structured reps."
    elif not actual_reps:
        reason = "This recording has no per-rep data, so only the session as a whole can be compared."
    else:
        reason = f"The plan has {len(work)} work rep{'s' if len(work) != 1 else ''} and the recording has {len(actual_reps)}, so reps aren't paired."

    reps_out = []
    for i, (target, actual) in enumerate(paired):
        if not _has_rep_targets(target):
            continue
        reps_out.append({
            "index": i,
            "block_index": target["block_index"],
            "kind": target["kind"],
            "metrics": rep_metrics(target, actual),
        })

    whole_metrics: list[dict] = []
    continuous = len(all_reps) == 1 and len(work) == 1
    if mode == "whole" and continuous:
        whole_metrics = [m for m in rep_metrics(work[0], actual_whole) if m["metric"] not in ("duration_s", "distance_m")]
        if whole_metrics:
            reason = None
    elif mode == "whole" and work and any(_has_rep_targets({k: v for k, v in r.items() if k not in ("work_m", "work_min")}) for r in work):
        reason = (reason or "") + " Rep targets aren't compared with a whole-session average, which would include warm-up and rest."

    has_targets = bool(totals) or any(_has_rep_targets(r) for r in all_reps)
    return {
        "mode": mode if (paired or whole_metrics or totals) else "none",
        "reason": reason.strip() if reason else None,
        "reps_source": reps_source if paired else None,
        "totals": totals,
        "reps": reps_out,
        "whole": whole_metrics,
        "has_targets": has_targets,
    }


def split_from(duration_s: Optional[float], distance_m: Optional[float], split_m: float) -> Optional[float]:
    if not duration_s or not distance_m:
        return None
    return duration_s / distance_m * split_m


def actual_from_values(*, duration_s: Any = None, distance_m: Any = None, split_s: Any = None, watts: Any = None, rate: Any = None,
                       hr: Any = None, split_m: float = 500.0, basis: Optional[dict] = None) -> dict:
    """Builds one actual-values dict. A split that wasn't reported is worked out from time and distance and marked derived."""
    b = dict(basis or {})
    if split_s is None:
        split_s = split_from(duration_s, distance_m, split_m)
        if split_s is not None:
            b.setdefault("split_s", "derived")
    return {"duration_s": duration_s, "distance_m": distance_m, "split_s": split_s, "watts": watts, "rate": rate, "hr": hr, "basis": b}
