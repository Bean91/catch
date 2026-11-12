from __future__ import annotations

from datetime import timedelta

from conftest import TEST_PASSWORD

from catch.analytics.planning import week_start
from catch.sync import planning as sp
from catch.sync import workout_library as lib

MON = week_start(sp.today())
TPL = {"name": "6x3", "workout_type": "erg_intervals", "target_zone": "AT", "structure": {"blocks": [{"reps": 6, "work_s": 180, "rest_s": 120, "zone": "AT"}]}}


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _d(offset):
    return (MON + timedelta(days=offset)).isoformat()


def test_every_route_requires_the_login_cookie(client):
    for method, path in (
        ("get", "/api/library/templates"), ("post", "/api/library/templates"), ("post", "/api/library/templates/preview"),
        ("get", "/api/library/templates/1"), ("patch", "/api/library/templates/1"), ("post", "/api/library/templates/1/duplicate"),
        ("post", "/api/library/templates/1/archive"), ("post", "/api/library/templates/1/unarchive"), ("post", "/api/library/templates/1/schedule"),
    ):
        assert getattr(client, method)(path).status_code == 401, path


def test_lifecycle_create_duplicate_edit_archive_schedule(client):
    _login(client)
    res = client.post("/api/library/templates", json=TPL)
    assert res.status_code == 200
    t = res.json()
    assert t["summary"]["total_duration_s"] == 6 * 180 + 5 * 120 and t["signature"] == "6x180s/r120"
    copy = client.post(f"/api/library/templates/{t['id']}/duplicate", json={"name": "6x3 copy"}).json()
    assert copy["id"] != t["id"] and copy["duplicated_from_id"] == t["id"]
    assert client.patch(f"/api/library/templates/{copy['id']}", json={"difficulty": "hard"}).json()["difficulty"] == "hard"
    sched = client.post(f"/api/library/templates/{t['id']}/schedule", json={"date": _d(1), "start_time": "06:30", "repeat": {"weekdays": [1, 3], "count": 3}})
    assert sched.status_code == 200
    planned = sched.json()["planned"]
    assert len(planned) == 3 and all(p["template_id"] == t["id"] and p["duration_min"] == 28.0 for p in planned)
    cal = client.get(f"/api/calendar?from={_d(0)}&to={_d(13)}").json()
    assert sum(1 for d in cal["days"] for p in d["planned"] if p["template_id"] == t["id"]) == 3
    assert client.post(f"/api/library/templates/{t['id']}/archive").json()["archived"] is True
    assert [x["id"] for x in client.get("/api/library/templates?scope=archived").json()["templates"]] == [t["id"]]
    assert client.get("/api/library/templates").json()["templates"][0]["id"] == copy["id"]
    assert client.post(f"/api/library/templates/{t['id']}/schedule", json={"date": _d(1)}).status_code == 422
    assert client.post(f"/api/library/templates/{t['id']}/unarchive").json()["archived"] is False


def test_preview_validates_and_computes_without_saving(client):
    _login(client)
    ok = client.post("/api/library/templates/preview", json=TPL).json()
    assert ok["ok"] and ok["summary"]["rest_duration_s"] == 600 and ok["planned"]["duration_min"] == 28.0
    bad = client.post("/api/library/templates/preview", json={"name": "x", "workout_type": "rate_ladder", "structure": {"blocks": []}}).json()
    assert not bad["ok"] and bad["issues"][0]["path"] and bad["summary"] is None
    assert client.get("/api/library/templates?scope=mine").json()["templates"] == []


def test_validation_and_unknown_ids(client):
    _login(client)
    assert client.post("/api/library/templates", json={"name": "x", "workout_type": "nope"}).status_code == 422
    assert client.post("/api/library/templates", json={**TPL, "owner_id": "x"}).status_code == 422
    assert client.get("/api/library/templates/999").status_code == 404
    assert client.patch("/api/library/templates/999", json={"name": "x"}).status_code == 404
    assert client.get("/api/library/templates?scope=bogus").status_code == 422


def test_examples_are_read_only_and_scoped(client, session):
    _login(client)
    lib.seed_examples(session)
    assert client.get("/api/library/templates").json()["templates"] == []
    ex = client.get("/api/library/templates?scope=examples").json()["templates"]
    assert ex and all(t["is_example"] and t["example_label"] for t in ex)
    assert client.patch(f"/api/library/templates/{ex[0]['id']}", json={"name": "x"}).status_code == 422
    assert client.post(f"/api/library/templates/{ex[0]['id']}/duplicate").json()["is_example"] is False
    assert len(client.get("/api/library/templates?scope=all").json()["templates"]) == len(ex) + 1


def test_a_coach_token_is_rejected_by_every_library_route(client, session):
    from catch.api.deps import hash_token
    from catch.core.models import ApiToken

    session.add(ApiToken(name="c", token_hash=hash_token("coach-secret"), role="coach", display_name="Sam"))
    session.commit()
    h = {"Authorization": "Bearer coach-secret"}
    assert client.get("/api/library/templates", headers=h).status_code == 401
    assert client.post("/api/library/templates", json=TPL, headers=h).status_code == 401
