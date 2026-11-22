"""Session 33: merging workouts and piece photos are scoped to the signed-in account — another person's ids are simply not found,
whether they arrive in the path or in the request body."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from catch.core import tenant
from catch.core.models import CanonicalActivity, Piece, PiecePhoto
from catch.sync.matching import run_matching
from catch.sync.upsert import upsert_activity
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A, B = bearer(kit.ALICE), bearer(kit.BOB)
T0 = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 256


def _two_workouts(engine, owner: str) -> list[int]:
    with tenant.use_owner(owner), Session(engine) as s:
        a = upsert_activity(s, "garmin", "p1", type="indoor_rowing", start=T0, duration=1800.0, distance=7000.0, avg_hr=140.0)
        b = upsert_activity(s, "garmin", "p2", type="indoor_rowing", start=T0 + timedelta(minutes=40), duration=1200.0, distance=5000.0, avg_hr=150.0)
        run_matching(s)
        s.refresh(a)
        s.refresh(b)
        return [a.canonical_id, b.canonical_id]


def test_another_persons_workouts_cannot_be_previewed_merged_or_unmerged(pub_client, pub_engine):
    alice = _two_workouts(pub_engine, kit.ALICE)
    bob = _two_workouts(pub_engine, kit.BOB)

    assert pub_client.post("/api/activities/combine/preview", headers=B, json={"canonical_ids": alice}).status_code == 404
    # Mixing one of Bob's with one of Alice's doesn't let Bob reach hers either.
    assert pub_client.post("/api/activities/combine/preview", headers=B, json={"canonical_ids": [bob[0], alice[1]]}).status_code == 404
    assert pub_client.post("/api/activities/combine", headers=B, json={"canonical_ids": alice, "preview_hash": "0" * 24}).status_code == 404

    preview = pub_client.post("/api/activities/combine/preview", headers=A, json={"canonical_ids": alice}).json()
    assert preview["compatible"]
    done = pub_client.post("/api/activities/combine", headers=A, json={"canonical_ids": alice, "preview_hash": preview["preview_hash"]})
    assert done.status_code == 200
    assert pub_client.post(f"/api/activities/{alice[0]}/uncombine", headers=B).status_code == 404

    with tenant.use_owner(kit.BOB), Session(pub_engine) as s:
        assert len(s.exec(select(CanonicalActivity)).all()) == 2  # Bob's two workouts untouched
    with tenant.use_owner(kit.ALICE), Session(pub_engine) as s:
        assert [c.merge_mode for c in s.exec(select(CanonicalActivity)).all()] == ["combined"]


def test_a_piece_with_a_photo_lands_in_the_signed_in_account_only(pub_client, pub_engine):
    alice = _two_workouts(pub_engine, kit.ALICE)
    payload = {"piece_type": "2000m", "splits": [], "distance_m": 2000.0, "duration_s": 400.0, "source": "photo"}

    refused = pub_client.post(
        f"/api/activities/{alice[0]}/pieces/with-photo", headers=B, data={"payload": json.dumps(payload)}, files={"photo": ("p.jpg", JPEG, "image/jpeg")}
    )
    assert refused.status_code == 404
    made = pub_client.post(
        f"/api/activities/{alice[0]}/pieces/with-photo", headers=A, data={"payload": json.dumps(payload)}, files={"photo": ("p.jpg", JPEG, "image/jpeg")}
    )
    assert made.status_code == 200, made.text
    piece_id = made.json()["piece"]["id"]
    assert pub_client.get(f"/api/pieces/{piece_id}/photo", headers=B).status_code == 404
    assert pub_client.post(f"/api/pieces/{piece_id}/photo", headers=B, files={"photo": ("p.jpg", JPEG, "image/jpeg")}).status_code == 404
    assert pub_client.delete(f"/api/pieces/{piece_id}/photo", headers=B).status_code == 404
    assert pub_client.get(f"/api/pieces/{piece_id}/photo", headers=A).content == JPEG
    with tenant.use_owner(kit.BOB), Session(pub_engine) as s:
        assert s.exec(select(Piece)).all() == [] and s.exec(select(PiecePhoto)).all() == []
