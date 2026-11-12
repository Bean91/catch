"""Through a REAL Supavisor pooler in transaction mode (session 24). Needs the local stack started with
`[db.pooler] enabled = true`, and CATCH_TEST_SUPABASE_POOLER_URL (e.g. postgresql://postgres.pooler-dev:postgres@127.0.0.1:54329/postgres).

The local pooler only knows its provisioned `postgres.pooler-dev` user (tenant id "pooler-dev") (a hosted project also accepts custom roles
as `<role>.<ref>`), so this proves the *mechanism* — identity set per transaction survives transaction pooling and
never leaks between clients — with a role that can SET ROLE; the role restrictions themselves are tested directly
in test_rls.py."""

from __future__ import annotations

import os
import random
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlmodel import Session

from catch.core import tenant
from tests.pg.conftest import signup

POOLER = os.environ.get("CATCH_TEST_SUPABASE_POOLER_URL", "")
pytestmark = pytest.mark.skipif(not POOLER, reason="CATCH_TEST_SUPABASE_POOLER_URL not set")


@pytest.fixture()
def pooled(clean):
    from catch.core.db_pg import build_pg_engine

    eng = build_pg_engine(POOLER, pool_mode="transaction")
    yield eng
    eng.dispose()


def test_identity_is_per_transaction_and_never_leaks_between_clients_on_a_transaction_pooler(pooled):
    from catch.core.models import Note

    users = [signup("pool-a"), signup("pool-b"), signup("pool-c")]
    for u in users:
        with tenant.use_owner(u.id), Session(pooled) as s:
            for i in range(3):
                s.add(Note(date=date(2026, 11, 1 + i), text=f"{u.id}:{i}"))
                s.commit()
    rng = random.Random(7)
    for _ in range(60):  # interleaved clients, repeated identical statements, many commits
        u = rng.choice(users)
        with tenant.use_owner(u.id), Session(pooled) as s:
            texts = s.execute(select(Note.text)).scalars().all()
            assert sorted(texts) == [f"{u.id}:{i}" for i in range(3)]
            assert s.execute(text("SELECT auth.uid()::text")).scalar() == u.id
    with pooled.connect() as conn:  # a bare pooled connection afterwards carries no identity
        assert conn.execute(text("SELECT coalesce(current_setting('request.jwt.claim.sub', true), '')")).scalar() == ""
        conn.rollback()
