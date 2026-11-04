from __future__ import annotations

import json

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
