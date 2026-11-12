"""Baseline: every table, from the frozen DDL snapshot (0001_baseline.sql).

Revision ID: 0001
Revises:
"""
import re
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).with_name("0001_baseline.sql")).read_text()
    sql = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
    statements = [s.strip() for s in sql.split(";\n") if s.strip()]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    # Drops the tables this revision created (not the schema: Alembic's own version table lives in it).
    sql = (Path(__file__).with_name("0001_baseline.sql")).read_text()
    for name in re.findall(r"^CREATE TABLE (\w+) \(", sql, flags=re.M):
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
