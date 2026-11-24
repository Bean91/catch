"""Session 36 follow-up: the per-recording stroke summary cache (rules in catch/analytics/stroke_summary.py).

`activities.stroke_summary_json` holds one Concept2 rowing recording's split-by-rate bands and best-power curve. It is filled when
strokes are stored (`store_for`, called by `upsert.upsert_strokes`) and, for recordings synced before it existed, the first time a
reader asks (`summaries_for`). `upsert_strokes` is the only writer of strokes, and it replaces the summary in the same commit, so a
stored summary is current unless its algorithm version is older. The write is a plain UPDATE of that one column: it changes no
score input, so it marks no day for a recompute."""

from __future__ import annotations

import json
from typing import Iterable

from sqlalchemy import update
from sqlmodel import Session, select

from catch.analytics import stroke_summary as ss
from catch.core.models import Activity, Stroke

_FILL_CHUNK = 25
_STROKE_COLUMNS = (Stroke.activity_id, Stroke.interval_index, Stroke.t, Stroke.pace_500m, Stroke.watts, Stroke.stroke_rate)


def _as_dicts(rows: Iterable[tuple]) -> list[dict]:
    return [{"interval_index": r[1], "t": r[2], "pace_500m": r[3], "watts": r[4], "stroke_rate": r[5]} for r in rows]


def _write(session: Session, activity_id: int, summary: dict | None) -> None:
    session.exec(
        update(Activity).where(Activity.id == activity_id).values(stroke_summary_json=json.dumps(summary) if summary else None)
    )


def store_for(session: Session, activity_id: int, strokes: list[dict]) -> dict:
    """Summarise strokes that were just stored for this recording (no re-read). The caller commits."""
    summary = ss.summarize(strokes, watts_derived=True)
    _write(session, activity_id, summary)
    return summary


def _current(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if data.get("v") == ss.SUMMARY_VERSION else None


def summaries_for(session: Session, activity_ids: list[int]) -> dict[int, dict]:
    """`{activity_id: summary}` for these recordings, building and storing any that is missing or from an older version. Strokes
    are read a few recordings at a time, only the columns the summary needs."""
    out: dict[int, dict] = {}
    stale: list[int] = []
    for i in range(0, len(activity_ids), 500):
        chunk = activity_ids[i : i + 500]
        for aid, raw in session.exec(select(Activity.id, Activity.stroke_summary_json).where(Activity.id.in_(chunk))).all():
            current = _current(raw)
            if current is None:
                stale.append(aid)
            else:
                out[aid] = current
    for i in range(0, len(stale), _FILL_CHUNK):
        chunk = stale[i : i + _FILL_CHUNK]
        rows = session.exec(select(*_STROKE_COLUMNS).where(Stroke.activity_id.in_(chunk)).order_by(Stroke.activity_id, Stroke.seq)).all()
        by_act: dict[int, list[tuple]] = {aid: [] for aid in chunk}
        for r in rows:
            by_act[r[0]].append(r)
        for aid, strokes in by_act.items():
            summary = ss.summarize(_as_dicts(strokes), watts_derived=True)
            _write(session, aid, summary)
            out[aid] = summary
        session.commit()
    return out


BACKFILL_BATCH = 300


def backfill(session: Session, limit: int = BACKFILL_BATCH) -> int:
    """Build up to `limit` missing or outdated summaries (recordings synced before the cache, or after a version change). Called by
    `scheduler.run_maintenance`, so a reader rarely pays the cold cost; what's left is picked up on the next run or the first read."""
    current = f'{{"v": {ss.SUMMARY_VERSION},%'
    ids = session.exec(
        select(Activity.id).where(
            Activity.source == "concept2",
            (Activity.stroke_summary_json.is_(None)) | (~Activity.stroke_summary_json.like(current)),
        ).order_by(Activity.start.desc()).limit(limit)
    ).all()
    if ids:
        summaries_for(session, list(ids))
    return len(ids)
