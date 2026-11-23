"""Session 36: per-category exports (CSV for spreadsheets, JSON for structured records), beside the whole-account export in
catch/sync/privacy.py.

  * Only the signed-in owner's rows (tenant hooks), and only whitelisted columns — no credentials, tokens, sealed values or
    another person's ids ever reach a file.
  * Column names carry their unit (`duration_s`, `distance_m`, `avg_power_w`); an instant is `…_utc` (ISO 8601, UTC) and sits beside
    the athlete's own `local_date` and the `local_tz` it was recorded in, so nothing depends on where the file is opened.
  * Derived figures say so in their column name (`avg_split_s_per_500m_derived`) or a `…_basis` column.
  * Rows are built in one pass with the owner set, then written out: the request context is never held across a `yield`.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterator

from sqlmodel import Session, select

from catch.core import localtime, tenant
from catch.core.models import Activity, CanonicalActivity, DailyScore, DailyWellness, Goal, Note, Piece, PieceInterval, TechniqueNote

CATEGORIES = ("activities", "pieces", "intervals", "daily_metrics", "records", "goals", "notes")


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def _ov(c: CanonicalActivity) -> dict:
    return json.loads(c.overrides_json) if c.overrides_json else {}


def _activities(session: Session) -> list[dict]:
    rows = session.exec(select(CanonicalActivity).where(CanonicalActivity.start.is_not(None)).order_by(CanonicalActivity.start)).all()
    members: dict[int, list[str]] = {}
    for cid, src in session.exec(select(Activity.canonical_id, Activity.source)).all():
        if cid is not None:
            members.setdefault(cid, []).append(src)
    out = []
    for c in rows:
        ov = _ov(c)
        split = (c.duration / c.distance * 500.0) if c.sport_family == "rowing" and c.duration and c.distance else None
        out.append({
            "workout_id": c.id, "start_utc": c.start, "local_date": localtime.day_of(session, c), "local_tz": c.local_tz,
            "title": ov.get("title") or c.title, "sport_family": c.sport_family, "category": c.category,
            "duration_s": c.duration, "distance_m": c.distance, "avg_split_s_per_500m_derived": split,
            "avg_hr_bpm": c.avg_hr, "max_hr_bpm": c.max_hr, "avg_power_w": c.avg_power, "avg_rate_per_min": c.avg_cadence,
            "calories_kcal": c.calories, "session_label": c.session_label, "rpe_0_10": ov.get("rpe"),
            "tags": ";".join(ov.get("tags") or []), "notes": ov.get("notes"), "conditions": ov.get("conditions"), "equipment": ov.get("equipment"),
            "excluded_from_totals": bool(ov.get("exclude_from_totals")), "sources": ";".join(sorted(set(members.get(c.id, [])))),
        })
    return out


def _pieces(session: Session) -> list[dict]:
    canon = {c.id: c for c in session.exec(select(CanonicalActivity)).all()}
    out = []
    for p in session.exec(select(Piece).order_by(Piece.id)).all():
        c = canon.get(p.canonical_id)
        split_m = 1000.0 if p.modality == "bike" else 500.0
        out.append({
            "piece_id": p.id, "workout_id": p.canonical_id, "local_date": localtime.day_of(session, c) if c is not None and c.start else None,
            "piece_type": p.piece_type, "modality": p.modality, "distance_m": p.distance_m, "duration_s": p.duration_s,
            "split_unit_m": split_m, "avg_split_s_derived": (p.duration_s / p.distance_m * split_m) if p.duration_s and p.distance_m else None,
            "avg_power_w": p.avg_watts, "avg_power_basis": ("derived_from_pace" if p.modality == "rowing_erg" else "as_recorded") if p.avg_watts is not None else None,
            "has_intervals": bool(p.has_intervals), "source": p.source, "notes": p.notes,
        })
    return out


def _intervals(session: Session) -> list[dict]:
    pieces = {p.id: p for p in session.exec(select(Piece)).all()}
    out = []
    for r in session.exec(select(PieceInterval).order_by(PieceInterval.piece_id, PieceInterval.position)).all():
        p = pieces.get(r.piece_id)
        out.append({
            "piece_id": r.piece_id, "workout_id": p.canonical_id if p else None, "position": r.position + 1, "target_type": r.target_type,
            "work_distance_m": r.work_distance_m, "work_duration_s": r.work_duration_s, "rest_after_s": r.rest_duration_s,
            "avg_split_s": r.avg_split_s, "avg_power_w": r.avg_watts, "avg_rate_per_min": r.avg_rate, "avg_hr_bpm": r.avg_hr, "max_hr_bpm": r.max_hr,
            "source": r.source, "notes": r.notes,
        })
    return out


def _daily(session: Session) -> list[dict]:
    wellness = {w.date: w for w in session.exec(select(DailyWellness)).all()}
    scores = {s.date: s for s in session.exec(select(DailyScore)).all()}
    out = []
    for d in sorted(set(wellness) | set(scores)):
        w, s = wellness.get(d), scores.get(d)
        rec = json.loads(s.recovery_json) if s is not None and s.recovery_json else {}
        strain = json.loads(s.strain_json) if s is not None and s.strain_json else {}
        load = json.loads(s.load_json) if s is not None and s.load_json else {}
        lc = (load.get("components") or [{}])[0] if load.get("components") else {}
        out.append({
            "local_date": d, "recovery_score_0_100": rec.get("value"), "recovery_band": rec.get("band"),
            "strain_0_21": strain.get("value"), "day_load_trimp": strain.get("load"),
            "acute_load_7d": lc.get("acute_7d"), "chronic_load_42d": lc.get("chronic_42d"), "acute_chronic_ratio": load.get("value"),
            "hrv_rmssd_ms": w.hrv_rmssd if w else None, "resting_hr_bpm": w.resting_hr if w else None, "sleep_s": w.sleep_seconds if w else None,
        })
    return out


def _records(session: Session) -> list[dict]:
    from catch.sync.records import records

    out = []
    for modality in ("rowing_erg", "bike"):
        r = records(session, modality)
        for group in ("distance", "duration", "power"):
            for row in r[group]:
                for i, e in enumerate(row["history"]):
                    out.append({
                        "modality": modality, "record": row["key"], "is_current_best": i == len(row["history"]) - 1,
                        "local_date": e["date"], "distance_m": e["distance_m"], "duration_s": e["duration_s"],
                        "avg_split_s_derived": e["pace_s"], "split_unit_m": e["split_m"], "avg_power_w": e["avg_watts"], "avg_power_basis": e["watts_basis"],
                        "kind": e["label"], "concept2_verified": e["verified"], "workout_id": e["canonical_id"], "piece_id": e["piece_id"],
                    })
    return out


def _goals(session: Session) -> list[dict]:
    from catch.sync.goals import goal_dict

    today = localtime.today(session)
    out = []
    for g in session.exec(select(Goal).order_by(Goal.id)).all():
        d = goal_dict(session, g, today)
        p = d["progress"]
        out.append({
            "goal_id": g.id, "text": g.text, "kind": d["kind"], "sport": g.sport, "target_value": g.target_value, "unit": g.unit,
            "start_date": g.start_date, "end_date": g.end_date or g.target_date, "status": g.status, "completed_utc": g.completed_at,
            "progress_current": p.get("current"), "progress_pct": p.get("pct"), "state": p.get("state"),
        })
    return out


def _notes(session: Session) -> list[dict]:
    out = []
    for n in session.exec(select(Note).order_by(Note.date)).all():
        out.append({"kind": "day_note", "local_date": n.date, "workout_id": None, "piece_id": None, "text": n.text, "rpe_0_10": n.rpe, "category": None, "visibility": "private"})
    for c in session.exec(select(CanonicalActivity).where(CanonicalActivity.overrides_json.is_not(None))).all():
        ov = _ov(c)
        for key in ("notes", "conditions", "equipment"):
            if ov.get(key):
                out.append({"kind": f"workout_{key}", "local_date": localtime.day_of(session, c) if c.start else None, "workout_id": c.id, "piece_id": None,
                            "text": ov[key], "rpe_0_10": ov.get("rpe") if key == "notes" else None, "category": None, "visibility": "private"})
    for p in session.exec(select(Piece).where(Piece.notes.is_not(None))).all():
        if p.notes:
            out.append({"kind": "piece_note", "local_date": None, "workout_id": p.canonical_id, "piece_id": p.id, "text": p.notes, "rpe_0_10": None, "category": None, "visibility": "private"})
    for t in session.exec(select(TechniqueNote)).all():
        out.append({"kind": "technique_note", "local_date": t.note_date, "workout_id": t.canonical_id, "piece_id": t.piece_id, "text": t.text,
                    "rpe_0_10": None, "category": t.category, "visibility": t.visibility})
    return out


_BUILDERS: dict[str, Callable[[Session], list[dict]]] = {
    "activities": _activities, "pieces": _pieces, "intervals": _intervals, "daily_metrics": _daily,
    "records": _records, "goals": _goals, "notes": _notes,
}


def build(session: Session, owner_id: str, category: str) -> list[dict]:
    if category not in _BUILDERS:
        raise KeyError(category)
    with tenant.use_owner(owner_id):
        rows = _BUILDERS[category](session)
    return [{k: _iso(v) for k, v in r.items()} for r in rows]


def iter_csv(rows: list[dict]) -> Iterator[bytes]:
    if not rows:
        yield b""
        return
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
    writer.writeheader()
    for i, r in enumerate(rows, start=1):
        writer.writerow(r)
        if i % 500 == 0:
            yield buf.getvalue().encode()
            buf.seek(0)
            buf.truncate(0)
    yield buf.getvalue().encode()


def as_json(category: str, rows: list[dict]) -> bytes:
    return json.dumps({
        "category": category, "generated_utc": datetime.now(timezone.utc).isoformat(), "rows": rows,
        "note": "Units are in the column names; *_utc instants are UTC; local_date is your own calendar day.",
    }, default=str).encode()
