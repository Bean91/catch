from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine, select

from catch.core import db as db_module
from catch.core.models import Activity, CanonicalActivity, DailyWellness, Piece, PieceInterval, Stroke
from catch.core.settings_store import update_settings
from catch.sync import piece as piece_sync
from catch.sync.canonical import resolve_canonical
from catch.sync.erg_test import list_tests
from catch.sync.piece_intervals import build_intervals_from_concept2, NoIntervalData
from catch.sync.samples import store_samples
from catch.sync.training_intelligence import gather_interval_comparisons
from conftest import TEST_PASSWORD

T0 = datetime(2026, 7, 1, 7, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "concept2" / "result_102_detail.json"


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed(session, *, start=T0) -> Activity:
    a = Activity(source="garmin", external_id=f"g{start.isoformat()}", type="rowing_v2", start=start, duration=3600.0, sport_family="rowing")
    session.add(a)
    session.commit()
    c = CanonicalActivity(sport_family="rowing", start=start)
    session.add(c)
    session.commit()
    a.canonical_id = c.id
    session.add(a)
    session.commit()
    store_samples(session, a.id, start=start, hr=[140.0] * 3600, power=[None] * 3600, cadence=[20.0] * 3600)
    return a


def _make(client, cid, body):
    return client.post(f"/api/activities/{cid}/pieces", json={"piece_type": "custom", **body})


def _repeat_body(**kw):
    return {"intervals": [{"target_type": "distance", "work_distance_m": 500, "rest_duration_s": 60 if i < 3 else None, **kw} for i in range(4)]}


def test_requires_auth(client, session):
    a = _seed(session)
    assert _make(client, a.canonical_id, _repeat_body()).status_code == 401
    assert client.get("/api/pieces/1").status_code == 401
    assert client.put("/api/pieces/1/intervals/order", json={"ids": []}).status_code == 401
    assert client.get("/api/training-intelligence/intervals").status_code == 401


def test_create_distance_intervals_and_fetch_with_parent(client, session):
    a = _seed(session)
    _login(client)
    resp = _make(client, a.canonical_id, _repeat_body(work_duration_s=105.0, avg_watts=250, avg_rate=32))
    assert resp.status_code == 200
    piece = resp.json()["piece"]
    assert piece["has_intervals"] and len(piece["intervals"]) == 4
    assert [i["position"] for i in piece["intervals"]] == [0, 1, 2, 3]
    assert piece["distance_m"] == 2000 and piece["duration_s"] == 420
    s = piece["interval_summary"]
    assert s["rest_duration_s"] == 180 and s["total_duration_s"] == 600 and s["avg_split_s"] == 105.0
    assert piece["interval_signature"] == "4x500m/r60"

    got = client.get(f"/api/pieces/{piece['id']}").json()
    assert got["intervals"] == piece["intervals"]
    assert client.get(f"/api/activities/{a.canonical_id}").json()["pieces"][0]["id"] == piece["id"]


def test_time_based_and_mixed_sequences(client, session):
    a = _seed(session)
    _login(client)
    body = {
        "intervals": [
            {"target_type": "time", "work_duration_s": 60, "rest_duration_s": 60},
            {"target_type": "distance", "work_distance_m": 1000, "work_duration_s": 220, "rest_duration_s": 120},
            {"target_type": "time", "work_duration_s": 300, "work_distance_m": 1200},
        ]
    }
    piece = _make(client, a.canonical_id, body).json()["piece"]
    assert [i["target_type"] for i in piece["intervals"]] == ["time", "distance", "time"]
    assert piece["interval_summary"]["work_duration_s"] == 580
    assert piece["intervals"][1]["split_s"] == 110.0  # derived, not stored
    assert piece["intervals"][0]["split_s"] is None


def test_invalid_intervals_are_soft_rejected_unless_forced(client, session):
    a = _seed(session)
    _login(client)
    bad = {"intervals": [{"target_type": "distance"}]}  # no target
    resp = _make(client, a.canonical_id, bad)
    assert resp.status_code == 200 and resp.json()["piece"] is None and not resp.json()["validation"]["ok"]
    assert session.exec(select(Piece)).all() == []
    saved = _make(client, a.canonical_id, {**bad, "force": True}).json()
    assert saved["piece"] is not None  # incomplete data saved, to be returned to later


def test_schema_rejects_negative_values(client, session):
    a = _seed(session)
    _login(client)
    assert _make(client, a.canonical_id, {"intervals": [{"target_type": "distance", "work_distance_m": -1}]}).status_code == 422
    assert _make(client, a.canonical_id, {"intervals": [{"target_type": "distance", "work_distance_m": 500, "avg_hr": -4}]}).status_code == 422


def test_edit_delete_and_reorder(client, session):
    a = _seed(session)
    _login(client)
    pid = _make(client, a.canonical_id, _repeat_body()).json()["piece"]["id"]
    ids = [i["id"] for i in client.get(f"/api/pieces/{pid}/intervals").json()["intervals"]]

    patched = client.patch(f"/api/pieces/intervals/{ids[1]}", json={"work_duration_s": 100.0, "avg_hr": 170})
    assert patched.status_code == 200 and patched.json()["saved"]
    assert patched.json()["piece"]["intervals"][1]["avg_hr"] == 170

    # an explicit null clears, an omitted key doesn't
    cleared = client.patch(f"/api/pieces/intervals/{ids[1]}", json={"avg_hr": None}).json()["piece"]["intervals"][1]
    assert cleared["avg_hr"] is None and cleared["work_duration_s"] == 100.0

    rev = client.put(f"/api/pieces/{pid}/intervals/order", json={"ids": list(reversed(ids))})
    assert rev.status_code == 200
    after = rev.json()["piece"]["intervals"]
    assert [i["position"] for i in after] == [0, 1, 2, 3]
    assert after[2]["work_duration_s"] == 100.0  # the edited one moved from position 1 to 2

    assert client.put(f"/api/pieces/{pid}/intervals/order", json={"ids": ids[:3]}).status_code == 422
    assert client.put(f"/api/pieces/{pid}/intervals/order", json={"ids": [ids[0]] * 4}).status_code == 422

    victim = after[0]["id"]
    deleted = client.delete(f"/api/pieces/intervals/{victim}").json()["piece"]
    assert [i["position"] for i in deleted["intervals"]] == [0, 1, 2]
    assert client.delete(f"/api/pieces/intervals/{victim}").status_code == 404
    assert client.patch("/api/pieces/intervals/99999", json={"avg_hr": 1}).status_code == 404


def test_update_validation_blocks_unless_forced(client, session):
    a = _seed(session)
    _login(client)
    piece = _make(client, a.canonical_id, _repeat_body()).json()["piece"]
    iid = piece["intervals"][0]["id"]
    bad = client.patch(f"/api/pieces/intervals/{iid}", json={"avg_hr": 150, "max_hr": 120}).json()
    assert not bad["saved"] and not bad["validation"]["ok"]
    assert client.get(f"/api/pieces/{piece['id']}").json()["intervals"][0]["avg_hr"] is None
    forced = client.patch(f"/api/pieces/intervals/{iid}", json={"avg_hr": 150, "max_hr": 120, "force": True}).json()
    assert forced["saved"]


def test_repeat_generator_extends_existing_and_template_endpoint(client, session):
    a = _seed(session)
    _login(client)
    tpl = client.get(f"/api/activities/{a.canonical_id}/pieces/interval-template", params={"count": 3, "distance_m": 500, "rest_s": 60}).json()
    assert [r["rest_duration_s"] for r in tpl["intervals"]] == [60, 60, None]
    assert client.get(f"/api/activities/{a.canonical_id}/pieces/interval-template", params={"count": 3}).status_code == 422

    pid = _make(client, a.canonical_id, _repeat_body()).json()["piece"]["id"]
    out = client.post(f"/api/pieces/{pid}/intervals", json={"repeat": {"count": 2, "work_distance_m": 250, "rest_duration_s": 30}}).json()
    rows = out["piece"]["intervals"]
    assert len(rows) == 6 and rows[3]["rest_duration_s"] == 30  # old last interval picked up the block's rest
    assert client.post(f"/api/pieces/{pid}/intervals", json={}).status_code == 422


def test_replace_keeps_ids_of_rows_that_send_them(client, session):
    a = _seed(session)
    _login(client)
    piece = _make(client, a.canonical_id, _repeat_body()).json()["piece"]
    keep = piece["intervals"][2]
    rows = [{"id": keep["id"], "target_type": "distance", "work_distance_m": 500, "avg_hr": 160}, {"target_type": "time", "work_duration_s": 60}]
    out = client.post(f"/api/pieces/{piece['id']}/intervals", json={"replace": rows}).json()["piece"]["intervals"]
    assert out[0]["id"] == keep["id"] and out[0]["avg_hr"] == 160 and out[0]["position"] == 0
    assert len(out) == 2


def test_replace_whole_set(client, session):
    a = _seed(session)
    _login(client)
    pid = _make(client, a.canonical_id, _repeat_body()).json()["piece"]["id"]
    rep = client.post(f"/api/pieces/{pid}/intervals", json={"replace": [{"target_type": "time", "work_duration_s": 300}]}).json()
    assert rep["saved"] and len(rep["piece"]["intervals"]) == 1 and rep["piece"]["distance_m"] is None


def test_splits_edit_and_align_refused_for_interval_piece(client, session):
    a = _seed(session)
    _login(client)
    pid = _make(client, a.canonical_id, _repeat_body()).json()["piece"]["id"]
    assert client.patch(f"/api/pieces/{pid}", json={"splits": []}).status_code == 422
    assert client.post(f"/api/pieces/{pid}/align").status_code == 422
    assert client.patch(f"/api/pieces/{pid}", json={"notes": "felt good"}).status_code == 200


def test_delete_piece_removes_intervals(client, session):
    a = _seed(session)
    _login(client)
    pid = _make(client, a.canonical_id, _repeat_body()).json()["piece"]["id"]
    assert client.delete(f"/api/pieces/{pid}").status_code == 200
    assert session.exec(select(PieceInterval)).all() == []


def test_plain_piece_without_intervals_is_unchanged(client, session):
    a = _seed(session)
    _login(client)
    splits = [{"split_index": i + 1, "distance_m": 500.0 * (i + 1), "split_s": 98.0, "rate": 30.0, "watts": None, "hr": None} for i in range(4)]
    resp = client.post(f"/api/activities/{a.canonical_id}/pieces", json={"piece_type": "2000m", "splits": splits, "distance_m": 2000.0, "duration_s": 392.0})
    piece = resp.json()["piece"]
    assert piece["has_intervals"] is False and piece["intervals"] == [] and piece["interval_summary"] is None
    assert len(piece["splits"]) == 4
    assert client.post(f"/api/activities/{a.canonical_id}/pieces", json={"piece_type": "2000m"}).status_code == 422


# --- No double counting / exclusion from single-effort analytics -----------------------------


def test_interval_piece_does_not_change_parent_strain_or_totals(session):
    a = _seed(session)
    update_settings(session, {"max_hr": 190})
    session.add(DailyWellness(date=T0.date(), resting_hr=55))
    session.commit()
    before = resolve_canonical(session, a.canonical_id)
    snapshot = (before.strain_trimp, before.duration, before.distance, before.zones_json, before.session_label)

    from catch.sync.piece_intervals import create_interval_piece

    rows = [{"target_type": "distance", "work_distance_m": 500, "work_duration_s": 90, "avg_watts": 400, "rest_duration_s": 60} for _ in range(4)]
    piece, _ = create_interval_piece(session, a.canonical_id, rows)
    assert piece is not None

    after = resolve_canonical(session, a.canonical_id)
    assert (after.strain_trimp, after.duration, after.distance, after.zones_json, after.session_label) == snapshot


def test_interval_piece_excluded_from_single_effort_analytics(session):
    a = _seed(session)
    from catch.sync.piece_intervals import create_interval_piece

    rows = [{"target_type": "distance", "work_distance_m": 1000, "work_duration_s": 220, "rest_duration_s": 120} for _ in range(2)]
    piece, _ = create_interval_piece(session, a.canonical_id, rows, piece_type="1000m")
    assert piece.distance_m == 2000 and piece.has_intervals
    assert list_tests(session) == []
    assert piece_sync.piece_pb_candidates(session) == []
    assert piece_sync.confirmed_piece_pace_candidates(session, datetime(2020, 1, 1, tzinfo=timezone.utc)) == []
    assert piece_sync.absorb_concept2_piece_results(session) == 0


def test_last_interval_deleted_stops_reporting_work_totals(client, session):
    a = _seed(session)
    _login(client)
    piece = _make(client, a.canonical_id, {"intervals": [{"target_type": "distance", "work_distance_m": 2000, "work_duration_s": 420}]}).json()["piece"]
    out = client.delete(f"/api/pieces/intervals/{piece['intervals'][0]['id']}").json()["piece"]
    assert out["has_intervals"] is False and out["distance_m"] is None
    assert piece_sync.piece_pb_candidates(session) == []


def test_interval_comparison_groups_by_structure(session):
    from catch.sync.piece_intervals import create_interval_piece

    base = datetime.now(timezone.utc) - timedelta(days=10)
    for n, dur in enumerate([105.0, 103.0, 101.0]):
        a = _seed(session, start=base + timedelta(days=n * 3))
        rows = [{"target_type": "distance", "work_distance_m": 500, "work_duration_s": dur, "rest_duration_s": 60 if i < 3 else None} for i in range(4)]
        create_interval_piece(session, a.canonical_id, rows)
    other = _seed(session, start=base + timedelta(days=9))
    create_interval_piece(session, other.canonical_id, [{"target_type": "time", "work_duration_s": 60, "work_distance_m": 250}] * 2)

    from catch.core.settings_store import get_settings

    result = gather_interval_comparisons(session, get_settings(session))
    by = {b["bucket_label"]: b for b in result["buckets"]}
    assert by["4x500m/r60"]["n_points"] == 3
    assert by["4x500m/r60"]["best"]["value"] == 101.0 and by["4x500m/r60"]["recent"]["value"] == 101.0
    assert by["2x60s/r0"]["n_points"] == 1 and by["2x60s/r0"]["note"]


# --- Concept2 on-demand import -----------------------------------------------------------------


def _concept2_member(session, with_intervals=True):
    a = _seed(session)
    detail = json.loads(FIXTURE.read_text())["data"]
    c2 = Activity(
        source="concept2",
        external_id="102",
        type="rowing",
        start=T0,
        duration=600.0,
        sport_family="rowing",
        canonical_id=a.canonical_id,
        intervals_json=json.dumps(detail["workout"]) if with_intervals else None,
    )
    session.add(c2)
    session.commit()
    for seq, (t, hr, idx) in enumerate([(0, 160, 0), (52.5, 168, 0), (105.0, 172, 0), (0, 170, 1), (52.5, 175, 1), (105.0, 178, 1)]):
        session.add(Stroke(activity_id=c2.id, seq=seq, interval_index=idx, t=t, distance=t, hr=hr, watts=200.0 + idx * 10, stroke_rate=32.0))
    session.commit()
    return a, c2


def test_concept2_import_maps_real_interval_data(client, session):
    a, c2 = _concept2_member(session)
    _login(client)
    assert client.get(f"/api/activities/{a.canonical_id}").json()["concept2_interval_activity_id"] == c2.id
    resp = client.post(f"/api/activities/{a.canonical_id}/pieces/from-concept2", json={"activity_id": c2.id})
    assert resp.status_code == 200
    piece = resp.json()["piece"]
    assert piece["source"] == "concept2" and piece["concept2_activity_id"] == c2.id
    rows = piece["intervals"]
    assert len(rows) == 4 and all(r["source"] == "concept2" for r in rows)
    assert rows[0]["work_distance_m"] == 500 and rows[0]["work_duration_s"] == 105.0 and rows[0]["rest_duration_s"] == 60.0
    assert rows[0]["avg_rate"] == 32.0 and rows[0]["max_hr"] == 172 and rows[0]["avg_watts"] == 200.0
    assert rows[1]["avg_watts"] == 210.0
    assert rows[2]["avg_watts"] is None and rows[2]["max_hr"] is None  # no strokes for that interval: nothing invented
    assert piece["interval_summary"]["rest_duration_s"] == 240

    again = client.post(f"/api/activities/{a.canonical_id}/pieces/from-concept2", json={"activity_id": c2.id}).json()["piece"]
    assert again["id"] == piece["id"] and len(again["intervals"]) == 4  # idempotent
    assert len(session.exec(select(Piece)).all()) == 1


def test_concept2_import_without_interval_data_is_refused(client, session):
    a, c2 = _concept2_member(session, with_intervals=False)
    _login(client)
    assert client.get(f"/api/activities/{a.canonical_id}").json()["concept2_interval_activity_id"] is None
    resp = client.post(f"/api/activities/{a.canonical_id}/pieces/from-concept2", json={"activity_id": c2.id})
    assert resp.status_code == 422
    assert session.exec(select(Piece)).all() == []
    import pytest

    with pytest.raises(NoIntervalData):
        build_intervals_from_concept2(session, a.canonical_id, c2.id)


def test_concept2_import_rejects_foreign_activity(client, session):
    a, c2 = _concept2_member(session)
    other = _seed(session, start=T0 + timedelta(days=2))
    _login(client)
    assert client.post(f"/api/activities/{other.canonical_id}/pieces/from-concept2", json={"activity_id": c2.id}).status_code == 422
    assert client.post("/api/activities/9999/pieces/from-concept2", json={"activity_id": c2.id}).status_code == 404


# --- Coach tool ---------------------------------------------------------------------------------


def test_coach_add_piece_repeat_previews_then_saves(session):
    from catch.coach.tools import call_tool

    a = _seed(session)
    args = {"piece_type": "custom", "canonical_id": a.canonical_id, "repeat": {"count": 4, "distance_m": 500, "rest_s": 60}}
    preview = call_tool(session, "add_piece", args)
    assert preview["saved"] is False and preview["summary"]["count"] == 4 and session.exec(select(Piece)).all() == []
    saved = call_tool(session, "add_piece", {**args, "confirm": True})
    assert saved["saved"] and saved["piece"]["interval_signature"] == "4x500m/r60"
    assert call_tool(session, "get_interval_comparisons", {})["buckets"][0]["bucket_label"] == "4x500m/r60"


# --- Migration ----------------------------------------------------------------------------------


def test_migration_adds_has_intervals_to_a_pre_existing_pieces_table(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.exec_driver_sql("DROP TABLE piece_intervals")
        conn.exec_driver_sql("DROP TABLE piece_photos")
        conn.exec_driver_sql("DROP TABLE pieces")
        conn.exec_driver_sql(
            "CREATE TABLE pieces (id INTEGER PRIMARY KEY, canonical_id INTEGER, piece_type TEXT, splits_json TEXT, source TEXT, created_at TEXT, updated_at TEXT)"
        )
        conn.exec_driver_sql("INSERT INTO pieces (id, canonical_id, piece_type, splits_json, source) VALUES (1, 1, '2000m', '[{\"split_s\": 98}]', 'manual')")
        conn.commit()
    monkeypatch.setattr(db_module, "engine", eng)
    db_module._migrate_columns()
    with eng.connect() as conn:
        row = conn.exec_driver_sql("SELECT splits_json, has_intervals FROM pieces WHERE id = 1").one()
    assert row[0] == '[{"split_s": 98}]' and row[1] == 0
    SQLModel.metadata.create_all(eng)  # piece_intervals appears via create_all, no migration needed
    assert "piece_intervals" in {r[0] for r in eng.connect().exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
