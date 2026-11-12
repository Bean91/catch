from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from catch.core import db as db_module
from catch.core.models import Activity


def test_migrate_garmin_activity_fields_backfills_from_raw_json(monkeypatch):
    """Session 13 (see PLAN.md Part A): pre-session-13 Garmin rows have `steps`/`bmr_kcal`
    unset but a stored `raw_json` from the original sync — the migration should recover both
    without any network call, and leave a row with neither field in its raw_json untouched."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(db_module, "engine", eng)

    with Session(eng) as session:
        session.add(
            Activity(
                source="garmin",
                external_id="a1",
                raw_json=json.dumps({"steps": 4200, "bmrCalories": 95.0, "calories": 410.0}),
            )
        )
        session.add(
            Activity(
                source="garmin",
                external_id="a2",
                raw_json=json.dumps({"calories": 200.0}),  # no steps/bmrCalories at all
            )
        )
        session.add(Activity(source="concept2", external_id="c1", raw_json=json.dumps({"steps": 999})))
        session.commit()

    db_module._migrate_garmin_activity_fields()

    with Session(eng) as session:
        a1 = session.exec(select(Activity).where(Activity.external_id == "a1")).one()
        a2 = session.exec(select(Activity).where(Activity.external_id == "a2")).one()
        c1 = session.exec(select(Activity).where(Activity.external_id == "c1")).one()
        assert a1.steps == 4200
        assert a1.bmr_kcal == 95.0
        assert a2.steps is None
        assert a2.bmr_kcal is None
        # Non-Garmin rows are never touched, even if their raw_json happens to have a "steps".
        assert c1.steps is None

    # Idempotent: a second run is a no-op (nothing left with both fields unset after the
    # real backfill found something — a2 stays unset forever since its raw_json has neither,
    # but that's indistinguishable from "already migrated," which is fine, not a bug).
    db_module._migrate_garmin_activity_fields()


# --- Session 22: workout library, technique notes, feedback ------------------------------------------


NEW_TABLES = ("workout_templates", "technique_notes", "coach_feedback", "coach_feedback_revisions")


def test_new_tables_are_created_by_create_all_and_a_second_run_is_a_noop(engine):
    from sqlalchemy import inspect

    assert set(NEW_TABLES) <= set(inspect(engine).get_table_names())
    SQLModel.metadata.create_all(engine)  # idempotent
    assert set(NEW_TABLES) <= set(inspect(engine).get_table_names())


def test_old_shape_api_tokens_and_planned_workouts_gain_the_new_columns_idempotently(sqlite_engine):
    from sqlalchemy import inspect
    from sqlalchemy.dialects import postgresql

    from catch.core import db as db_module

    with sqlite_engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE api_tokens")
        conn.exec_driver_sql("CREATE TABLE api_tokens (id INTEGER PRIMARY KEY, name TEXT, token_hash TEXT, created_at TEXT, last_used_at TEXT)")
        conn.exec_driver_sql("INSERT INTO api_tokens (name, token_hash) VALUES ('legacy', 'h')")
        conn.exec_driver_sql("DROP TABLE planned_workouts")
        conn.exec_driver_sql("CREATE TABLE planned_workouts (id INTEGER PRIMARY KEY, owner_id TEXT, date DATE, session_type TEXT, title TEXT)")
        stmts = db_module._add_column_statements(inspect(conn), {t: db_module._NEW_COLUMNS[t] for t in ("api_tokens", "planned_workouts")})
        assert sorted(s.split()[5] for s in stmts) == ["display_name", "role", "template_id"]
        for s in stmts:
            conn.exec_driver_sql(s)
            str(text(s).compile(dialect=postgresql.dialect()))
        assert db_module._add_column_statements(inspect(conn), {t: db_module._NEW_COLUMNS[t] for t in ("api_tokens", "planned_workouts")}) == []
        row = conn.exec_driver_sql("SELECT name, role, display_name FROM api_tokens").one()
    assert tuple(row) == ("legacy", None, None)  # a pre-existing token has no role -> the athlete


def test_new_columns_use_portable_ddl_types():
    from catch.core.db import _NEW_COLUMNS

    for table in ("api_tokens", "planned_workouts"):
        for decl in _NEW_COLUMNS[table].values():
            assert decl in ("TEXT", "INTEGER", "REAL") and "DEFAULT" not in decl


def test_new_tables_compile_for_postgresql():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    from catch.core.models import CoachFeedback, CoachFeedbackRevision, TechniqueNote, WorkoutTemplate

    for model in (WorkoutTemplate, TechniqueNote, CoachFeedback, CoachFeedbackRevision):
        table = model.__table__
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in ddl
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "uq_workout_templates_external_id" in str(CreateTable(WorkoutTemplate.__table__).compile(dialect=postgresql.dialect()))


def test_new_modules_use_no_sqlite_only_sql():
    import pathlib
    import re

    import catch

    root = pathlib.Path(catch.__file__).resolve().parent
    banned = (r"strftime", r"julianday", r"PRAGMA", r"INSERT OR", r"json_extract", r"\browid\b", r"\btext\(", r"exec_driver_sql", r"\bGLOB\b", r"\bLIKE\b", r"ilike")
    for rel in (
        "core/principal.py", "analytics/workout_library.py", "sync/workout_library.py", "sync/coaching_notes.py",
        "coach/library_tools.py", "api/routes_library.py", "api/routes_coaching.py",
    ):
        body = (root / rel).read_text()
        for token in banned:
            assert not re.search(token, body), f"{rel} contains {token}"


def test_seeding_examples_through_init_helpers_is_idempotent(engine, monkeypatch):
    from sqlmodel import Session

    from catch.core import db as db_module
    from catch.core.models import WorkoutTemplate

    monkeypatch.setattr(db_module, "engine", engine)
    db_module._seed_workout_examples()
    db_module._seed_workout_examples()
    with Session(engine) as s:
        rows = s.exec(select(WorkoutTemplate)).all()
    assert len(rows) >= 6 and all(r.is_example and r.external_id for r in rows) and len({r.external_id for r in rows}) == len(rows)
