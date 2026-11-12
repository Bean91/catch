from __future__ import annotations

from conftest import TEST_PASSWORD

from catch.api.deps import hash_token
from catch.core.models import ApiToken
from catch.core.principal import coach_principal
from catch.sync import coaching_notes as cn

SECRET = "SECRET-PRIVATE-TEXT"


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _coach_feedback(session, **kw):
    return cn.create_feedback(session, "owner", coach_principal(1, "Coach Sam"), {"text": "Hands before body", "date": "2026-11-02", **kw})


def test_every_route_requires_the_login_cookie(client):
    for method, path in (
        ("get", "/api/technique-notes"), ("post", "/api/technique-notes"), ("patch", "/api/technique-notes/1"), ("delete", "/api/technique-notes/1"),
        ("get", "/api/coach-feedback"), ("get", "/api/coach-feedback/coaches"), ("post", "/api/coach-feedback"), ("patch", "/api/coach-feedback/1"),
        ("post", "/api/coach-feedback/1/response"), ("get", "/api/coach-feedback/1/history"), ("delete", "/api/coach-feedback/1"),
    ):
        assert getattr(client, method)(path).status_code == 401, path


def test_a_coach_token_cannot_use_the_cookie_only_routes(client, session):
    session.add(ApiToken(name="c", token_hash=hash_token("coach-secret"), role="coach", display_name="Sam"))
    session.commit()
    h = {"Authorization": "Bearer coach-secret"}
    assert client.get("/api/coach-feedback", headers=h).status_code == 401
    assert client.get("/api/technique-notes", headers=h).status_code == 401


def test_technique_note_lifecycle_and_privacy_default(client):
    _login(client)
    res = client.post("/api/technique-notes", json={"category": "catch", "text": "Early arms", "date": "2026-11-02"})
    assert res.status_code == 200
    n = res.json()
    assert n["visibility"] == "private" and n["shared_with_coach"] is False and n["date"] == "2026-11-02"
    assert client.patch(f"/api/technique-notes/{n['id']}", json={"visibility": "coach"}).json()["shared_with_coach"] is True
    assert [x["id"] for x in client.get("/api/technique-notes?category=catch").json()["notes"]] == [n["id"]]
    assert client.delete(f"/api/technique-notes/{n['id']}").json() == {"ok": True}
    assert client.get("/api/technique-notes").json()["notes"] == []


def test_technique_note_errors(client):
    _login(client)
    assert client.post("/api/technique-notes", json={"category": "speed", "text": "x"}).status_code == 422
    assert client.post("/api/technique-notes", json={"category": "catch", "text": "x", "canonical_id": 999}).status_code == 404
    assert client.patch("/api/technique-notes/999", json={"text": "x"}).status_code == 404
    assert client.get("/api/technique-notes?category=nope").status_code == 422


def test_feedback_timeline_response_history_and_ownership(client, session):
    _login(client)
    fb = _coach_feedback(session, focus_areas=["catch"])
    listing = client.get("/api/coach-feedback").json()
    entry = listing["feedback"][0]
    assert entry["author"]["role"] == "coach" and entry["can_edit"] is False and entry["can_respond"] is True and listing["coaches"] == ["Coach Sam"]
    assert client.patch(f"/api/coach-feedback/{fb.id}", json={"text": "tampered"}).status_code == 403
    assert client.delete(f"/api/coach-feedback/{fb.id}").status_code == 403
    resp = client.post(f"/api/coach-feedback/{fb.id}/response", json={"response": "Will do"}).json()
    assert resp["athlete_response"] == "Will do"
    cn.update_feedback(session, "owner", coach_principal(1, "Coach Sam"), fb.id, {"text": "Hands, then body"})
    hist = client.get(f"/api/coach-feedback/{fb.id}/history").json()["history"]
    assert [h["kind"] for h in hist] == ["response", "edit"] and hist[1]["text"] == "Hands before body"
    assert client.get("/api/coach-feedback?coach=sam&category=catch").json()["feedback"][0]["edited"] is True
    assert client.get("/api/coach-feedback?coach=lee").json()["feedback"] == []


def test_athlete_logs_and_edits_their_own_feedback(client):
    _login(client)
    made = client.post("/api/coach-feedback", json={"text": "Sit up", "coach_name": "Kim", "focus_areas": ["posture"], "date": "2026-11-03"}).json()
    assert made["author"]["role"] == "athlete" and made["can_edit"] is True and made["created_via"] == "web" and made["shared"] is True
    edited = client.patch(f"/api/coach-feedback/{made['id']}", json={"visibility": "private"}).json()
    assert edited["visibility"] == "private" and edited["edited"] is True
    assert client.delete(f"/api/coach-feedback/{made['id']}").json() == {"ok": True}
    assert client.get(f"/api/coach-feedback/{made['id']}/history").status_code == 404


def test_feedback_errors_and_route_order(client):
    _login(client)
    assert client.post("/api/coach-feedback", json={"text": ""}).status_code == 422
    assert client.post("/api/coach-feedback", json={"text": "x", "focus_areas": ["nope"]}).status_code == 422
    assert client.patch("/api/coach-feedback/999", json={"text": "x"}).status_code == 404
    assert client.get("/api/coach-feedback/coaches").json() == {"coaches": []}  # not swallowed by /{id}


def test_private_feedback_text_is_athlete_only_in_the_api(client, session):
    _login(client)
    made = client.post("/api/coach-feedback", json={"text": SECRET, "visibility": "private"}).json()
    assert made["visibility"] == "private"
    assert SECRET in client.get("/api/coach-feedback").text
