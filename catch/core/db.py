from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from catch.core.config import settings

Path(settings.db_file).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{settings.db_file}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


# create_all() only creates missing tables, not missing columns on existing ones — session 1
# already shipped a live `activities`/`strokes` table, so new nullable columns added since
# need an explicit ALTER TABLE or they silently never appear on that file.
_NEW_COLUMNS = {
    "activities": {
        "workout_type": "TEXT",
        "drag_factor": "INTEGER",
        "stroke_rate": "REAL",
        "intervals_json": "TEXT",
        "linked_activity_id": "INTEGER",
        # Session 8/12 (see PLAN.md): the cross-source matching engine.
        "avg_cadence": "REAL",
        "sport_family": "TEXT",
        "origin": "TEXT",
        "canonical_id": "INTEGER",
        "hr_source_type": "TEXT",
        "laps_json": "TEXT",
        "title_hint": "TEXT",
    },
    "strokes": {
        "seq": "INTEGER NOT NULL DEFAULT 0",
        "interval_index": "INTEGER",
    },
    "daily_scores": {
        "rowing_load_json": "TEXT",
    },
}


def _migrate_columns() -> None:
    with engine.connect() as conn:
        for table, columns in _NEW_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, decl in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_strokes_activity_id ON strokes(activity_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_activities_canonical_id ON activities(canonical_id)")
        conn.commit()


def _migrate_linked_activities_to_canonical() -> None:
    """One-time, idempotent: give every pre-session-12 `Activity` a `canonical_id` (a 1:1
    canonical for a standalone activity, a shared one for an existing Garmin<->Concept2
    `linked_activity_id` pair), then run the matching engine's own backfill so same-source
    duplicates (e.g. a Peloton-pushed Garmin ride vs. the watch's own) and anything the old
    linker never covered get matched too. Safe to call on every startup — every step below
    is a no-op once canonical_id is populated."""
    from sqlmodel import Session, select

    from catch.analytics.matching import sport_family as _sport_family
    from catch.core.models import Activity, CanonicalActivity

    with Session(engine) as session:
        rows = session.exec(select(Activity).where(Activity.canonical_id.is_(None))).all()
        if not rows:
            return
        by_id = {a.id: a for a in rows}
        seen: set[int] = set()
        for row in rows:
            if row.id in seen:
                continue
            group = [row]
            seen.add(row.id)
            partner_id = row.linked_activity_id
            if partner_id in by_id and partner_id not in seen:
                group.append(by_id[partner_id])
                seen.add(partner_id)
            canonical = CanonicalActivity(sport_family=_sport_family(row.source, row.type))
            session.add(canonical)
            session.flush()
            for member in group:
                member.canonical_id = canonical.id
                session.add(member)
        session.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_columns()
    _migrate_linked_activities_to_canonical()


@contextmanager
def get_session():
    with Session(engine) as session:
        yield session
