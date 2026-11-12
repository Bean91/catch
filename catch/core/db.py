from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event, inspect
from sqlmodel import Session, SQLModel, create_engine

from catch.core import tenant
from catch.core.config import settings


def _build_engine():
    if settings.is_public:
        # Public deployment: Supabase Postgres through the pooler. Imported lazily — the Pi never
        # installs psycopg (it has no 32-bit ARM wheel) and never reaches this branch.
        from catch.core.db_pg import build_pg_engine

        return build_pg_engine(settings.database_url, pool_mode=settings.db_pool_mode, pool_size=settings.db_pool_size)
    Path(settings.db_file).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{settings.db_file}", connect_args={"check_same_thread": False})


engine = _build_engine()

if engine.dialect.name == "sqlite":

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
        # Session 13 (see PLAN.md Part A).
        "steps": "INTEGER",
        "bmr_kcal": "REAL",
    },
    "strokes": {
        "seq": "INTEGER NOT NULL DEFAULT 0",
        "interval_index": "INTEGER",
    },
    "daily_scores": {
        "rowing_load_json": "TEXT",
        # Session 15 (see PLAN.md Part B) — illness early-warning output, rewritten on every
        # recompute like every other *_json column here (user-owned state lives in the
        # separate illness_acks table instead, which recompute never overwrites).
        "illness_json": "TEXT",
    },
    "canonical_activities": {
        # Session 12 (see PLAN.md): erg/on_water split, persisted so GET /api/activities'
        # category filter can run entirely in SQL — see the field's docstring in models.py.
        "category": "TEXT",
        # Session 14 (see PLAN.md Part C).
        "muscular_load_au": "REAL",
        "muscular_by_muscle_json": "TEXT",
        # Session 17 (see PLAN.md Part D.4) — see the field's docstring in models.py.
        "absorbed_into_piece_id": "INTEGER",
    },
    "pieces": {
        # Session 19 (see PLAN.md): see the field's docstring in models.py.
        "has_intervals": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "daily_wellness": {
        # Session 13 (see PLAN.md Part A).
        "steps": "INTEGER",
        "active_kcal": "INTEGER",
        "total_kcal": "INTEGER",
        "bmr_kcal": "INTEGER",
        "moderate_intensity_minutes": "INTEGER",
        "vigorous_intensity_minutes": "INTEGER",
        "floors_climbed": "INTEGER",
        "floors_descended": "INTEGER",
        # Session 15 (see PLAN.md Part B).
        "sleep_respiration_avg": "REAL",
        # Session 16 (see PLAN.md Part A) — see DailyWellness.wake_time_minutes's docstring.
        "wake_time_minutes": "INTEGER",
        # Session 23 (see PLAN.md) — see DailyWellness.skin_temp_c / field_sources_json.
        "skin_temp_c": "REAL",
        "field_sources_json": "TEXT",
    },
    "coach_settings": {
        # Session 23 (see PLAN.md): per-owner lookup, a per-provider model map, a token ceiling.
        "owner_id": "TEXT NOT NULL DEFAULT 'owner'",
        "models_json": "TEXT NOT NULL DEFAULT '{}'",
        "daily_token_cap": "INTEGER",
    },
    "coach_conversations": {"owner_id": "TEXT NOT NULL DEFAULT 'owner'"},
    "ai_usage_events": {
        "owner_id": "TEXT NOT NULL DEFAULT 'owner'",
        "provider": "TEXT",
        "model": "TEXT",
    },
    "events": {
        # Session 15 (see PLAN.md Part C.3).
        "plan_json": "TEXT",
        # Session 21 (see PLAN.md): race-planning fields. Nullable only — no BOOLEAN DEFAULT.
        "location": "TEXT",
        "goals": "TEXT",
        "notes": "TEXT",
        "distance_m": "REAL",
        "owner_id": "TEXT",
    },
    "api_tokens": {
        # Session 22 (see PLAN.md): nullable only. NULL role = athlete.
        "role": "TEXT",
        "display_name": "TEXT",
    },
    "planned_workouts": {
        "template_id": "INTEGER",
    },
    "sync_state": {
        # Session 16 (see PLAN.md Part A/B) — see SyncState's docstring in models.py.
        "consecutive_failures": "INTEGER NOT NULL DEFAULT 0",
        "alert_sent_at": "TEXT",
    },
    "illness_acks": {
        # Session 16 (see PLAN.md Part A) — see IllnessAck's docstring in models.py.
        "notified_at": "TEXT",
    },
}


def _owner_columns() -> dict[str, dict[str, str]]:
    """Session 24: `owner_id` on every owned table of an already-existing SQLite file. Strict tables
    backfill to the install's single owner through the column default; shared reference tables
    (exercises, foods, workout_templates) stay NULL = global. The physical primary/unique keys of
    tables created before this session stay narrower than the models' (a rebuild of daily_wellness
    et al. buys nothing for a one-owner file) — harmless, and a fresh file gets the full keys."""
    from catch.core.tenant import OwnedOrShared, OwnedStrict

    out: dict[str, dict[str, str]] = {}
    for mapper in SQLModel._sa_registry.mappers:
        cls = mapper.class_
        if issubclass(cls, OwnedOrShared):
            out[cls.__tablename__] = {"owner_id": "TEXT"}
        elif issubclass(cls, OwnedStrict):
            out[cls.__tablename__] = {"owner_id": f"TEXT NOT NULL DEFAULT '{tenant.PERSONAL_OWNER}'"}
    return out


def _add_column_statements(inspector, new_columns: dict[str, dict[str, str]]) -> list[str]:
    """Dialect-neutral (SQLAlchemy `inspect`, not SQLite's PRAGMA) so the same list drives a
    PostgreSQL move; the DDL strings themselves are plain `ALTER TABLE ... ADD COLUMN`."""
    statements: list[str] = []
    tables = set(inspector.get_table_names())
    for table, columns in new_columns.items():
        if table not in tables:
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, decl in columns.items():
            if name not in existing:
                statements.append(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    return statements


def _migrate_columns() -> None:
    with engine.connect() as conn:
        for statement in _add_column_statements(inspect(conn), _NEW_COLUMNS):
            conn.exec_driver_sql(statement)
        for statement in _add_column_statements(inspect(conn), _owner_columns()):
            conn.exec_driver_sql(statement)
        # `events.owner_id` predates this session as a nullable column (session 21).
        if "events" in inspect(conn).get_table_names():
            conn.exec_driver_sql("UPDATE events SET owner_id = ? WHERE owner_id IS NULL", (tenant.PERSONAL_OWNER,))
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_strokes_activity_id ON strokes(activity_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_activities_canonical_id ON activities(canonical_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_strength_sets_activity_id ON strength_sets(activity_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_gym_stations_gym_id ON gym_stations(gym_id)")
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


def _migrate_garmin_activity_fields() -> None:
    """One-time, idempotent (session 13 — see PLAN.md Part A): backfill `steps`/`bmr_kcal`
    for Garmin activities synced before this session from their already-stored `raw_json`,
    rather than re-downloading anything from Garmin. Safe on every startup — only touches
    rows where both are still unset."""
    import json as _json

    from sqlmodel import Session, select

    from catch.core.models import Activity

    with Session(engine) as session:
        rows = session.exec(
            select(Activity).where(
                Activity.source == "garmin",
                Activity.steps.is_(None),
                Activity.bmr_kcal.is_(None),
                Activity.raw_json.is_not(None),
            )
        ).all()
        for row in rows:
            try:
                raw = _json.loads(row.raw_json)
            except ValueError:
                continue
            row.steps = raw.get("steps")
            row.bmr_kcal = raw.get("bmrCalories")
            session.add(row)
        if rows:
            session.commit()


def _seed_exercise_library() -> None:
    """Idempotent: inserts any seed exercise (`catch/seed/exercises.json` —
    yuhonas/free-exercise-db, vendored at build time, see PLAN.md's session 14 section for
    the licence/derivation) whose `external_id` isn't already in the table. Lives under
    `catch/seed/`, not `catch/data/` — the repo's `.gitignore` has an unanchored `data/` rule
    for the *runtime* `data/` directory (the SQLite DB, downloaded FIT files) at the repo
    root, which would have silently excluded a `catch/data/` subdirectory too. Never touches a
    row the athlete has since edited — `Exercise.external_id` is only set at seed time and
    never rewritten, so a user edit (e.g. correcting `movement_pattern`) survives every
    restart untouched."""
    import json as _json
    from pathlib import Path as _Path

    from sqlmodel import Session, select

    from catch.core.models import Exercise

    seed_path = _Path(__file__).resolve().parent.parent / "seed" / "exercises.json"
    if not seed_path.exists():
        return
    with Session(engine) as session:
        existing = set(session.exec(select(Exercise.external_id).where(Exercise.external_id.is_not(None))).all())
        seed = _json.loads(seed_path.read_text())
        added = 0
        for e in seed:
            if e["external_id"] in existing:
                continue
            session.add(
                Exercise(
                    external_id=e["external_id"],
                    name=e["name"],
                    default_equipment_type=e["default_equipment_type"],
                    movement_pattern=e["movement_pattern"],
                    unilateral=e["unilateral"],
                    primary_muscles_json=_json.dumps(e["primary_muscles"]),
                    secondary_muscles_json=_json.dumps(e["secondary_muscles"]),
                    custom=False,
                )
            )
            added += 1
        if added:
            session.commit()


def _seed_workout_examples() -> None:
    from sqlmodel import Session

    from catch.sync import workout_library

    with Session(engine) as session:
        workout_library.seed_examples(session)


def _seed_wellness_readings() -> None:
    """Session 23: a Garmin-era wellness row gets the readings it implies, once (idempotent)."""
    from sqlmodel import Session

    from catch.sync import wellness_readings

    with Session(engine) as session:
        wellness_readings.seed_from_daily_wellness(session)


def _ensure_personal_profile() -> None:
    from sqlmodel import Session, select

    from catch.core.models import UserProfile

    with Session(engine) as session:
        if session.exec(select(UserProfile).where(UserProfile.id == tenant.PERSONAL_OWNER)).first() is None:
            session.add(UserProfile(id=tenant.PERSONAL_OWNER, display_name="You"))
            session.commit()


def init_db() -> None:
    if settings.is_public:
        # The public schema is changed only by Alembic, run by an operator with the admin URL —
        # never by the app, and never with the runtime role (docs/public-architecture.md §5).
        return
    SQLModel.metadata.create_all(engine)
    _migrate_columns()
    _ensure_personal_profile()
    _migrate_linked_activities_to_canonical()
    _migrate_garmin_activity_fields()
    with tenant.system():
        _seed_exercise_library()
        _seed_workout_examples()
    _seed_wellness_readings()


@contextmanager
def get_session():
    with Session(engine) as session:
        yield session
