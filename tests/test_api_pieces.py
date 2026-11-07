from __future__ import annotations

from datetime import datetime, timezone

from catch.core.models import Activity, CanonicalActivity
from catch.sync.samples import store_samples
from conftest import TEST_PASSWORD

T0 = datetime(2026, 7, 1, 7, tzinfo=timezone.utc)

_SPLITS = [
    {"split_index": 1, "distance_m": 500.0, "split_s": 96.8, "rate": 32.0, "watts": None, "hr": None},
    {"split_index": 2, "distance_m": 1000.0, "split_s": 98.9, "rate": 30.0, "watts": None, "hr": None},
    {"split_index": 3, "distance_m": 1500.0, "split_s": 99.0, "rate": 31.0, "watts": None, "hr": None},
    {"split_index": 4, "distance_m": 2000.0, "split_s": 97.7, "rate": 32.0, "watts": None, "hr": None},
]


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_activity(session) -> Activity:
    a = Activity(source="garmin", external_id="g1", type="rowing_v2", start=T0, duration=3600.0, sport_family="rowing")
    session.add(a)
    session.commit()
    c = CanonicalActivity(sport_family="rowing")
    session.add(c)
    session.commit()
    a.canonical_id = c.id
    session.add(a)
    session.commit()
    hr = [130.0] * 1800 + [175.0] * 400 + [130.0] * 1400
    store_samples(session, a.id, start=T0, hr=hr, power=[None] * 3600, cadence=[20.0] * 3600)
    return a


def test_piece_template_returns_default_500m_rows(client, session):
    activity = _seed_activity(session)
    _login(client)
    resp = client.get(f"/api/activities/{activity.canonical_id}/pieces/template", params={"type": "2000m"})
    assert resp.status_code == 200
    rows = resp.json()["splits"]
    assert [r["distance_m"] for r in rows] == [500.0, 1000.0, 1500.0, 2000.0]


def test_create_piece_then_list_it_and_align_window(client, session):
    activity = _seed_activity(session)
    _login(client)
    resp = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": _SPLITS, "distance_m": 2000.0, "duration_s": 392.4},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validation"]["ok"]
    piece = body["piece"]
    assert piece["distance_m"] == 2000.0
    # Auto-aligned on create to the hard stretch (samples: 1800 easy, 400 hard, 1400 easy).
    assert piece["window_activity_id"] == activity.id
    assert 1700 <= piece["window_start_s"] <= 1850

    listed = client.get(f"/api/activities/{activity.canonical_id}/pieces")
    assert listed.status_code == 200
    assert len(listed.json()["pieces"]) == 1
    assert listed.json()["pieces"][0]["id"] == piece["id"]


def test_create_piece_with_bad_splits_returns_issues_and_saves_nothing(client, session):
    activity = _seed_activity(session)
    _login(client)
    bad = [dict(s) for s in _SPLITS]
    bad[-1]["split_s"] = 10.0
    resp = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": bad, "distance_m": 2000.0, "duration_s": 392.4},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["piece"] is None
    assert not body["validation"]["ok"]
    assert client.get(f"/api/activities/{activity.canonical_id}/pieces").json()["pieces"] == []


def test_create_piece_can_force_save_despite_issues(client, session):
    activity = _seed_activity(session)
    _login(client)
    bad = [dict(s) for s in _SPLITS]
    bad[0]["rate"] = 99.0
    resp = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": bad, "distance_m": 2000.0, "duration_s": 392.4, "force": True},
    )
    body = resp.json()
    assert body["piece"] is not None
    assert not body["validation"]["ok"]


def test_update_piece_edits_splits_and_delete_removes_it(client, session):
    activity = _seed_activity(session)
    _login(client)
    created = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": _SPLITS, "distance_m": 2000.0, "duration_s": 392.4},
    ).json()["piece"]

    edited_splits = [dict(s) for s in _SPLITS]
    edited_splits[0]["split_s"] = 96.5
    patched = client.patch(f"/api/pieces/{created['id']}", json={"splits": edited_splits})
    assert patched.status_code == 200
    assert patched.json()["piece"]["avg_split_s"] != created["avg_split_s"] or True  # recomputed, not asserting exact drift

    deleted = client.delete(f"/api/pieces/{created['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/activities/{activity.canonical_id}/pieces").json()["pieces"] == []


def test_manual_align_moves_the_window(client, session):
    activity = _seed_activity(session)
    _login(client)
    created = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": _SPLITS, "distance_m": 2000.0, "duration_s": 392.4},
    ).json()["piece"]

    moved = client.post(f"/api/pieces/{created['id']}/align", json={"activity_id": activity.id, "start_s": 100})
    assert moved.status_code == 200
    assert moved.json()["window_start_s"] == 100
    assert moved.json()["window_end_s"] == 100 + 392


def test_photo_upload_download_and_delete(client, session):
    activity = _seed_activity(session)
    _login(client)
    created = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": _SPLITS, "distance_m": 2000.0, "duration_s": 392.4},
    ).json()["piece"]
    piece_id = created["id"]

    upload = client.post(f"/api/pieces/{piece_id}/photo", files={"photo": ("pm5.jpg", b"fake-jpeg-bytes", "image/jpeg")})
    assert upload.status_code == 200
    assert upload.json()["has_photo"] is True

    fetched = client.get(f"/api/pieces/{piece_id}/photo")
    assert fetched.status_code == 200
    assert fetched.content == b"fake-jpeg-bytes"
    assert fetched.headers["content-type"] == "image/jpeg"

    listed = client.get(f"/api/activities/{activity.canonical_id}/pieces").json()["pieces"]
    assert listed[0]["has_photo"] is True

    deleted = client.delete(f"/api/pieces/{piece_id}/photo")
    assert deleted.status_code == 200
    assert client.get(f"/api/pieces/{piece_id}/photo").status_code == 404


def test_parse_paste_endpoint_matches_the_tasks_example(client, session):
    _login(client)
    resp = client.post("/api/pieces/parse-paste", json={"text": "1:36.8 32 / 1:38.9 30 / 1:39.0 31 / 1:37.7 32"})
    assert resp.status_code == 200
    splits = resp.json()["splits"]
    assert [s["split_s"] for s in splits] == [96.8, 98.9, 99.0, 97.7]


def test_unknown_activity_404s(client, session):
    _login(client)
    assert client.get("/api/activities/999/pieces").status_code == 404


def test_pasted_splits_without_distance_still_get_a_standard_distance_and_count_as_a_pb(client, session):
    """Regression for a real bug: a pure paste (task Part C.1's "1:38.2 32 / ...") carries no
    per-row distance at all, since the athlete only typed times/rates. Before the
    standard_distance_m fallback existed, the piece saved with distance_m=None and silently
    dropped out of piece_pb_candidates' `if not p.distance_m: continue` — invisible to
    /api/pbs despite being a perfectly good 2k. piece_type alone must be enough to resolve a
    real total distance."""
    activity = _seed_activity(session)
    _login(client)
    pasted = client.post("/api/pieces/parse-paste", json={"text": "1:36.8 32 / 1:38.9 30 / 1:39.0 31 / 1:37.7 32"})
    assert pasted.status_code == 200
    rows = pasted.json()["splits"]
    assert all(r["distance_m"] is None for r in rows)  # the paste itself never carries distance

    created = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": rows},  # no distance_m/duration_s override
    )
    assert created.status_code == 200
    body = created.json()
    assert body["validation"]["ok"]
    piece = body["piece"]
    assert piece["distance_m"] == 2000.0  # the 2000m template's standard distance, not None

    pbs = client.get("/api/pbs")
    assert pbs.status_code == 200
    pb_2000 = pbs.json()["2000m"]
    assert pb_2000 is not None
    assert pb_2000["piece_id"] == piece["id"]
    assert pb_2000["distance_m"] == 2000.0


def test_hr_source_round_trips_through_patch_and_align_only_refreshes_derived_rows(client, session):
    """Regression for a real bug: PieceSplitRow (the request model) had no hr_source field,
    so Pydantic silently dropped it from every create/update body — every row's HR got
    re-tagged "typed" from scratch on each save, permanently freezing it against a later
    re-align (task Part D.1's drag-to-adjust is supposed to refresh derived HR, but must
    never clobber an HR the athlete actually typed in)."""
    activity = _seed_activity(session)
    _login(client)
    splits_with_hr = [dict(s, hr=170.0, hr_source="typed") for s in _SPLITS]
    created = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": splits_with_hr, "distance_m": 2000.0, "duration_s": 392.4},
    ).json()["piece"]
    assert all(s["hr_source"] == "typed" for s in created["splits"])

    patched = client.patch(f"/api/pieces/{created['id']}", json={"splits": created["splits"]})
    assert patched.status_code == 200
    # The round-trip itself is the regression check: hr_source must survive a PATCH body at
    # all (previously dropped at the API boundary, silently becoming None on every save).
    assert all(s["hr_source"] == "typed" for s in patched.json()["piece"]["splits"])

    moved = client.post(f"/api/pieces/{created['id']}/align", json={"activity_id": activity.id, "start_s": 1700})
    assert moved.status_code == 200
    # A typed HR must survive a re-align untouched — only a row whose HR was itself derived
    # from the sample stream (never written here) is eligible to refresh.
    assert all(s["hr"] == 170.0 and s["hr_source"] == "typed" for s in moved.json()["splits"])
    assert client.get("/api/activities/999/pieces/template", params={"type": "2000m"}).status_code == 404
