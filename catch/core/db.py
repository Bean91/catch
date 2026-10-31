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
    },
    "strokes": {
        "seq": "INTEGER NOT NULL DEFAULT 0",
        "interval_index": "INTEGER",
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
        conn.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_columns()


@contextmanager
def get_session():
    with Session(engine) as session:
        yield session
