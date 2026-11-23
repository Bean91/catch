"""Session 36: structured goals, event results, editable block categories.

* `goals` — measurable goals (`kind`, sport, target, unit, start/end, completed_at, params_json). Existing rows are free-text
  goals (`kind` NULL reads as "text") and keep working unchanged.
* `events` — `participation` (planned | entered | completed | withdrawn | did_not_start), `sport`, and the linked result:
  `result_canonical_id` (the workout) and `result_piece_id` (a piece inside it). Both are composite tenant foreign keys, so a
  result can only ever point at the same owner's row, and deleting the workout/piece clears the link.
* `training_phases.category` — the athlete's own label for a block (Base, Build, Peak, Taper, Recovery or anything else).
  `kind` stays: it drives the review-flag rule.

New columns on existing owned tables: their RLS policies are per table and already cover them.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TS = "TIMESTAMP WITH TIME ZONE"

GOAL_COLUMNS = (
    ("kind", "VARCHAR"),
    ("sport", "VARCHAR"),
    ("target_value", "FLOAT"),
    ("unit", "VARCHAR"),
    ("start_date", "DATE"),
    ("end_date", "DATE"),
    ("completed_at", TS),
    ("params_json", "VARCHAR"),
)
EVENT_COLUMNS = (
    ("participation", "VARCHAR"),
    ("sport", "VARCHAR"),
    ("result_canonical_id", "INTEGER"),
    ("result_piece_id", "INTEGER"),
)
TENANT_FKS = (
    ("events", "result_canonical_id", "canonical_activities"),
    ("events", "result_piece_id", "pieces"),
)


def upgrade() -> None:
    for name, type_ in GOAL_COLUMNS:
        op.execute(f"ALTER TABLE catch.goals ADD COLUMN {name} {type_}")
    for name, type_ in EVENT_COLUMNS:
        op.execute(f"ALTER TABLE catch.events ADD COLUMN {name} {type_}")
    op.execute("ALTER TABLE catch.training_phases ADD COLUMN category VARCHAR")
    for child, col, parent in TENANT_FKS:
        op.execute(
            f"ALTER TABLE catch.{child} ADD CONSTRAINT fk_tenant_{child}_{col} "
            f"FOREIGN KEY (owner_id, {col}) REFERENCES catch.{parent} (owner_id, id) ON DELETE SET NULL ({col})"
        )


def downgrade() -> None:
    for child, col, _ in TENANT_FKS:
        op.execute(f"ALTER TABLE catch.{child} DROP CONSTRAINT fk_tenant_{child}_{col}")
    op.execute("ALTER TABLE catch.training_phases DROP COLUMN category")
    for name, _ in reversed(EVENT_COLUMNS):
        op.execute(f"ALTER TABLE catch.events DROP COLUMN {name}")
    for name, _ in reversed(GOAL_COLUMNS):
        op.execute(f"ALTER TABLE catch.goals DROP COLUMN {name}")
