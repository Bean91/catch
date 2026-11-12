"""Alembic environment for the public schema (docs/public-setup.md).

Migrations run with an admin URL, inside the `catch` schema (so the objects land there and the version table
sits beside them), and are the only thing that ever changes the public database's structure."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlmodel import SQLModel

import catch.core.models  # noqa: F401  (registers the tables on SQLModel.metadata)
from catch.core.db_pg import normalize_url

config = context.config
target_metadata = SQLModel.metadata
SCHEMA = "catch"


def _url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or os.environ.get("DATABASE_ADMIN_URL", "")
    return normalize_url(url)


def _include_object(obj, name, type_, reflected, compare_to):
    # Created by migrations 0002/0003, not modelled: composite tenant foreign keys, their parents' (owner_id, id)
    # unique constraints, and the policy/role/function layer (never reflected as objects here).
    if type_ == "unique_constraint" and name and name.startswith("uq_owner_id_"):
        return False
    if type_ == "foreign_key_constraint" and name and name.startswith("fk_tenant_"):
        return False
    return True


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.execute(text(f"SET search_path TO {SCHEMA}, public"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=False,
            include_object=_include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline SQL generation is not supported; run against a database.")
run_migrations_online()
