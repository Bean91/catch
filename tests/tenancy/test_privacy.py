"""Privacy center (session 28): the export is complete, contains only the caller's data and no secret; category deletion is scoped,
confirmed and throttled."""

from __future__ import annotations

import gzip
import json

import pytest
from sqlmodel import Session, select

from catch.coach import limits
from catch.core import secret_store, tenant
from catch.core.models import AiCredential, CoachConversation, Note
from catch.sync import privacy
from tests.tenancy import kit
from tests.tenancy.conftest import bearer
from tests.tenancy.test_isolation_generic import _no_parent_guard, _seed  # noqa: F401

pytestmark = [pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")]
A, B = bearer(kit.ALICE), bearer(kit.BOB)


def _lines(resp) -> list[dict]:
    return [json.loads(line) for line in gzip.decompress(resp.content).decode().splitlines()]


def test_every_owned_table_is_exported_or_explicitly_withheld_with_a_reason():
    from catch.sync import privacy as p

    owned = {c.__tablename__ for c in p.owned_classes()}
    assert set(p.exported_tables()) | set(p.EXPORT_SKIPPED) == owned
    assert not set(p.exported_tables()) & set(p.EXPORT_SKIPPED)
    assert set(p.WITHHELD_COLUMNS) <= owned and all(p.EXPORT_SKIPPED.values())
    for table, cols in p.WITHHELD_COLUMNS.items():
        real = {c.name for c in next(c for c in p.owned_classes() if c.__tablename__ == table).__table__.columns}
        assert cols <= real, (table, cols - real)


def test_every_global_table_with_a_person_column_is_covered_by_the_export():
    from catch.sync import account_store

    for table, column in account_store.OWNER_COLUMN.items():
        cls = account_store._table_class(table)
        assert column in {c.name for c in cls.__table__.columns}, (table, column)


def test_the_export_holds_the_callers_rows_in_every_table_and_nothing_of_anyone_elses(pub_client, pub_engine):
    _seed(pub_engine, kit.ALICE)
    _seed(pub_engine, kit.BOB)
    for h in (A, B):
        pub_client.get("/api/me", headers=h)
    resp = pub_client.get("/api/privacy/export", headers=A)
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/gzip" and "attachment" in resp.headers["content-disposition"]
    assert resp.headers["cache-control"] == "no-store"
    lines = _lines(resp)
    assert lines[0]["manifest"]["kind"] == "catch-account-export" and "footer" in lines[-1]
    tables = {line["table"] for line in lines if "table" in line}
    assert tables >= set(privacy.exported_tables()) - {"foods", "exercises", "workout_templates"}  # every table the generator filled
    for line in lines:
        row = line.get("row")
        if row and "owner_id" in row:
            assert row["owner_id"] == kit.ALICE, line["table"]
    counts = lines[-1]["footer"]["counts"]
    assert counts["notes"] == 1 and counts["coach_conversations"] == 1


def test_secrets_are_withheld_from_the_export(pub_client, pub_engine):
    blob, kid = secret_store.seal("sk-ant-SENTINEL-export-key-0123456789", owner_id=kit.ALICE, provider="anthropic")
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        s.add(AiCredential(owner_id=kit.ALICE, provider="anthropic", key_enc=blob, key_id=kid, last4="6789"))
        s.commit()
    pub_client.get("/api/me", headers=A)
    raw = gzip.decompress(pub_client.get("/api/privacy/export", headers=A).content).decode()
    assert "SENTINEL-export-key" not in raw and blob not in raw
    rows = [json.loads(line) for line in raw.splitlines() if '"table":"ai_credentials"' in line]
    assert rows and "key_enc" not in rows[0]["row"] and rows[0]["row"]["last4"] == "6789"
    assert json.loads(raw.splitlines()[-1])["footer"]["withheld"]["ai_credentials"] == ["key_enc"]


def test_the_export_is_throttled_per_day(pub_client, pub_engine):
    pub_client.get("/api/me", headers=A)
    codes = []
    for _ in range(5):
        limits._windows.clear()  # leave only the daily ceiling in play
        codes.append(pub_client.get("/api/privacy/export", headers=A).status_code)
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    limits._daily.clear()


def test_another_user_has_their_own_daily_allowance(pub_client, pub_engine):
    for _ in range(3):
        limits._windows.clear()
        assert pub_client.get("/api/privacy/export", headers=A).status_code == 200
    limits._windows.clear()
    assert pub_client.get("/api/privacy/export", headers=B).status_code == 200
    limits._daily.clear()


def test_deleting_a_category_removes_only_the_callers_rows_of_exactly_those_tables(pub_client, pub_engine):
    _seed(pub_engine, kit.ALICE)
    _seed(pub_engine, kit.BOB)
    for h in (A, B):
        pub_client.get("/api/me", headers=h)
    denied = pub_client.request("DELETE", "/api/privacy/data/conversations", headers=A, json={})
    assert denied.status_code == 400
    done = pub_client.request("DELETE", "/api/privacy/data/conversations", headers=A, json={"confirm": True})
    assert done.status_code == 200 and done.json()["rows_removed"] >= 2
    with Session(pub_engine) as s:
        def n(cls, owner):
            with tenant.use_owner(owner):
                return len(s.exec(select(cls)).all())

        assert n(CoachConversation, kit.ALICE) == 0 and n(CoachConversation, kit.BOB) == 1  # Bob's chats survive
        assert n(Note, kit.ALICE) == 1  # a different category is untouched


def test_unknown_categories_404_and_every_category_is_deletable_and_scoped(pub_client, pub_engine, monkeypatch):
    from catch.api import routes_account

    purged = []
    monkeypatch.setattr(routes_account, "purge_storage", lambda token, owner: purged.append(owner) or 2)
    pub_client.get("/api/me", headers=A)
    assert pub_client.request("DELETE", "/api/privacy/data/everything", headers=A, json={"confirm": True}).status_code == 404
    _seed(pub_engine, kit.ALICE)
    _seed(pub_engine, kit.BOB)
    for key in privacy.DELETE_CATEGORIES:
        limits._windows.clear()
        assert pub_client.request("DELETE", f"/api/privacy/data/{key}", headers=A, json={"confirm": True}).status_code == 200, key
    from sqlalchemy import func

    assert purged == [kit.ALICE]  # the media category also clears stored files, and only for the caller
    with Session(pub_engine) as s, tenant.use_owner(kit.BOB):
        for key, spec in privacy.DELETE_CATEGORIES.items():
            for table in spec["tables"]:
                cls = next(c for c in privacy.owned_classes() if c.__tablename__ == table)
                assert s.execute(select(func.count()).select_from(cls)).scalar() == 1, (key, table)  # Bob kept his


def test_the_summary_counts_the_callers_rows_and_says_what_is_public(pub_client, pub_engine):
    _seed(pub_engine, kit.ALICE)
    _seed(pub_engine, kit.BOB)
    pub_client.get("/api/me", headers=A)
    data = pub_client.get("/api/privacy/summary", headers=A).json()
    assert {c["key"] for c in data["categories"]} == set(privacy.DELETE_CATEGORIES)
    assert all(c["rows"] >= 1 for c in data["categories"])  # one generated row per table, Alice's only
    assert data["public"] == {"leaderboard_profile": None, "published_results": 0, "club_memberships": 0}


def test_privacy_routes_need_a_signed_in_user(pub_client):
    assert pub_client.get("/api/privacy/summary").status_code == 401
    assert pub_client.get("/api/privacy/export").status_code == 401
    assert pub_client.request("DELETE", "/api/privacy/data/notes_checkins", json={"confirm": True}).status_code == 401
