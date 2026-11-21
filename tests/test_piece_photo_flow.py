"""Session 33, Part D: the piece-from-a-photo flow end to end through the API.

The bugs these reproduce (each fails on the session 32 code): a photo whose PM5 screen shows only totals produced `splits: []`,
which the create route refused with 422, so the piece could never be saved; the piece and its photo were two requests, so an
upload failure after the create left a saved piece the app reported as "couldn't save" (a retry duplicated it); and a failure
in the post-save alignment/rescoring turned a committed piece into a 500."""

from __future__ import annotations

import json

import pytest
from sqlmodel import select

from catch.core.models import Piece, PiecePhoto
from catch.sync import piece as piece_sync
from test_api_pieces import _SPLITS, _login, _seed_activity

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2048
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _count(session, model) -> int:
    session.expire_all()
    return len(session.exec(select(model)).all())


def _with_photo(client, canonical_id, payload: dict, data: bytes = JPEG, content_type: str = "image/jpeg"):
    return client.post(
        f"/api/activities/{canonical_id}/pieces/with-photo",
        data={"payload": json.dumps(payload)},
        files={"photo": ("pm5.jpg", data, content_type)},
    )


def test_a_totals_only_piece_can_be_saved(client, session):
    """A PM5 photo with no splits table: the estimate has totals and no rows. It used to be impossible to save."""
    activity = _seed_activity(session)
    _login(client)
    resp = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": [], "distance_m": 2000.0, "duration_s": 392.4, "source": "photo", "avg_rate": 31},
    )
    assert resp.status_code == 200, resp.text
    piece = resp.json()["piece"]
    assert piece["distance_m"] == 2000.0 and piece["duration_s"] == 392.4
    assert piece["avg_split_s"] == pytest.approx(98.1)
    assert piece["avg_rate"] == 31
    assert len(piece["splits"]) == 1 and piece["splits"][0]["split_s"] == 392.4


def test_no_splits_and_no_totals_is_refused_with_a_sentence(client, session):
    activity = _seed_activity(session)
    _login(client)
    resp = client.post(f"/api/activities/{activity.canonical_id}/pieces", json={"piece_type": "custom", "splits": []})
    assert resp.status_code == 422
    assert "total distance or time" in resp.json()["detail"]
    assert _count(session, Piece) == 0


def test_piece_and_photo_are_saved_together(client, session):
    activity = _seed_activity(session)
    _login(client)
    resp = _with_photo(client, activity.canonical_id, {"piece_type": "2000m", "splits": _SPLITS, "distance_m": 2000.0, "duration_s": 392.4, "source": "photo", "drag_factor": 118})
    assert resp.status_code == 200, resp.text
    piece = resp.json()["piece"]
    assert piece["has_photo"] is True and piece["drag_factor"] == 118
    photo = client.get(f"/api/pieces/{piece['id']}/photo")
    assert photo.status_code == 200 and photo.content == JPEG
    assert client.get(f"/api/activities/{activity.canonical_id}/pieces").json()["pieces"][0]["has_photo"] is True


@pytest.mark.parametrize(
    ("data", "content_type", "status"),
    [
        (b"GIF89a" + b"0" * 64, "image/gif", 422),  # type not allowed
        (b"not really a jpeg", "image/jpeg", 422),  # magic bytes don't match the declared type
        (PNG_BYTES, "image/jpeg", 422),  # a PNG claiming to be a JPEG
        (b"", "image/jpeg", 422),
        (b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024), "image/jpeg", 413),  # over 5 MB, under the 6 MB stream cap
    ],
)
def test_a_bad_photo_saves_nothing(client, session, data, content_type, status):
    activity = _seed_activity(session)
    _login(client)
    resp = _with_photo(client, activity.canonical_id, {"piece_type": "2000m", "splits": _SPLITS}, data, content_type)
    assert resp.status_code == status
    assert _count(session, Piece) == 0 and _count(session, PiecePhoto) == 0


def test_a_request_over_the_stream_cap_is_refused_before_parsing(client, session):
    activity = _seed_activity(session)
    _login(client)
    resp = _with_photo(client, activity.canonical_id, {"piece_type": "2000m", "splits": _SPLITS}, b"\xff\xd8\xff" + b"0" * (7 * 1024 * 1024))
    assert resp.status_code == 413
    assert _count(session, Piece) == 0


def test_unreadable_payload_saves_nothing(client, session):
    activity = _seed_activity(session)
    _login(client)
    resp = client.post(
        f"/api/activities/{activity.canonical_id}/pieces/with-photo",
        data={"payload": "{not json"},
        files={"photo": ("pm5.jpg", JPEG, "image/jpeg")},
    )
    assert resp.status_code == 422
    assert _count(session, Piece) == 0


def test_a_database_failure_while_saving_the_photo_leaves_no_piece(session, monkeypatch):
    activity = _seed_activity(session)
    real_commit = session.commit
    calls = {"n": 0}

    def failing_commit():
        calls["n"] += 1
        raise RuntimeError("database went away")

    monkeypatch.setattr(session, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        piece_sync.create_piece(session, activity.canonical_id, "2000m", [dict(r) for r in _SPLITS], photo=(JPEG, "image/jpeg"))
    monkeypatch.setattr(session, "commit", real_commit)
    assert calls["n"] == 1
    assert _count(session, Piece) == 0 and _count(session, PiecePhoto) == 0


def test_a_failure_after_saving_still_returns_the_saved_piece(client, session, monkeypatch):
    """Alignment/rescoring run after the commit. A bug there used to 500 a piece that was already saved."""
    activity = _seed_activity(session)
    _login(client)

    def boom(*_a, **_k):
        raise RuntimeError("alignment bug")

    monkeypatch.setattr(piece_sync, "_auto_align", boom)
    resp = _with_photo(client, activity.canonical_id, {"piece_type": "2000m", "splits": _SPLITS, "distance_m": 2000.0, "duration_s": 392.4})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["piece"]["has_photo"] is True
    assert body["validation"]["warnings"]
    assert _count(session, Piece) == 1 and _count(session, PiecePhoto) == 1


def test_replace_and_remove_a_photo_on_an_existing_piece(client, session):
    activity = _seed_activity(session)
    _login(client)
    piece = client.post(
        f"/api/activities/{activity.canonical_id}/pieces", json={"piece_type": "2000m", "splits": _SPLITS, "distance_m": 2000.0, "duration_s": 392.4}
    ).json()["piece"]
    assert piece["has_photo"] is False

    first = client.post(f"/api/pieces/{piece['id']}/photo", files={"photo": ("a.jpg", JPEG, "image/jpeg")})
    assert first.status_code == 200 and first.json()["piece"]["has_photo"] is True
    second = client.post(f"/api/pieces/{piece['id']}/photo", files={"photo": ("b.png", PNG_BYTES, "image/png")})
    assert second.status_code == 200
    fetched = client.get(f"/api/pieces/{piece['id']}/photo")
    assert fetched.content == PNG_BYTES and fetched.headers["content-type"] == "image/png"
    assert _count(session, PiecePhoto) == 1

    removed = client.delete(f"/api/pieces/{piece['id']}/photo")
    assert removed.status_code == 200 and removed.json()["piece"]["has_photo"] is False
    assert client.get(f"/api/pieces/{piece['id']}/photo").status_code == 404


def test_uploading_to_a_missing_piece_is_404(client, session):
    _login(client)
    assert client.post("/api/pieces/9999/photo", files={"photo": ("a.jpg", JPEG, "image/jpeg")}).status_code == 404


def test_photo_estimate_route_validates_and_passes_the_modality(client, session, monkeypatch):
    activity = _seed_activity(session)
    _login(client)
    seen = {}

    async def fake_estimate(db, image_bytes, media_type, owner_id=None, *, modality="rowing_erg"):
        seen.update(bytes=image_bytes, modality=modality)
        return {"splits": [], "distance_m": 5000, "duration_s": 1200.0, "detected_piece_type": "5000m", "modality": modality}

    import catch.api.routes_pieces as routes

    monkeypatch.setattr(routes, "estimate_piece_photo", fake_estimate)
    bad = client.post(f"/api/activities/{activity.canonical_id}/pieces/photo-estimate", files={"photo": ("a.jpg", b"nope", "image/jpeg")})
    assert bad.status_code == 422
    ok = client.post(
        f"/api/activities/{activity.canonical_id}/pieces/photo-estimate", data={"modality": "rowing_erg"}, files={"photo": ("a.jpg", JPEG, "image/jpeg")}
    )
    assert ok.status_code == 200 and ok.json()["detected_piece_type"] == "5000m"
    assert seen == {"bytes": JPEG, "modality": "rowing_erg"}
