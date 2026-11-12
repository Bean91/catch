from __future__ import annotations

"""Session 22: runs the library / technique-note / feedback schema and services against a real
PostgreSQL server. Skipped unless CATCH_TEST_PG_URL is set (e.g.
`postgresql+psycopg://user@127.0.0.1:5432/dbname`) — the Pi's own suite needs no database server.
Run with: CATCH_TEST_PG_URL=... uv run --with 'psycopg[binary]' pytest tests/test_postgres_optional.py
Each run uses its own throwaway schema and drops it afterwards."""

import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session, SQLModel, select

URL = os.environ.get("CATCH_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not URL, reason="CATCH_TEST_PG_URL not set")


@pytest.fixture
def pg():
    schema = f"catch_{uuid.uuid4().hex[:10]}"
    admin = create_engine(URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    eng = create_engine(URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield eng
    finally:
        eng.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_whole_metadata_creates_on_postgres_and_a_second_run_is_a_noop(pg):
    SQLModel.metadata.create_all(pg)
    SQLModel.metadata.create_all(pg)
    tables = set(inspect(pg).get_table_names())
    assert {"workout_templates", "technique_notes", "coach_feedback", "coach_feedback_revisions", "planned_workouts", "api_tokens"} <= tables


def test_add_column_statements_run_on_postgres(pg):
    from catch.core import db as db_module

    with pg.begin() as conn:
        conn.execute(text("CREATE TABLE api_tokens (id SERIAL PRIMARY KEY, name TEXT, token_hash TEXT, created_at TIMESTAMP, last_used_at TIMESTAMP)"))
        conn.execute(text("INSERT INTO api_tokens (name, token_hash) VALUES ('legacy', 'h')"))
        conn.execute(text("CREATE TABLE planned_workouts (id SERIAL PRIMARY KEY, owner_id TEXT, title TEXT)"))
        stmts = db_module._add_column_statements(inspect(conn), {t: db_module._NEW_COLUMNS[t] for t in ("api_tokens", "planned_workouts")})
        assert len(stmts) == 3
        for s in stmts:
            conn.execute(text(s))
        assert db_module._add_column_statements(inspect(conn), {t: db_module._NEW_COLUMNS[t] for t in ("api_tokens", "planned_workouts")}) == []
        assert conn.execute(text("SELECT role, display_name FROM api_tokens")).one() == (None, None)


def test_library_and_feedback_services_behave_the_same_on_postgres(pg):
    from catch.core import principal as pr
    from catch.core.models import CanonicalActivity, CoachFeedback, Event, PlannedWorkout, TechniqueNote
    from catch.core.principal import ATHLETE
    from catch.sync import coaching_notes as cn
    from catch.sync import planning as sp
    from catch.sync import workout_library as lib

    SQLModel.metadata.create_all(pg)
    with Session(pg) as _s:  # the tenant foreign key is enforced here: the owner needs its profile row
        from catch.core.models import UserProfile

        _s.add(UserProfile(id="owner", display_name="You"))
        _s.commit()
    coach = pr.coach_principal(1, "Coach Sam")
    with Session(pg) as s:
        assert lib.seed_examples(s) >= 6 and lib.seed_examples(s) == 0
        mine = lib.create_template(s, "owner", {"name": "6x3", "workout_type": "erg_intervals", "tags": ["Speed"], "structure": {"blocks": [{"reps": 6, "work_s": 180, "rest_s": 120, "zone": "AT"}]}})
        assert [t.id for t in lib.search_templates(s, "owner", include_examples=False, tags=["speed"])] == [mine.id]
        assert len(lib.search_templates(s, "owner", only_examples=True)) >= 6
        lib.set_archived(s, "owner", mine.id, True)
        assert lib.search_templates(s, "owner", include_examples=False) == []
        lib.set_archived(s, "owner", mine.id, False)

        monday = sp.pl.week_start(sp.today())
        plans = lib.schedule_template(s, "owner", mine.id, monday, repeat={"weekdays": [0, 2], "count": 3})
        assert len(plans) == 3 and all(p.template_id == mine.id for p in plans)
        assert sp.build_week_summary(s, "owner", monday)["planned"]["minutes"] > 0

        from datetime import datetime, timezone

        c = CanonicalActivity(start=datetime(monday.year, monday.month, monday.day, 12, tzinfo=timezone.utc), duration=1700.0, sport_family="rowing", category="erg")
        s.add(c)
        s.commit()
        assert sp.link_planned(s, "owner", plans[0].id, c.id).linked_canonical_id == c.id

        private = cn.create_technique_note(s, "owner", ATHLETE, {"category": "catch", "text": "private one", "canonical_id": c.id})
        shared = cn.create_technique_note(s, "owner", ATHLETE, {"category": "drive", "text": "shared one", "visibility": "coach", "note_date": monday.isoformat()})
        assert [n.id for n in cn.list_technique_notes(s, "owner", coach)] == [shared.id]
        assert {n.id for n in cn.list_technique_notes(s, "owner", ATHLETE)} == {private.id, shared.id}

        ev = sp.create_event(s, "owner", {"name": "Head", "date": monday + timedelta(days=20), "type": "race"})
        fb = cn.create_feedback(s, "owner", coach, {"text": "v1", "focus_areas": ["catch"], "event_id": ev.id, "canonical_id": c.id})
        cn.update_feedback(s, "owner", coach, fb.id, {"text": "v2"})
        cn.respond_to_feedback(s, "owner", ATHLETE, fb.id, "thanks")
        assert [h["kind"] for h in cn.feedback_history(s, "owner", ATHLETE, fb.id)] == ["edit", "response"]
        assert [f.id for f in cn.list_feedback(s, "owner", ATHLETE, coach="sam", category="catch", date_from=monday - timedelta(days=1))] == [fb.id]
        with pytest.raises(cn.Forbidden):
            cn.update_feedback(s, "owner", ATHLETE, fb.id, {"text": "tamper"})
        sp.delete_event(s, "owner", ev.id)
        assert s.get(CoachFeedback, fb.id).event_id is None and s.exec(select(Event)).all() == []
        cn.delete_feedback(s, "owner", coach, fb.id)
        assert cn.list_feedback(s, "owner", ATHLETE) == []
        assert len(s.exec(select(PlannedWorkout)).all()) == 3 and len(s.exec(select(TechniqueNote)).all()) == 2
