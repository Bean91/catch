"""Cross-user isolation for EVERY owned table (session 24). One generated row per table, built for Alice and then for
Bob with identical natural keys (same dates, same external ids, same client ids) — if any primary or unique key
lacked the owner, Bob's insert would collide with Alice's; if any read, update or delete lacked the owner filter,
Bob would see or change hers."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select, update
from sqlmodel import Session, SQLModel

from catch.core import tenant, tenant_hooks
from catch.core.tenant import OwnedOrShared, TenantViolation
from tests.tenancy import kit

pytestmark = [pytest.mark.usefixtures("public"), pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")]


def _ordered() -> list[type]:
    by_table = {c.__tablename__: c for c in kit.owned_classes()}
    return [by_table[t.name] for t in SQLModel.metadata.sorted_tables if t.name in by_table]


@pytest.fixture(autouse=True)
def _no_parent_guard(monkeypatch):
    # The generic rows point at same-owner parents already; the parent guard has its own tests below.
    monkeypatch.setattr(tenant_hooks, "_check_refs", lambda *a, **k: None)


def _seed(engine, owner: str) -> dict[str, dict]:
    """One row per table for `owner`; returns {table: {column: value}} of each row's primary-key columns."""
    created: dict[str, dict] = {}
    with tenant.use_owner(owner), Session(engine) as s:
        for cls in _ordered():
            row = kit.build_row(cls, created)
            s.add(row)
            s.commit()
            s.refresh(row)
            created[cls.__tablename__] = {c.name: getattr(row, c.name) for c in cls.__table__.primary_key.columns if c.name != "owner_id"}
    return created


def test_every_owned_table_has_a_generated_row(engine):
    # Guards the generator itself: a new owned model that it can't build fails here, not silently in the loops below.
    created = _seed(engine, kit.ALICE)
    assert set(created) == {c.__tablename__ for c in kit.owned_classes()}


def test_users_with_identical_natural_keys_coexist_and_never_see_each_other(engine):
    alice, bob = _seed(engine, kit.ALICE), _seed(engine, kit.BOB)  # a collision would raise IntegrityError here
    for cls in _ordered():
        name = cls.__tablename__
        for owner, mine in ((kit.ALICE, alice), (kit.BOB, bob)):
            with tenant.use_owner(owner), Session(engine) as s:
                rows = s.exec(select(cls)).scalars().all()
                assert len(rows) == 1, f"{name}: {owner} sees {len(rows)} rows"
                assert rows[0].owner_id == owner, name
                assert s.execute(select(func.count()).select_from(cls)).scalar() == 1, name


def test_a_stranger_sees_nothing_and_changes_nothing(engine):
    _seed(engine, kit.ALICE)
    stranger = "99999999-9999-4999-8999-999999999999"
    with tenant.use_owner(stranger), Session(engine) as s:
        for cls in _ordered():
            if issubclass(cls, OwnedOrShared):
                continue  # shared reference tables: a stranger sees only NULL-owner rows, none exist here
            name = cls.__tablename__
            assert s.exec(select(cls)).scalars().all() == [], name
            assert s.execute(update(cls).values(owner_id=stranger)).rowcount == 0, name
            assert s.execute(delete(cls)).rowcount == 0, name
        s.commit()
    with tenant.use_owner(kit.ALICE), Session(engine) as s:
        for cls in _ordered():
            assert s.exec(select(cls)).scalars().all(), cls.__tablename__  # all still there, still hers


def test_primary_key_lookup_of_someone_elses_row_finds_nothing(engine):
    alice = _seed(engine, kit.ALICE)
    with tenant.use_owner(kit.BOB), Session(engine) as s:
        for cls in _ordered():
            pk = alice[cls.__tablename__]
            key = tuple(pk[c.name] for c in cls.__table__.primary_key.columns if c.name != "owner_id")
            owner_leads = "owner_id" in {c.name for c in cls.__table__.primary_key.columns}
            ident = (kit.ALICE, *key) if owner_leads else (key[0] if len(key) == 1 else key)
            assert s.get(cls, ident) is None, cls.__tablename__


def test_writing_a_row_that_names_another_owner_is_refused(engine):
    alice = _seed(engine, kit.ALICE)
    for cls in _ordered():
        with tenant.use_owner(kit.BOB), Session(engine) as s:
            row = kit.build_row(cls, alice)
            row.owner_id = kit.ALICE
            s.add(row)
            with pytest.raises(TenantViolation):
                s.flush()
            s.rollback()


def test_changing_a_loaded_rows_owner_is_refused(engine):
    _seed(engine, kit.ALICE)
    with tenant.use_owner(kit.ALICE), Session(engine) as s:
        row = s.exec(select(kit.owned_classes()[0])).scalars().first()
        row.owner_id = kit.BOB
        with pytest.raises(TenantViolation):
            s.flush()


def test_no_owner_means_no_access_in_a_public_deployment(engine):
    _seed(engine, kit.ALICE)
    from catch.core.tenant import NoTenantContext

    with Session(engine) as s:
        for cls in _ordered():
            with pytest.raises(NoTenantContext):
                s.exec(select(cls)).all()
    with pytest.raises(NoTenantContext):
        kit.build_row(_ordered()[0], {})  # building an owned row needs an owner too
