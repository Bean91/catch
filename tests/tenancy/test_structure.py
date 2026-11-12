"""Structural guarantees (session 24): a new table, key or query can't quietly escape the tenant model."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel

import catch.core.models  # noqa: F401
from catch.core import tenant_hooks
from catch.core.tenant import OwnedOrShared, OwnedStrict

ROOT = Path(__file__).resolve().parents[2]
GLOBAL_TABLES = {"user_profiles", "weather_cells"}  # no owner column by design (see docs/public-architecture.md §2)


def _migration(name: str):
    path = ROOT / "migrations" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _classes(marker):
    return {m.class_.__tablename__: m.class_ for m in SQLModel._sa_registry.mappers if issubclass(m.class_, marker)}


def test_every_table_is_owned_shared_or_explicitly_global():
    owned, shared = _classes(OwnedStrict), _classes(OwnedOrShared)
    assert not set(owned) & set(shared)
    unclassified = set(SQLModel.metadata.tables) - set(owned) - set(shared) - GLOBAL_TABLES
    assert not unclassified, f"tables with no tenant classification: {sorted(unclassified)}"


def test_every_owned_table_points_its_owner_at_user_profiles_with_cascade():
    for name in [*_classes(OwnedStrict), *_classes(OwnedOrShared)]:
        col = SQLModel.metadata.tables[name].c.owner_id
        fks = list(col.foreign_keys)
        assert len(fks) == 1 and fks[0].column.table.name == "user_profiles" and fks[0].ondelete == "CASCADE", name
        assert col.nullable == (name in _classes(OwnedOrShared)), name


# Keys that are deliberately NOT per owner, each for a stated reason.
GLOBAL_KEYS = {
    ("workout_templates", "uq_workout_templates_external_id"): "only seeded example rows (owner NULL) carry an external_id",
    ("planned_workouts", "uq_planned_workouts_linked_canonical"): "canonical ids are already unique across all owners",
}


def test_every_unique_key_and_primary_key_is_per_owner():
    for name, table in SQLModel.metadata.tables.items():
        if name in GLOBAL_TABLES:
            continue
        pk = [c.name for c in table.primary_key.columns]
        fk_cols = {c.name for c in table.columns if any(f.column.table.name != "user_profiles" for f in c.foreign_keys)}
        assert "owner_id" in pk or pk == ["id"] or (len(pk) == 1 and pk[0] in fk_cols), f"{name}: primary key {pk} is not per owner"
        for const in table.constraints:
            if isinstance(const, UniqueConstraint) and (name, const.name) not in GLOBAL_KEYS:
                assert "owner_id" in {c.name for c in const.columns}, f"{name}.{const.name} is a global unique key"
        for idx in table.indexes:
            if idx.unique and (name, idx.name) not in GLOBAL_KEYS:
                assert "owner_id" in {c.name for c in idx.columns}, f"{name}.{idx.name} is a global unique index"


def test_migration_0002_covers_exactly_the_tables_the_models_declare():
    m = _migration("0002_security")
    owned, shared = _classes(OwnedStrict), _classes(OwnedOrShared)
    assert set(m.OWNED) == set(owned) and set(m.SHARED) == set(shared)
    assert {m.PROFILES, m.GLOBAL_CACHE} == GLOBAL_TABLES
    # tenant FKs = every declared (non-EXTRA) reference to a strictly owned parent
    declared = {r for r in tenant_hooks.reference_columns() if r not in set(tenant_hooks.EXTRA_REFS) and r[2] in owned}
    assert {(c, col, p) for c, col, p, _ in m.TENANT_FKS} == declared


def test_the_baseline_snapshot_creates_every_table_and_only_those():
    sql = (ROOT / "migrations" / "versions" / "0001_baseline.sql").read_text()
    assert set(re.findall(r"^CREATE TABLE (\w+) \(", sql, flags=re.M)) == set(SQLModel.metadata.tables)


ALLOWED_RAW_SQL = {
    "catch/core/db.py",  # SQLite startup migration
    "catch/core/db_pg.py",  # role report / RLS probe, on the runtime connection
    "catch/core/tenant_hooks.py",  # the per-transaction role + claims
    "catch/core/device_tokens.py",  # SECURITY DEFINER lookup before an owner is known
    "catch/core/supabase_auth.py",  # SECURITY DEFINER session check
    "catch/api/routes_internal.py",  # SECURITY DEFINER user list + advisory lock
}


def test_no_raw_sql_or_unscoped_queries_outside_the_reviewed_modules():
    pattern = re.compile(r"exec_driver_sql|\btext\(|tenant_unscoped|bulk_insert_mappings|bulk_update_mappings|bulk_save_objects")
    offenders = []
    for path in (ROOT / "catch").rglob("*.py"):
        rel = str(path.relative_to(ROOT))
        if rel in ALLOWED_RAW_SQL or rel == "catch/core/tenant.py":
            continue
        if pattern.search(path.read_text()):
            offenders.append(rel)
    assert not offenders, f"raw SQL / unscoped option outside the reviewed modules: {offenders}"


def test_a_personal_install_never_imports_the_public_stack():
    code = (
        "import sys, catch.main\n"
        "bad = [m for m in ('psycopg', 'psycopg_binary', 'alembic', 'jwt', 'catch.core.supabase_auth', 'catch.core.db_pg') if m in sys.modules]\n"
        "print(','.join(bad))"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "CATCH_DB_PATH": "/tmp/catch-struct-test.db", "PYTHONPATH": str(ROOT)})
    # `-I` drops PYTHONPATH; run via the project interpreter's own site-packages instead
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "", f"the personal install imported: {out.stdout.strip()}"
