"""Session 36: per-category exports — one person's rows only, whitelisted columns, units and zones in the file."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from sqlmodel import Session

from catch.core import tenant
from catch.core.models import Goal, Note
from catch.sync.exports import CATEGORIES
from catch.sync.matching import run_matching
from catch.sync.upsert import upsert_activity
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A, B = bearer(kit.ALICE), bearer(kit.BOB)


def _seed(engine, owner: str, title: str):
    with tenant.use_owner(owner), Session(engine) as s:
        upsert_activity(s, "garmin", f"act-{owner[:4]}", type="indoor_rowing", start=datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc),
                        duration=1800.0, distance=7000.0, avg_hr=140.0, title_hint=title)
        s.add(Note(date=datetime(2026, 11, 2).date(), text=f"{title} note"))
        s.add(Goal(text=f"{title} goal"))
        s.commit()
        run_matching(s)


def test_each_category_is_the_callers_own(pub_client, pub_engine):
    _seed(pub_engine, kit.ALICE, "Alice")
    _seed(pub_engine, kit.BOB, "Bob")
    for cat in CATEGORIES:
        for fmt in ("csv", "json"):
            r = pub_client.get(f"/api/export/{cat}", params={"format": fmt}, headers=A)
            assert r.status_code == 200, (cat, fmt, r.text)
            assert "Bob" not in r.text, cat
            assert r.headers["cache-control"] == "no-store"
    acts = list(csv.DictReader(io.StringIO(pub_client.get("/api/export/activities", headers=A).text)))
    assert len(acts) == 1
    row = acts[0]
    assert row["start_utc"].endswith("+00:00") and row["local_date"] == "2026-11-02" and "local_tz" in row
    assert row["duration_s"] == "1800.0" and row["distance_m"] == "7000.0"
    assert row["avg_split_s_per_500m_derived"] != ""
    notes = json.loads(pub_client.get("/api/export/notes", params={"format": "json"}, headers=A).text)["rows"]
    assert [n["text"] for n in notes] == ["Alice note"]


def test_no_secret_or_foreign_columns_and_unknown_category(pub_client, pub_engine):
    _seed(pub_engine, kit.ALICE, "Alice")
    for cat in CATEGORIES:
        header = pub_client.get(f"/api/export/{cat}", headers=A).text.split("\n", 1)[0].lower()
        for word in ("token", "secret", "password", "owner_id", "_enc", "hash", "raw_json"):
            assert word not in header, (cat, word)
    assert pub_client.get("/api/export/strokes_raw", headers=A).status_code == 404
    assert pub_client.get("/api/export/activities", params={"format": "xml"}, headers=A).status_code == 422
