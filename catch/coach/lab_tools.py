from __future__ import annotations

"""Session 36: analysis tools for the coach and MCP, merged into catch.coach.tools.TOOLS.

Every one reads through the same services the app's pages use (records, the Performance Lab, load history, goals), so the coach and
the screen can't disagree. Each row carries a `ref` — an in-app path ("/workouts/123", "/tests/piece/4") the coach cites and the
app turns into a link — and says whether a figure was measured, worked out, or is an estimate. Nothing here writes."""

import json
from datetime import date, timedelta
from typing import Any, Optional

from sqlmodel import Session

from catch.core import localtime
from catch.sync.activity_days import canonical_in_days

MAX_PERIOD_DAYS = 366
_RANK_METRICS = ("avg_power", "distance", "duration", "avg_hr", "split")


def _date(v: Any) -> Optional[date]:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise ValueError(f"'{v}' is not a date (YYYY-MM-DD)") from None


def _period(session: Session, args: dict, default_days: int = 30) -> tuple[date, date]:
    end = _date(args.get("to")) or localtime.today(session)
    start = _date(args.get("from")) or end - timedelta(days=default_days - 1)
    if start > end:
        raise ValueError("'from' must be on or before 'to'")
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise ValueError(f"Ask for at most {MAX_PERIOD_DAYS} days at a time")
    return start, end


def _ov(c) -> dict:
    return json.loads(c.overrides_json) if c.overrides_json else {}


def _counted(session: Session, start: date, end: date) -> list:
    return [c for c in canonical_in_days(session, start, end) if c.start is not None and not _ov(c).get("exclude_from_totals")]


def _workout_row(session: Session, c) -> dict:
    split = (c.duration / c.distance * (1000.0 if c.sport_family == "cycling" else 500.0)) if c.duration and c.distance and c.sport_family in ("rowing", "cycling") else None
    return {
        "ref": f"/workouts/{c.id}", "id": c.id, "date": localtime.day_of(session, c).isoformat(), "title": _ov(c).get("title") or c.title,
        "sport_family": c.sport_family, "category": c.category, "duration_s": c.duration, "distance_m": c.distance,
        "avg_split_s": split, "split_unit_m": 1000 if c.sport_family == "cycling" else 500 if split else None,
        "avg_power_w": c.avg_power, "avg_hr_bpm": c.avg_hr, "measured": "provider figures; the split is worked out from time and distance",
    }


def _totals(rows: list) -> dict:
    by_sport: dict[str, float] = {}
    for c in rows:
        by_sport[c.sport_family or "other"] = by_sport.get(c.sport_family or "other", 0.0) + (c.duration or 0.0) / 60.0
    return {
        "sessions": len(rows), "minutes": round(sum((c.duration or 0.0) for c in rows) / 60.0, 1),
        "distance_m": round(sum((c.distance or 0.0) for c in rows)), "training_days": len({c.local_date for c in rows}),
        "minutes_by_sport": {k: round(v, 1) for k, v in by_sport.items()},
    }


def _summarize_period(session: Session, args: dict, ctx: dict) -> dict:
    start, end = _period(session, args)
    days = (end - start).days + 1
    rows = _counted(session, start, end)
    prev = _counted(session, start - timedelta(days=days), start - timedelta(days=1))
    cur, before = _totals(rows), _totals(prev)

    def change(k: str) -> Optional[float]:
        return round((cur[k] - before[k]) / before[k] * 100.0, 1) if before[k] else None

    from catch.sync.records import records

    rec = records(session, "rowing_erg", start, end)
    bests = [{"record": r["key"], "ref": r["best"]["ref"], "date": r["best"]["date"].isoformat(), "duration_s": r["best"]["duration_s"],
              "distance_m": r["best"]["distance_m"], "kind": r["best"]["label"]}
             for g in ("distance", "duration") for r in rec[g] if r["best"]]
    longest = sorted(rows, key=lambda c: c.duration or 0, reverse=True)[:3]
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "totals": cur,
        "previous_period": {"from": (start - timedelta(days=days)).isoformat(), "to": (start - timedelta(days=1)).isoformat(), "totals": before},
        "change_pct": {k: change(k) for k in ("sessions", "minutes", "distance_m")},
        "longest_sessions": [_workout_row(session, c) for c in longest],
        "best_efforts_in_period": bests,
        "notes": [
            "Counts completed workouts by their own local day; workouts excluded from totals are left out; a session recorded by two devices counts once.",
            "Planned sessions are never counted.",
        ],
    }


def _compare_tests(session: Session, args: dict, ctx: dict) -> dict:
    from catch.sync import erg_test

    test_type = args.get("test_type") or "2000m"
    n = max(2, min(int(args.get("count") or 3), 10))
    rows = [r for r in erg_test.list_tests(session, test_type) if r.get("modality", "rowing_erg") == "rowing_erg"][:n]
    rows = list(reversed(rows))  # oldest first
    out = []
    for r in rows:
        split = (r["duration_s"] / r["distance_m"] * 500.0) if r.get("duration_s") and r.get("distance_m") else None
        out.append({
            "ref": f"/tests/piece/{r['piece_id']}" if r.get("piece_id") else f"/tests/{r['canonical_id']}",
            "kind": r.get("kind"), "date": r.get("date"), "distance_m": r.get("distance_m"), "duration_s": r.get("duration_s"),
            "avg_split_s_per_500m": split, "avg_power_w": r.get("avg_power"), "avg_rate_spm": r.get("avg_stroke_rate"), "avg_hr_bpm": r.get("avg_hr"),
        })
    for i in range(1, len(out)):
        a, b = out[i - 1], out[i]
        if a["duration_s"] and b["duration_s"] and a["distance_m"] and b["distance_m"]:
            b["change_vs_previous"] = {"time_s": round(b["duration_s"] - a["duration_s"], 1),
                                       "split_s": round(b["avg_split_s_per_500m"] - a["avg_split_s_per_500m"], 1) if a["avg_split_s_per_500m"] and b["avg_split_s_per_500m"] else None}
    return {
        "test_type": test_type, "count": len(out), "tests": out,
        "note": "Confirmed tests and saved pieces of this type, oldest first; a negative change is faster. Fewer than asked for means fewer exist."
        if out else "No confirmed tests or pieces of this type yet.",
    }


def _rank_workouts(session: Session, args: dict, ctx: dict) -> dict:
    metric = args.get("metric") or "avg_power"
    if metric not in _RANK_METRICS:
        raise ValueError(f"metric must be one of {list(_RANK_METRICS)}")
    start, end = _period(session, args, default_days=90)
    limit = max(1, min(int(args.get("limit") or 5), 20))
    sport = args.get("sport")
    rows = [c for c in _counted(session, start, end) if not sport or c.sport_family == sport]
    items = [_workout_row(session, c) for c in rows]
    key = {"avg_power": "avg_power_w", "distance": "distance_m", "duration": "duration_s", "avg_hr": "avg_hr_bpm", "split": "avg_split_s"}[metric]
    items = [i for i in items if i[key] is not None]
    if metric == "split":
        items = [i for i in items if (i["distance_m"] or 0) >= 1000]
    items.sort(key=lambda i: i[key], reverse=metric != "split")
    return {
        "metric": metric, "period": {"from": start.isoformat(), "to": end.isoformat()}, "sport": sport, "workouts": items[:limit],
        "considered": len(items),
        "note": "Whole-workout averages from the provider; a long easy session and a short hard one aren't alike, so compare like with like."
        + (" Split ranks only workouts of 1,000 m or more." if metric == "split" else ""),
    }


def _get_split_by_rate(session: Session, args: dict, ctx: dict) -> dict:
    from catch.sync.performance_lab import split_by_rate

    out = split_by_rate(session, _date(args.get("from")), _date(args.get("to")))
    out["note"] = ("Every Concept2 rowing stroke, grouped by stroke rate, the earlier half of the period beside the recent half. A figure "
                   f"needs {out['min_strokes']} strokes from {out['min_sessions']} sessions; drag factor and session purpose aren't accounted for.")
    out["ref"] = "/lab"
    return out


def _get_hr_at_workload(session: Session, args: dict, ctx: dict) -> dict:
    from catch.sync.performance_lab import hr_at_workload

    out = hr_at_workload(session, _date(args.get("from")), _date(args.get("to")))
    out["note"] = ("Continuous erg sessions of 10+ minutes by average power. A lower heart rate at the same power usually means better aerobic "
                   "fitness, but heat, fatigue, caffeine, illness and a different HR sensor all move it.")
    out["ref"] = "/lab"
    return out


def _get_records(session: Session, args: dict, ctx: dict) -> dict:
    from catch.sync.records import records

    modality = args.get("modality") or "rowing_erg"
    if modality not in ("rowing_erg", "bike"):
        raise ValueError("modality must be rowing_erg or bike")
    r = records(session, modality, _date(args.get("from")), _date(args.get("to")))

    def slim(row: dict) -> dict:
        b = row["best"]
        return {"record": row["key"], "best": None if b is None else {k: b[k] for k in ("date", "distance_m", "duration_s", "pace_s", "split_m", "avg_watts", "watts_basis", "label", "verified", "ref")},
                "improvements": len(row["history"]), "efforts": row["count"]}

    return {
        "modality": modality, "distance": [slim(x) for x in r["distance"]], "duration": [slim(x) for x in r["duration"]], "power": [slim(x) for x in r["power"]],
        "rules": "Whole continuous efforts only (results and pieces); interval sessions and estimates never count; excluded workouts are left out. "
        "label: test = confirmed test, piece = saved piece, training = ordinary result. watts_basis derived = worked out from pace.",
        "ref": "/lab",
    }


def _get_goals(session: Session, args: dict, ctx: dict) -> dict:
    from catch.sync import goals

    view = args.get("view") or "active"
    if view not in ("active", "history", "all"):
        raise ValueError("view must be active, history or all")
    return {"view": view, "goals": goals.list_goals(session, None if view == "all" else view), "ref": "/goals",
            "note": "Progress is computed from completed workouts and records. Never suggest training more to make up a weekly shortfall."}


def _get_load_history(session: Session, args: dict, ctx: dict) -> dict:
    from catch.sync.load_history import load_history

    weeks = max(5, min(int(args.get("weeks") or 12), 52))
    h = load_history(session, weeks)
    keep = ("week_start", "complete", "load", "monotony", "strain", "sessions", "minutes", "distance_m", "training_days", "avg_recovery")
    return {
        "weeks": [{k: w[k] for k in keep} for w in h["weeks"]], "months": h["months"], "recent_vs_baseline": h["comparison"],
        "rest_by_weekday_mon_first": h["rest_by_weekday"], "ref": "/trends",
        "note": "Training load is the day's TRIMP-unit sum without everyday steps. Monotony (Foster) = average daily load / its spread; strain = weekly "
        "load x monotony. Descriptive only — not a diagnosis or an injury prediction.",
    }


_RANGE = {"from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"}}

TOOLS: dict[str, dict] = {
    "summarize_period": {
        "fn": _summarize_period, "write": False,
        "description": "Totals for a period (default the last 30 days): sessions, minutes, metres, minutes by sport, the same for the period just "
        "before it with % change, the longest sessions and the best efforts at standard distances in the period. Each row has a ref path.",
        "input_schema": {"type": "object", "properties": {**_RANGE}, "additionalProperties": False},
    },
    "compare_tests": {
        "fn": _compare_tests, "write": False,
        "description": "The last N confirmed rowing tests or saved pieces of one type (default the last three 2000m), oldest first, each with time, split, "
        "watts, rate, HR and the change from the one before. Use for 'compare my last three 2k tests'.",
        "input_schema": {"type": "object", "properties": {
            "test_type": {"type": "string", "enum": ["500m", "1000m", "2000m", "5000m", "6000m", "10000m", "30min_r20", "30min", "60min"]},
            "count": {"type": "integer", "minimum": 2, "maximum": 10}}, "additionalProperties": False},
    },
    "rank_workouts": {
        "fn": _rank_workouts, "write": False,
        "description": "Workouts in a period (default 90 days) ranked by avg_power, distance, duration, avg_hr or split (fastest first). Use for "
        "'which workouts had the highest average power' or 'my strongest workouts this week'.",
        "input_schema": {"type": "object", "properties": {
            **_RANGE, "metric": {"type": "string", "enum": list(_RANK_METRICS)}, "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            "sport": {"type": "string", "enum": ["rowing", "cycling", "running", "strength", "other"]}}, "additionalProperties": False},
    },
    "get_split_by_rate": {
        "fn": _get_split_by_rate, "write": False,
        "description": "Average split at comparable stroke rates (2-spm bands), the earlier half of the period beside the recent half — 'has my split "
        "improved at the same rate?'. Only bands with enough strokes on both sides get a figure. Default period: the last year.",
        "input_schema": {"type": "object", "properties": {**_RANGE}, "additionalProperties": False},
    },
    "get_hr_at_workload": {
        "fn": _get_hr_at_workload, "write": False,
        "description": "Median heart rate at comparable power (20 W bands) in continuous erg sessions, earlier half of the period beside the recent "
        "half. Default period: the last year.",
        "input_schema": {"type": "object", "properties": {**_RANGE}, "additionalProperties": False},
    },
    "get_records": {
        "fn": _get_records, "write": False,
        "description": "Personal records: best time at 500m–10,000m, furthest in 30/60 min, best average power over 1–60 min, for the rowing erg "
        "or the bike; each says whether it was a confirmed test, a piece or an ordinary result, and links to it. Optional window.",
        "input_schema": {"type": "object", "properties": {**_RANGE, "modality": {"type": "string", "enum": ["rowing_erg", "bike"]}}, "additionalProperties": False},
    },
    "get_goals": {
        "fn": _get_goals, "write": False,
        "description": "The athlete's goals with progress computed from their training (distance, sessions, minutes or sessions a week, a split or "
        "power target). view: active (default), history or all.",
        "input_schema": {"type": "object", "properties": {"view": {"type": "string", "enum": ["active", "history", "all"]}}, "additionalProperties": False},
    },
    "get_load_history": {
        "fn": _get_load_history, "write": False,
        "description": "Week-by-week training load, Foster monotony and strain, sessions, minutes, metres and average recovery (default 12 weeks), "
        "monthly volume, and the last 4 weeks against the 12 before. Use for 'how has my training volume changed'.",
        "input_schema": {"type": "object", "properties": {"weeks": {"type": "integer", "minimum": 5, "maximum": 52}}, "additionalProperties": False},
    },
}
