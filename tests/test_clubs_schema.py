"""The vocabularies in catch/analytics/clubs.py and challenges.py are also CHECK constraints in the models (and so migration 0006).
This keeps the two statements of each list identical, so a new role or metric can't be added to one and forgotten in the other."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import CheckConstraint
from sqlmodel import SQLModel

import catch.core.models  # noqa: F401
from catch.analytics import challenges as ch
from catch.analytics import clubs as c

CASES = [
    ("clubs", "ck_clubs_visibility", c.VISIBILITIES), ("clubs", "ck_clubs_audience", c.AUDIENCES), ("clubs", "ck_clubs_join_policy", c.JOIN_POLICIES),
    ("clubs", "ck_clubs_status", c.CLUB_STATUSES), ("club_members", "ck_club_members_role", c.ROLES), ("club_members", "ck_club_members_status", c.MEMBER_STATUSES),
    ("club_members", "ck_club_members_age_class", c.AGE_CLASSES), ("club_profiles", "ck_club_profiles_age_class", c.AGE_CLASSES),
    ("club_invites", "ck_club_invites_role", c.INVITE_ROLES), ("club_join_requests", "ck_club_join_requests_role", c.INVITE_ROLES),
    ("club_join_requests", "ck_club_join_requests_status", c.REQUEST_STATUSES), ("club_announcements", "ck_club_announcements_status", c.POST_STATUSES),
    ("club_sessions", "ck_club_sessions_status", c.SESSION_STATUSES), ("club_challenges", "ck_club_challenges_status", c.CHALLENGE_STATUSES),
    ("club_challenges", "ck_club_challenges_metric", ch.METRICS), ("club_challenges", "ck_club_challenges_sport", ch.SPORTS),
    ("club_reports", "ck_club_reports_target", c.REPORT_TARGETS),
]


def _values(table: str, name: str) -> tuple[str, ...]:
    for con in SQLModel.metadata.tables[table].constraints:
        if isinstance(con, CheckConstraint) and con.name == name:
            return tuple(re.findall(r"'([^']+)'", str(con.sqltext)))
    raise AssertionError(f"{table}.{name} not found")


@pytest.mark.parametrize("table,name,vocab", CASES)
def test_the_python_vocabulary_equals_the_check_constraint(table, name, vocab):
    assert set(_values(table, name)) == set(vocab)


def test_the_migration_declares_the_same_check_names_the_models_do():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0006_clubs.py").read_text()
    for table in {t for t, _, _ in CASES}:
        for con in SQLModel.metadata.tables[table].constraints:
            if isinstance(con, CheckConstraint) and con.name:
                assert con.name in src, f"{con.name} is in the model but not in migration 0006"


def test_no_club_table_has_a_column_that_could_hold_a_health_value():
    """Structural half of the privacy guarantee (the behavioural half is tests/tenancy/test_clubs_privacy.py): nothing a club table
    can store is a recovery, sleep, weight, nutrition or heart-rate figure."""
    banned = re.compile(r"weight|calorie|kcal|bmi|body_(fat|comp|mass)|\bfat\b|fat_pct|sleep|hrv|heart|hr_|recovery|strain|readiness|illness|nutrition|protein|carb|macro|\brpe\b|niggle|mood|stress|temperature|skin_temp", re.I)
    from tests.tenancy.test_structure import CLUB_SCOPED

    for name in (*CLUB_SCOPED, "club_blocks"):
        for col in SQLModel.metadata.tables[name].columns:
            assert not banned.search(col.name), f"{name}.{col.name} looks like a health column"
