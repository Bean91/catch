"""Session 36: the built-in workout examples on the public deployment are one shared, ownerless set. Before this session every
lookup insisted on `owner_id == owner`, so no account could list, open, duplicate or schedule them."""

from __future__ import annotations

from datetime import date, timedelta

from sqlmodel import Session

from catch.core import tenant
from catch.sync.workout_library import seed_examples
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

A, B = bearer(kit.ALICE), bearer(kit.BOB)


def test_shared_examples_are_readable_but_never_shared_writes(pub_client, pub_engine):
    with tenant.system(), Session(pub_engine) as s:
        assert seed_examples(s) > 0

    examples = pub_client.get("/api/library/templates", params={"scope": "examples"}, headers=A).json()["templates"]
    assert examples, "examples must list on the public build"
    ex = examples[0]
    assert ex["can_archive"] is False

    assert pub_client.get(f"/api/library/templates/{ex['id']}", headers=B).status_code == 200
    # Archiving one row that serves everyone is refused; editing an example is refused as before.
    assert pub_client.post(f"/api/library/templates/{ex['id']}/archive", headers=A).status_code == 422
    assert pub_client.patch(f"/api/library/templates/{ex['id']}", json={"name": "x"}, headers=A).status_code == 422

    copy = pub_client.post(f"/api/library/templates/{ex['id']}/duplicate", json={}, headers=A).json()
    assert copy["is_example"] is False
    # Alice's copy is hers alone.
    assert pub_client.get(f"/api/library/templates/{copy['id']}", headers=B).status_code == 404
    mine_b = pub_client.get("/api/library/templates", params={"scope": "mine"}, headers=B).json()["templates"]
    assert all(t["id"] != copy["id"] for t in mine_b)

    day = (date.today() + timedelta(days=2)).isoformat()
    sched = pub_client.post(f"/api/library/templates/{ex['id']}/schedule", json={"date": day, "confirm": True}, headers=A)
    assert sched.status_code == 200, sched.text
