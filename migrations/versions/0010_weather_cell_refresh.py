"""Session 31 (launch audit L-36): let a user request refresh a *provisional* weather cell-day.

`sync/weather.py::get_cell_day` re-fetches a cell-day that was stored before the day was complete and updates that row in place.
0002 granted `authenticated` only SELECT and INSERT on `weather_cells`, so on Postgres the refresh failed with "permission denied"
and `enrich_pending` stopped at the first such activity. UPDATE is granted for provisional rows only (`complete = false`), so a
finished cell-day still can't be rewritten by anyone's request. No DELETE.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

POLICY_COUNT_ABSOLUTE = {"weather_cells": 3}  # select + insert (0002) + this provisional-only update


def upgrade() -> None:
    op.execute("GRANT UPDATE ON catch.weather_cells TO authenticated")
    op.execute("CREATE POLICY weather_cells_update ON catch.weather_cells FOR UPDATE TO authenticated USING (complete = false) WITH CHECK (true)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS weather_cells_update ON catch.weather_cells")
    op.execute("REVOKE UPDATE ON catch.weather_cells FROM authenticated")
