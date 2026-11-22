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
        assert sorted(s.split()[5] for s in stmts) == ["display_name", "expires_at", "role", "scope", "template_id"]
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


# --- Session 32: an existing Pi file upgraded in place ------------------------------------------------------------------------


def test_an_existing_pi_database_gains_the_session_32_columns_indexes_and_stamps(monkeypatch):
    """Start from a file as it was before session 32 (no zone columns, no new indexes, no zone table), with history in it; run the
    real startup migration; then the one-time backfill and a full recompute must work on it."""
    from datetime import datetime, timezone

    from catch.core import localtime
    from catch.core.models import CanonicalActivity, DailyScore, DailyWellness, UserProfile
    from catch.sync import scoring
    from catch.sync.matching import run_matching

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with eng.begin() as conn:
        for name, _table, _cols in db_module._SESSION32_INDEXES:
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {name}")
        conn.exec_driver_sql("DROP TABLE user_zone_periods")
        for table in ("activities", "canonical_activities", "food_logs", "body_comp"):
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS ix_{table}_owner_local_date")
            conn.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN local_tz")
            conn.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN local_date")
        for col in ("timezone", "follow_device_zone", "onboarding_state", "onboarding_step", "onboarding_json", "onboarding_completed_at"):
            conn.exec_driver_sql(f"ALTER TABLE user_profiles DROP COLUMN {col}")
        conn.exec_driver_sql("INSERT INTO user_profiles (id, display_name, created_at) VALUES ('owner', 'You', '2026-01-01 00:00:00')")
        conn.exec_driver_sql(
            "INSERT INTO activities (owner_id, source, external_id, type, start, duration, avg_hr, updated_at) "
            "VALUES ('owner', 'concept2', 'old1', 'rower', '2026-03-04 04:30:00.000000', 1800, 150, '2026-03-04 05:00:00.000000')"
        )
        conn.exec_driver_sql("INSERT INTO daily_wellness (owner_id, date, source, resting_hr, updated_at) VALUES ('owner', '2026-03-03', 'garmin', 50, '2026-03-03 08:00:00')")
    monkeypatch.setattr(db_module, "engine", eng)
    monkeypatch.setattr(localtime, "host_zone_name", lambda: "America/New_York")  # the Pi's own zone

    db_module._migrate_columns()
    db_module._migrate_columns()  # idempotent

    with eng.connect() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(activities)")}
        assert {"local_date", "local_tz"} <= cols
        idx = {r[1] for r in conn.exec_driver_sql("SELECT type, name FROM sqlite_master WHERE type = 'index'")}
        assert {name for name, _t, _c in db_module._SESSION32_INDEXES} <= idx
    SQLModel.metadata.create_all(eng)  # init_db's create_all adds the new table to an old file

    with Session(eng) as session:
        assert session.get(UserProfile, "owner").onboarding_state is None  # the Pi never auto-shows setup anyway
        run_matching(session)
        session.info["catch_no_stamp"] = True  # what old rows look like: run_matching created the canonical unstamped
        c = session.exec(select(CanonicalActivity)).one()
        c.local_date = None
        session.add(c)
        session.commit()
        del session.info["catch_no_stamp"]
        assert localtime.ensure_backfilled(session) is True
        a = session.exec(select(Activity)).one()
        # 23:30 on 3 March on the Pi's New York clock, exactly the day the old host-zone code gave it.
        assert a.local_date.isoformat() == "2026-03-03" and a.local_tz == "America/New_York"
        assert scoring.recompute_scores(session, full=True) > 0
        row = session.get(DailyScore, ("owner", DailyWellness.__table__.c.date.type.python_type.fromisoformat("2026-03-03")))
        assert json.loads(row.strain_json)["model"] == scoring.SCORING_MODEL
        assert datetime(2026, 3, 4, 4, 30, tzinfo=timezone.utc) == a.start


# --- Session 33: merge_mode, merge_log.snapshot_json, pieces.modality on an existing Pi file ------------------------------------


def test_an_existing_pi_database_gains_the_session_33_columns_and_old_pieces_read_as_rowing(monkeypatch):
    from catch.core.models import CanonicalActivity, Piece
    from catch.sync import scoring
    from catch.sync.canonical import resolve_all_canonicals

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE canonical_activities DROP COLUMN merge_mode")
        conn.exec_driver_sql("ALTER TABLE merge_log DROP COLUMN snapshot_json")
        conn.exec_driver_sql("ALTER TABLE pieces DROP COLUMN modality")
        conn.exec_driver_sql(
            "INSERT INTO canonical_activities (owner_id, id, sport_family, start, duration, zones_json, created_at, updated_at) "
            "VALUES ('owner', 1, 'rowing', '2026-03-04 07:00:00.000000', 1800, '{\"hr\": {\"UT2\": 1800}, \"power\": null}', '2026-03-04 08:00:00', '2026-03-04 08:00:00')"
        )
        conn.exec_driver_sql(
            "INSERT INTO pieces (owner_id, id, canonical_id, piece_type, distance_m, duration_s, splits_json, source, has_intervals, created_at, updated_at) "
            "VALUES ('owner', 1, 1, '2000m', 2000, 400, '[]', 'manual', 0, '2026-03-04 08:00:00', '2026-03-04 08:00:00')"
        )
    monkeypatch.setattr(db_module, "engine", eng)

    db_module._migrate_columns()
    db_module._migrate_columns()  # idempotent

    with Session(eng) as session:
        piece = session.exec(select(Piece)).one()
        assert piece.modality == "rowing_erg"  # every piece before session 33 was a rowing erg piece
        canonical = session.exec(select(CanonicalActivity)).one()
        assert canonical.merge_mode is None  # ordinary duplicate semantics
        # Zones cached before HRR carry no basis: maintenance sees that and re-resolves once.
        assert scoring.zones_model_is_current(session) is False
        resolve_all_canonicals(session)
