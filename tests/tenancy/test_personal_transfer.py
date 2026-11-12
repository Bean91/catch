"""Moving a personal install's data into a public account (session 24, docs/personal-to-public.md)."""

from __future__ import annotations

import gzip
import json

import pytest
from sqlalchemy import select
from sqlmodel import Session

from catch.core import tenant
from catch.core.models import Activity, CanonicalActivity, Exercise, Food, OAuthToken, Piece, SavedMeal, StrengthTemplate
from catch.sync import personal_transfer as pt
from tests.tenancy import kit
from tests.tenancy.conftest import public_mode


def _populate_personal(engine):
    """Every owned table gets one generated row (as the Pi's one owner), plus the cross-references a real install has."""
    created: dict[str, dict] = {}
    with Session(engine) as s:
        seeded = Exercise(owner_id=None, external_id="seed-squat", name="Squat", default_equipment_type="barbell", movement_pattern="squat")
        with tenant.system():
            s.add(seeded)
            s.commit()
            s.refresh(seeded)
        by_table = {c.__tablename__: c for c in kit.owned_classes()}
        from sqlmodel import SQLModel

        for table in SQLModel.metadata.sorted_tables:
            cls = by_table.get(table.name)
            if cls is None or cls is Exercise:
                continue
            row = kit.build_row(cls, created)
            s.add(row)
            s.commit()
            s.refresh(row)
            created[table.name] = {c.name: getattr(row, c.name) for c in cls.__table__.primary_key.columns if c.name != "owner_id"}
        act = s.get(Activity, created["activities"]["id"])
        act.canonical_id = created["canonical_activities"]["id"]  # the generator can't close this cycle
        food_id = created["foods"]["id"]
        s.add(SavedMeal(name="Oats", items_json=json.dumps([{"food_id": food_id, "quantity": 80, "unit": "g"}])))
        s.add(StrengthTemplate(name="Push", items_json=json.dumps([{"exercise_id": seeded.id, "target_sets": 3}])))
        s.commit()
        return seeded.id, food_id


def _seed_target_library(engine):
    with Session(engine) as s, tenant.system():
        s.add(Exercise(owner_id=None, external_id="seed-squat", name="Squat", default_equipment_type="barbell", movement_pattern="squat"))
        s.add(Exercise(owner_id=None, external_id="seed-other", name="Other", default_equipment_type="barbell", movement_pattern="hinge"))
        s.commit()


@pytest.fixture()
def exported(engine, tmp_path):
    seeded_id, food_id = _populate_personal(engine)
    with Session(engine) as s:
        manifest = pt.export_personal(s, tmp_path / "personal.jsonl.gz")
    return tmp_path / "personal.jsonl.gz", manifest, seeded_id, food_id


def test_the_export_leaves_out_credentials_device_bindings_and_derived_data(exported):
    path, manifest, *_ = exported
    tables_in_file = {json.loads(line)["t"] for line in gzip.open(path, "rt") if "manifest" not in line[:12]}
    for excluded in pt.EXCLUDED_TABLES:
        assert excluded not in tables_in_file, excluded
    assert "oauth_tokens" in manifest["excluded"] and "ai_credentials" in manifest["excluded"]
    assert pt.verify(path)["sha256"] == manifest["sha256"]


def test_a_damaged_or_edited_file_is_refused(exported, tmp_path):
    path, *_ = exported
    lines = gzip.open(path, "rt").read().splitlines()
    lines[0] = lines[0].replace("x-", "y-", 1)
    bad = tmp_path / "edited.jsonl.gz"
    with gzip.open(bad, "wt") as f:
        f.write("\n".join(lines) + "\n")
    with pytest.raises(pt.ImportRefused):
        pt.verify(bad)
    with gzip.open(tmp_path / "junk.jsonl.gz", "wt") as f:
        f.write('{"hello": 1}\n')
    with pytest.raises(pt.ImportRefused):
        pt.verify(tmp_path / "junk.jsonl.gz")


def test_import_gives_the_account_its_own_rows_with_every_reference_repointed(exported, sqlite_engine):
    path, manifest, seeded_id, food_id = exported
    _seed_target_library(sqlite_engine)
    with public_mode():
        # an unrelated user already lives in the target database, with ids that would collide with the incoming ones
        with tenant.use_owner(kit.BOB), Session(sqlite_engine) as s:
            for cls in (CanonicalActivity,):
                s.add(cls(sport_family="rowing"))
            s.commit()
        with Session(sqlite_engine) as s:
            report = pt.import_into_account(s, path, owner_id=kit.ALICE)
        assert report["imported"]["activities"] == 1 and "oauth_tokens" not in report["imported"]
        with tenant.use_owner(kit.ALICE), Session(sqlite_engine) as s:
            activity = s.execute(select(Activity)).scalars().one()
            canonical = s.execute(select(CanonicalActivity)).scalars().all()
            assert [c.id for c in canonical] == [activity.canonical_id] and canonical[0].owner_id == kit.ALICE
            assert s.execute(select(OAuthToken)).scalars().all() == []  # credentials are never carried over
            piece = s.execute(select(Piece)).scalars().one()
            assert piece.canonical_id == activity.canonical_id
            # the seeded exercise maps onto the target's own seeded row; embedded ids follow
            target_exercise = s.execute(select(Exercise).where(Exercise.external_id == "seed-squat")).scalars().one()
            assert json.loads(s.execute(select(StrengthTemplate).where(StrengthTemplate.name == "Push")).scalars().one().items_json)[0]["exercise_id"] == target_exercise.id
            foods = s.execute(select(Food)).scalars().all()
            assert [f.owner_id for f in foods] == [kit.ALICE]
            assert json.loads(s.execute(select(SavedMeal).where(SavedMeal.name == "Oats")).scalars().one().items_json)[0]["food_id"] == foods[0].id
        with tenant.use_owner(kit.BOB), Session(sqlite_engine) as s:  # Bob sees nothing of it
            assert s.execute(select(Activity)).scalars().all() == []
            assert len(s.execute(select(CanonicalActivity)).scalars().all()) == 1


def test_import_refuses_a_second_run_and_a_dry_run_writes_nothing(exported, sqlite_engine):
    path, *_ = exported
    _seed_target_library(sqlite_engine)
    with public_mode():
        with Session(sqlite_engine) as s:
            dry = pt.import_into_account(s, path, owner_id=kit.ALICE, dry_run=True)
        assert dry["dry_run"] and dry["imported"]["activities"] == 1
        with tenant.use_owner(kit.ALICE), Session(sqlite_engine) as s:
            assert s.execute(select(Activity)).scalars().all() == []
        with Session(sqlite_engine) as s:
            pt.import_into_account(s, path, owner_id=kit.ALICE)
        with Session(sqlite_engine) as s, pytest.raises(pt.ImportRefused, match="already has data"):
            pt.import_into_account(s, path, owner_id=kit.ALICE)
