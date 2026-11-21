"""Session 33: combined workouts, erg/bike pieces.

* `canonical_activities.merge_mode` — NULL keeps today's duplicate-recording semantics; "combined" marks a workout the athlete
  merged from consecutive or overlapping recordings (docs/analytics.md §31).
* `merge_log.snapshot_json` — what undoing a combine needs to give each merged-away workout back.
* `pieces.modality` — "rowing_erg" (pace per 500 m) or "bike" (pace per 1000 m). Every existing piece is a rowing erg piece.

New columns on existing owned tables: their RLS policies are per table and already cover them.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE catch.canonical_activities ADD COLUMN merge_mode VARCHAR")
    op.execute("ALTER TABLE catch.merge_log ADD COLUMN snapshot_json VARCHAR")
    op.execute("ALTER TABLE catch.pieces ADD COLUMN modality VARCHAR NOT NULL DEFAULT 'rowing_erg'")


def downgrade() -> None:
    op.execute("ALTER TABLE catch.pieces DROP COLUMN modality")
    op.execute("ALTER TABLE catch.merge_log DROP COLUMN snapshot_json")
    op.execute("ALTER TABLE catch.canonical_activities DROP COLUMN merge_mode")
