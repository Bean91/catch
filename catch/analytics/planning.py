from __future__ import annotations

"""Session 21 (see PLAN.md, docs/calendar.md): calendar planning math. Pure, no I/O — mirrors
every other analytics/*.py module's contract.

Two rules govern the whole module:
  * A plan is never a completed workout. Nothing here produces or consumes a CanonicalActivity
    row's totals; `planned_totals` sums *planned* rows only, and the DB layer
    (catch/sync/planning.py) is the only place the two are put side by side.
  * Time zones are explicit. Every function that buckets an instant into a calendar day takes
    `tz` (a tzinfo, or None for the host's local zone — what the rest of the app uses). The DB
    layer passes None; tests pass real zones so the day-boundary cases are covered."""

from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from catch.analytics.training_intelligence import _apply_hedge
from catch.analytics.zones import ZONE_ORDER

SESSION_TYPES = ("erg", "on_water", "run", "bike", "strength", "cross", "test", "rest", "other")
PHASE_KINDS = ("general_prep", "specific_prep", "pre_competition", "competition", "recovery")
EVENT_TYPES = ("race", "2k_test", "camp", "selection")
PRIORITIES = ("A", "B", "C")
PLANNED_STATUSES = ("planned", "skipped")

# What a planned session type implies about the completed workout's sport family. None means
# "any" (cross-training, an unspecified session, a test of any kind).
_TYPE_FAMILY = {
    "erg": "rowing",
    "on_water": "rowing",
    "run": "running",
    "bike": "cycling",
    "strength": "strength",
}

MAX_REPEAT_WEEKS = 26
MAX_REPEAT_ROWS = 200

# A suggestion below this score is not offered at all.
MATCH_THRESHOLD = 0.6


# --- Dates / time zones ---------------------------------------------------------------------


def local_date(dt: datetime, tz: tzinfo | None = None) -> date:
    """The calendar day an instant falls on. A naive datetime is read as UTC (SQLite hands
    timezone-aware columns back naive; every stored instant in this app is UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


def aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def today_in(tz: tzinfo | None = None, now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    return local_date(now, tz)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_dates(start: date) -> list[date]:
    return [start + timedelta(days=i) for i in range(7)]


def days_to_go(event_date: date, today: date) -> int:
    return (event_date - today).days


def local_day_utc_range(day: date, tz: tzinfo | None = None) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day as UTC instants — DST-safe, since the end is the
    *next local midnight*, not start + 24 h."""
    start = datetime(day.year, day.month, day.day, tzinfo=tz) if tz else datetime(day.year, day.month, day.day).astimezone()
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz) if tz else datetime(nxt.year, nxt.month, nxt.day).astimezone()
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


# --- Recurrence -----------------------------------------------------------------------------


def expand_repeat(start: date, repeat: dict | None) -> list[date]:
    """Expand `{"every": "weekly", "weekdays": [0, 2], "interval_weeks": 1, "until": date,
    "count": n}` into concrete dates, anchored at `start` (which is always the first one).
    Plain calendar dates, so a DST change can't shift a session by a day. No RRULE engine on
    purpose — the athlete edits individual rows afterwards, and the rows share a `series_id`."""
    if not repeat:
        return [start]
    if repeat.get("every", "weekly") != "weekly":
        raise ValueError("repeat.every must be 'weekly'")
    weekdays = repeat.get("weekdays") or [start.weekday()]
    if not all(isinstance(w, int) and 0 <= w <= 6 for w in weekdays):
        raise ValueError("repeat.weekdays must be integers 0 (Mon) to 6 (Sun)")
    interval = int(repeat.get("interval_weeks") or 1)
    if interval < 1:
        raise ValueError("repeat.interval_weeks must be at least 1")
    until = repeat.get("until")
    count = repeat.get("count")
    if until is None and count is None:
        raise ValueError("repeat needs an 'until' date or a 'count'")
    if count is not None and int(count) < 1:
        raise ValueError("repeat.count must be at least 1")
    limit_end = start + timedelta(weeks=MAX_REPEAT_WEEKS)
    if until is not None and until > limit_end:
        raise ValueError(f"repeat can't extend more than {MAX_REPEAT_WEEKS} weeks")
    first_week = week_start(start)
    out: list[date] = []
    week = 0
    while True:
        base = first_week + timedelta(weeks=week * interval)
        if base > limit_end:
            break
        for wd in sorted(set(weekdays)):
            day = base + timedelta(days=wd)
            if day < start:
                continue
            if until is not None and day > until:
                return out
            out.append(day)
            if count is not None and len(out) >= int(count):
                return out
            if len(out) > MAX_REPEAT_ROWS:
                raise ValueError(f"repeat would create more than {MAX_REPEAT_ROWS} sessions")
        week += 1
    if count is not None and len(out) < int(count):
        raise ValueError(f"repeat can't extend more than {MAX_REPEAT_WEEKS} weeks")
    return out


# --- Structure / validation -----------------------------------------------------------------


def validate_structure(blocks: Any) -> list[dict]:
    """A planned session's optional structure: a list of blocks
    `{"reps": int, "work_min": float?, "work_m": float?, "rest_min": float?, "zone": str?,
    "note": str?}`. Returns the cleaned list; raises ValueError naming the first bad block."""
    if blocks is None:
        return []
    if not isinstance(blocks, list):
        raise ValueError("structure must be a list of blocks")
    if len(blocks) > 30:
        raise ValueError("structure can have at most 30 blocks")
    out: list[dict] = []
    for i, raw in enumerate(blocks, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"block {i} must be an object")
        reps = raw.get("reps", 1)
        if not isinstance(reps, int) or isinstance(reps, bool) or not 1 <= reps <= 100:
            raise ValueError(f"block {i}: reps must be a whole number from 1 to 100")
        block: dict = {"reps": reps}
        for key in ("work_min", "work_m", "rest_min"):
            value = raw.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 100000:
                raise ValueError(f"block {i}: {key} must be a non-negative number")
            block[key] = float(value)
        if "work_min" not in block and "work_m" not in block:
            raise ValueError(f"block {i}: needs work_min or work_m")
        zone = raw.get("zone")
        if zone is not None:
            if zone not in ZONE_ORDER:
                raise ValueError(f"block {i}: zone must be one of {list(ZONE_ORDER)}")
            block["zone"] = zone
        note = raw.get("note")
        if note:
            block["note"] = str(note)[:200]
        out.append(block)
    return out


def structure_minutes(blocks: list[dict]) -> float | None:
    """Total timed minutes (work + rest). None when no block is timed (a distance-only
    structure has no honest duration without an assumed pace, and none is invented here)."""
    total = 0.0
    timed = False
    for b in blocks:
        work = b.get("work_min")
        if work is None:
            continue
        timed = True
        total += b["reps"] * (work + (b.get("rest_min") or 0.0))
    return total if timed else None


def validate_planned_fields(fields: dict) -> None:
    if "session_type" in fields and fields["session_type"] not in SESSION_TYPES:
        raise ValueError(f"session_type must be one of {list(SESSION_TYPES)}")
    zone = fields.get("target_zone")
    if zone is not None and zone not in ZONE_ORDER:
        raise ValueError(f"target_zone must be one of {list(ZONE_ORDER)}")
    for key in ("duration_min", "distance_m"):
        value = fields.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            raise ValueError(f"{key} must be a non-negative number")
    start_time = fields.get("start_time")
    if start_time is not None:
        try:
            datetime.strptime(start_time, "%H:%M")
        except (TypeError, ValueError):
            raise ValueError("start_time must be 'HH:MM'") from None
    status = fields.get("status")
    if status is not None and status not in PLANNED_STATUSES:
        raise ValueError(f"status must be one of {list(PLANNED_STATUSES)}")


def family_for_session_type(session_type: str) -> str | None:
    return _TYPE_FAMILY.get(session_type)


# --- Planned vs completed matching ----------------------------------------------------------


def match_score(planned: dict, activity: dict) -> dict | None:
    """Score one completed activity as a candidate for one planned session, or None when it
    can't be (a rest day, a different sport, more than a day away). Both are plain dicts:
    planned `{date, session_type, duration_min, distance_m}`, activity `{local_date, sport_family,
    category, duration_min, distance_m}`. The result is a *suggestion's* evidence — it never
    links anything."""
    if planned["session_type"] == "rest":
        return None
    gap = abs((activity["local_date"] - planned["date"]).days)
    if gap > 1:
        return None
    want = family_for_session_type(planned["session_type"])
    if want is not None and activity.get("sport_family") != want:
        return None

    score = 0.0
    reasons: list[str] = []
    if gap == 0:
        score += 0.4
        reasons.append("same day")
    else:
        score += 0.15
        reasons.append("one day apart")
    if want is not None:
        score += 0.3
        reasons.append("same sport")
    else:
        score += 0.1
    cat = activity.get("category")
    if planned["session_type"] in ("erg", "on_water") and cat in ("erg", "on_water"):
        if planned["session_type"] == cat:
            score += 0.05
            reasons.append("same setting")
        else:
            score -= 0.2
            reasons.append("erg vs on-water differs")

    p_dur, a_dur = planned.get("duration_min"), activity.get("duration_min")
    if p_dur and a_dur:
        ratio = a_dur / p_dur
        if 0.75 <= ratio <= 1.33:
            score += 0.25
            reasons.append("similar duration")
        elif 0.5 <= ratio <= 2.0:
            score += 0.1
            reasons.append("duration within 2x")
        else:
            score -= 0.1
    p_dist, a_dist = planned.get("distance_m"), activity.get("distance_m")
    if p_dist and a_dist and 0.8 <= a_dist / p_dist <= 1.25:
        score += 0.1
        reasons.append("similar distance")
    score = round(min(score, 1.0), 3)
    if score < MATCH_THRESHOLD:
        return None
    return {"score": score, "reasons": reasons}


def suggest_matches(planned_rows: list[dict], activities: list[dict], declined: set[tuple[int, int]] | None = None) -> list[dict]:
    """One-to-one greedy assignment by descending score, so an AM/PM double yields one
    workout per slot and a workout is never offered for two sessions. `planned_rows` must be
    the *unlinked* planned sessions; `activities` the not-yet-linked completed ones.
    `declined` is a set of (planned_id, canonical_id) the athlete already said "not this one" to."""
    declined = declined or set()
    pairs = []
    for p in planned_rows:
        for a in activities:
            if (p["id"], a["id"]) in declined:
                continue
            m = match_score(p, a)
            if m is not None:
                pairs.append((m["score"], -abs((a["local_date"] - p["date"]).days), p["id"], a["id"], m))
    pairs.sort(key=lambda t: (t[0], t[1], -t[2], -t[3]), reverse=True)
    used_p: set[int] = set()
    used_a: set[int] = set()
    out = []
    for score, _, pid, aid, m in pairs:
        if pid in used_p or aid in used_a:
            continue
        used_p.add(pid)
        used_a.add(aid)
        out.append({"planned_id": pid, "canonical_id": aid, **m})
    return out


# --- Planned totals -------------------------------------------------------------------------


def planned_minutes(row: dict) -> float:
    if row["session_type"] == "rest":
        return 0.0
    if row.get("duration_min"):
        return float(row["duration_min"])
    return structure_minutes(row.get("structure") or []) or 0.0


def planned_totals(rows: list[dict]) -> dict:
    """Sums over *planned* rows only (rest days contribute nothing; skipped rows are counted
    separately and left out of the minutes, so the totals describe what is still intended)."""
    minutes = 0.0
    distance = 0.0
    sessions = 0
    strength = 0
    skipped = 0
    zone_minutes = {z: 0.0 for z in ZONE_ORDER}
    for r in rows:
        if r["session_type"] == "rest":
            continue
        if r.get("status") == "skipped":
            skipped += 1
            continue
        sessions += 1
        if r["session_type"] == "strength":
            strength += 1
        mins = planned_minutes(r)
        minutes += mins
        distance += r.get("distance_m") or 0.0
        blocks = r.get("structure") or []
        assigned = 0.0
        for b in blocks:
            zone = b.get("zone") or r.get("target_zone")
            work = b.get("work_min")
            if zone in zone_minutes and work is not None:
                zone_minutes[zone] += b["reps"] * work
                assigned += b["reps"] * work
        if not blocks and r.get("target_zone") in zone_minutes:
            zone_minutes[r["target_zone"]] += mins
        elif blocks and assigned == 0 and r.get("target_zone") in zone_minutes:
            zone_minutes[r["target_zone"]] += mins
    return {
        "minutes": minutes,
        "distance_m": distance,
        "sessions": sessions,
        "strength_sessions": strength,
        "skipped_sessions": skipped,
        "zone_minutes": zone_minutes,
    }


def zone_pct(zone_minutes: dict[str, float]) -> dict[str, float]:
    total = sum(zone_minutes.values())
    if total <= 0:
        return {}
    return {z: round(zone_minutes.get(z, 0.0) / total * 100.0, 1) for z in ZONE_ORDER}


# --- Phases ---------------------------------------------------------------------------------


def phase_for_date(phases: list[dict], day: date) -> dict | None:
    for p in phases:
        if p["start_date"] <= day <= p["end_date"]:
            return p
    return None


def overlapping_phase(phases: list[dict], start: date, end: date, ignore_id: int | None = None) -> dict | None:
    for p in phases:
        if ignore_id is not None and p["id"] == ignore_id:
            continue
        if start <= p["end_date"] and p["start_date"] <= end:
            return p
    return None


def validate_phase_fields(fields: dict) -> None:
    if "kind" in fields and fields["kind"] not in PHASE_KINDS:
        raise ValueError(f"kind must be one of {list(PHASE_KINDS)}")
    start, end = fields.get("start_date"), fields.get("end_date")
    if start is not None and end is not None and end < start:
        raise ValueError("end_date can't be before start_date")
    for key in ("target_minutes_per_week", "target_sessions_per_week", "target_strength_sessions_per_week"):
        v = fields.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
            raise ValueError(f"{key} must be a non-negative number")
    zp = fields.get("target_zone_pct")
    if zp is not None:
        if not isinstance(zp, dict):
            raise ValueError("target_zone_pct must be an object like {\"UT2\": {\"min\": 70}}")
        for zone, bounds in zp.items():
            if zone not in ZONE_ORDER or not isinstance(bounds, dict) or not set(bounds) <= {"min", "max"}:
                raise ValueError("target_zone_pct entries must be a zone mapped to {min?, max?} percentages")
            for v in bounds.values():
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100:
                    raise ValueError("target_zone_pct bounds must be between 0 and 100")


def compare_week_to_targets(planned: dict, completed: dict, targets: dict, completed_zone_pct: dict[str, float]) -> list[dict]:
    """Rows of `{metric, target, planned, completed}` plus, for zones, whether the completed
    split sits inside a phase's stated bounds. Descriptive only: no row carries a verdict
    colour or a 'behind' flag — it is up to the UI to show numbers side by side."""
    rows = [
        {"metric": "minutes", "target": targets.get("minutes"), "planned": planned["minutes"], "completed": completed.get("minutes", 0.0)},
        {"metric": "sessions", "target": targets.get("sessions"), "planned": planned["sessions"], "completed": completed.get("sessions", 0)},
        {
            "metric": "strength_sessions",
            "target": targets.get("strength_sessions"),
            "planned": planned["strength_sessions"],
            "completed": completed.get("strength_sessions", 0),
        },
    ]
    zone_rows = []
    for zone, bounds in (targets.get("zone_pct") or {}).items():
        actual = completed_zone_pct.get(zone)
        within = None
        if actual is not None:
            within = (bounds.get("min") is None or actual >= bounds["min"]) and (bounds.get("max") is None or actual <= bounds["max"])
        zone_rows.append({"zone": zone, "min": bounds.get("min"), "max": bounds.get("max"), "completed_pct": actual, "within": within})
    return rows + [{"metric": "zone_pct", "zones": zone_rows}] if zone_rows else rows


# --- Review flags ---------------------------------------------------------------------------

# A flag needs both a relative and an absolute change: +30% of a 40-minute week is not news.
MIN_ABSOLUTE_CHANGE_MIN = 60.0


def workload_change_flags(weeks: list[dict], threshold_pct: float, confidence: str = "medium") -> list[dict]:
    """`weeks` is chronological `{week_start, planned_minutes, completed_baseline_minutes,
    phase_kind, phase_approved}`. A week is flagged when its planned minutes are more than
    `threshold_pct` above the previous planned week, or above the trailing completed average
    (`completed_baseline_minutes`, the athlete's actual recent load) — whichever reference is
    larger, since a plan that is modest against last week's plan but a leap from what was
    actually trained is exactly the case worth a second look. Drops are flagged only outside
    a recovery/taper-style phase. Flags ask for review; wording defers to a coach on an
    approved phase and never suggests editing the plan."""
    flags: list[dict] = []
    for i, w in enumerate(weeks):
        planned = w["planned_minutes"]
        if planned <= 0:
            continue
        refs: list[tuple[str, float]] = []
        if i > 0 and weeks[i - 1]["planned_minutes"] > 0:
            refs.append(("previous planned week", weeks[i - 1]["planned_minutes"]))
        base = w.get("completed_baseline_minutes")
        if base:
            refs.append(("recent completed average", base))
        if not refs:
            continue
        ref_name, ref = max(refs, key=lambda r: r[1])
        change = planned - ref
        pct = change / ref * 100.0
        approved = bool(w.get("phase_approved"))
        quiet_phase = w.get("phase_kind") in ("recovery", "pre_competition", "competition")
        if change >= MIN_ABSOLUTE_CHANGE_MIN and pct > threshold_pct:
            kind = "increase"
            core = f"The planned week of {w['week_start'].isoformat()} is {planned:.0f} min, about {pct:.0f}% above the {ref_name} ({ref:.0f} min)."
        elif -change >= MIN_ABSOLUTE_CHANGE_MIN and -pct > threshold_pct and not quiet_phase:
            kind = "drop"
            core = f"The planned week of {w['week_start'].isoformat()} is {planned:.0f} min, about {-pct:.0f}% below the {ref_name} ({ref:.0f} min)."
        else:
            continue
        if approved:
            tail = " It sits in a coach-approved phase, so this is worth confirming with your coach — nothing has been changed."
            body = core + tail
        else:
            tail = " Worth a look before you commit to it — nothing has been changed, and only you (or your coach) can decide."
            body = _apply_hedge(confidence, core + tail)
        flags.append(
            {
                "week_start": w["week_start"],
                "kind": kind,
                "planned_minutes": planned,
                "reference_minutes": ref,
                "reference": ref_name,
                "pct_change": round(pct, 1),
                "phase_approved": approved,
                "message": body,
            }
        )
    return flags
