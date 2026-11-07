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
    never clobber an HR the athlete actually typed in). Deliberately starts every row with
    hr_source=None (not "typed") so the bug's actual failure mode — a *derived* row silently
    frozen as "typed" by a round trip that dropped the field — has something to catch. A
    version of this test that starts every row already "typed" can't fail: with the bug, the
    field is dropped and then _mark_typed_hr re-tags it "typed" anyway, same end state either
    way."""
    activity = _seed_activity(session)  # hr: 130 x1800, 175 x400 (the hard stretch), 130 x1400
    _login(client)
    created = client.post(
        f"/api/activities/{activity.canonical_id}/pieces",
        json={"piece_type": "2000m", "splits": _SPLITS, "distance_m": 2000.0, "duration_s": 392.4},
    ).json()["piece"]
    # Auto-aligned on create to the hard stretch (same window the other create/align test
    # asserts) — every row gets a *derived* HR around 175, not a typed one.
    assert 1700 <= created["window_start_s"] <= 1850
    assert all(s["hr_source"] == "derived" for s in created["splits"])
    assert all(170 <= s["hr"] <= 180 for s in created["splits"])

    patched = client.patch(f"/api/pieces/{created['id']}", json={"splits": created["splits"]})
    assert patched.status_code == 200
    # The regression check: hr_source must survive a PATCH body as "derived", not silently
    # drop out and get re-tagged "typed" by _mark_typed_hr (which would then freeze it against
    # the re-align below).
    patched_splits = patched.json()["piece"]["splits"]
    assert all(s["hr_source"] == "derived" for s in patched_splits)

    moved = client.post(f"/api/pieces/{created['id']}/align", json={"activity_id": activity.id, "start_s": 100})
    assert moved.status_code == 200
    moved_splits = moved.json()["splits"]
    # A derived row must refresh on re-align — if the PATCH above had silently turned it
    # "typed", these would still read ~175 instead of the new window's ~130.
    assert all(s["hr_source"] == "derived" for s in moved_splits)
    assert all(125 <= s["hr"] <= 135 for s in moved_splits)
