"""Session 36 follow-up: a per-recording stroke summary cache and template folders.

* `activities.stroke_summary_json` — derived from the recording's own strokes, never entered: the split-by-rate band aggregates
  and the rolling best-power curve, stamped with an algorithm version and the stroke count it was built from. A reader rebuilds
  it when either differs, and re-syncing a result's strokes clears it.
* `workout_templates.folder` — the owner's own folder label for a template. Shared examples (owner NULL) never carry one: a
  folder on a shared row would be everyone's folder.

New columns on existing owned tables: their RLS policies are per table and already cover them.

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE catch.activities ADD COLUMN stroke_summary_json VARCHAR")
    op.execute("ALTER TABLE catch.workout_templates ADD COLUMN folder VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE catch.workout_templates DROP COLUMN folder")
    op.execute("ALTER TABLE catch.activities DROP COLUMN stroke_summary_json")
