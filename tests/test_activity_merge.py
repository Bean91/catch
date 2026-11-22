"""Session 33, Part A: merging workouts into one ("combine") through the real pipeline — what the merged workout reports, that
nothing is lost or counted twice, that every link follows it, that the next sync can't undo or duplicate it, and that it can be
undone."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from catch.core.models import Activity, CanonicalActivity, MatchDecision, MergeLog, Piece, PlannedWorkout, TechniqueNote
from catch.core.settings_store import get_settings, update_settings
from catch.sync import activity_merge, scoring
from catch.sync import piece as piece_sync
from catch.sync.matching import list_flagged_duplicates, run_matching
from catch.sync.samples import store_samples
from catch.sync.upsert import upsert_activity
from conftest import TEST_PASSWORD

T0 = datetime(2026, 7, 15, 7, tzinfo=timezone.utc)


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _rec(session, source: str, ext: str, start: datetime, minutes: float, hr: float, distance: float | None, type_: str = "indoor_rowing") -> Activity:
    n = int(minutes * 60)
    a = upsert_activity(session, source, ext, type=type_, start=start, duration=float(n), distance=distance, avg_hr=hr, max_hr=hr + 8, sport_family="rowing")
    store_samples(session, a.id, start=start, hr=[hr + (i % 3 - 1) for i in range(n)], power=[None] * n, cadence=[22.0] * n)
    return a


def _rhr(session, day, value=50):
    from catch.core.models import DailyWellness

    for i in range(0, 15):
        session.add(DailyWellness(date=day - timedelta(days=i), resting_hr=value))
    session.commit()


def _two_parts(session):
    update_settings(session, {"max_hr": 190})
    _rhr(session, T0.date())
    a = _rec(session, "garmin", "part1", T0, 30, 140, 7000)
    b = _rec(session, "garmin", "part2", T0 + timedelta(minutes=40), 20, 165, 5000)
    run_matching(session)
    session.refresh(a)
    session.refresh(b)
    return session.get(CanonicalActivity, a.canonical_id), session.get(CanonicalActivity, b.canonical_id)


def _merge(session, ids):
    p = activity_merge.preview(session, ids)
    assert p["compatible"], p["reasons"]
    return activity_merge.combine(session, ids, p["preview_hash"])


def test_preview_shows_the_combined_result_and_writes_nothing(session):
    c1, c2 = _two_parts(session)
    stamps = (c1.updated_at, c2.updated_at)
    canonicals_before = len(session.exec(select(CanonicalActivity)).all())

    p = activity_merge.preview(session, [c2.id, c1.id])
    assert p["compatible"] and p["keep_id"] == c1.id
    r = p["result"]
    assert r["duration"] == pytest.approx(3000)
    assert r["distance"] == pytest.approx(12000)
    # Weighted by duration: (140 * 1800 + 165 * 1200) / 3000 = 150, not (140 + 165) / 2 = 152.5.
    assert r["avg_hr"] == pytest.approx(150)
    assert r["max_hr"] == 173
    assert sum(r["zones"].values()) == pytest.approx(3000, abs=5)
    assert [i["id"] for i in p["items"]] == [c1.id, c2.id]

    session.expire_all()
    assert len(session.exec(select(CanonicalActivity)).all()) == canonicals_before
    assert (session.get(CanonicalActivity, c1.id).updated_at, session.get(CanonicalActivity, c2.id).updated_at) == stamps
    assert session.exec(select(MergeLog).where(MergeLog.action == "combine")).first() is None


def test_combine_keeps_every_recording_and_counts_strain_once(session):
    c1, c2 = _two_parts(session)
    separate_trimp = c1.strain_trimp + c2.strain_trimp
    day = c1.local_date
    separate_day = scoring.day_strain(session, day, get_settings(session))["value"]

    merged = _merge(session, [c1.id, c2.id])
    assert merged.id == c1.id and merged.merge_mode == "combined"
    assert session.get(CanonicalActivity, c2.id) is None
    members = session.exec(select(Activity).where(Activity.canonical_id == merged.id)).all()
    assert {m.external_id for m in members} == {"part1", "part2"}  # source records untouched, only regrouped
    assert merged.duration == pytest.approx(3000) and merged.distance == pytest.approx(12000)
    assert merged.strain_trimp == pytest.approx(separate_trimp, rel=0.02)  # the same seconds, counted once
    assert scoring.day_strain(session, day, get_settings(session))["value"] == pytest.approx(separate_day, abs=0.15)
    hr_zones = json.loads(merged.zones_json)["hr"]
    assert sum(hr_zones.values()) == pytest.approx(3000, abs=5)


def test_a_duplicate_pair_inside_the_selection_is_counted_once(session):
    update_settings(session, {"max_hr": 190})
    watch = _rec(session, "garmin", "w", T0, 30, 140, 6900)
    erg = _rec(session, "concept2", "c", T0 + timedelta(seconds=20), 29.5, 141, 7000, type_="rower")
    part2 = _rec(session, "garmin", "w2", T0 + timedelta(minutes=40), 20, 160, 5000)
    run_matching(session)
    for a in (watch, erg, part2):
        session.refresh(a)
    ids = sorted({watch.canonical_id, erg.canonical_id, part2.canonical_id})
    merged = _merge(session, ids)
    # Concept2 wins inside the overlapping group (field priority), then the second part adds on.
    assert merged.distance == pytest.approx(7000 + 5000)
    assert merged.duration == pytest.approx(29.5 * 60 + 1200)


def test_every_link_follows_the_merged_workout_and_comes_back_on_undo(session):
    c1, c2 = _two_parts(session)
    c1.overrides_json = json.dumps({"tags": ["race-prep"], "notes": "first"})
    c2.overrides_json = json.dumps({"tags": ["test"], "test_type": "2000m", "notes": "second", "rpe": 8})
    session.add_all([c1, c2])
    session.commit()
    piece, _ = piece_sync.create_piece(session, c2.id, "2000m", [{"split_index": 1, "distance_m": 2000.0, "split_s": 420.0, "rate": 30, "watts": None, "hr": None}])
    note = TechniqueNote(category="catch", text="early catch", canonical_id=c2.id)
    plan = PlannedWorkout(date=c2.local_date, title="2k", session_type="erg", linked_canonical_id=c2.id)
    session.add_all([note, plan])
    session.commit()

    merged = _merge(session, [c1.id, c2.id])
    o = json.loads(merged.overrides_json)
    assert o["tags"] == ["race-prep", "test"] and o["test_type"] == "2000m" and o["notes"] == "first\n\nsecond" and o["rpe"] == 8
    session.expire_all()
    assert session.get(Piece, piece.id).canonical_id == merged.id
    assert session.get(TechniqueNote, note.id).canonical_id == merged.id
    assert session.get(PlannedWorkout, plan.id).linked_canonical_id == merged.id

    restored = activity_merge.uncombine(session, merged.id)
    assert restored[0] == merged.id and len(restored) == 2
    back = restored[1]
    session.expire_all()
    assert session.get(CanonicalActivity, merged.id).merge_mode is None
    assert json.loads(session.get(CanonicalActivity, merged.id).overrides_json) == {"tags": ["race-prep"], "notes": "first"}
    assert json.loads(session.get(CanonicalActivity, back).overrides_json)["test_type"] == "2000m"
    assert session.get(Piece, piece.id).canonical_id == back
    assert session.get(TechniqueNote, note.id).canonical_id == back
    assert session.get(PlannedWorkout, plan.id).linked_canonical_id == back
    assert session.get(CanonicalActivity, merged.id).duration == pytest.approx(1800)
    assert session.get(CanonicalActivity, back).duration == pytest.approx(1200)
    # The matcher never re-merges them on its own.
    assert session.exec(select(MatchDecision).where(MatchDecision.decision == "split")).first() is not None
    run_matching(session)
    assert session.get(CanonicalActivity, back) is not None


def test_a_stale_preview_is_refused(session):
    c1, c2 = _two_parts(session)
    p = activity_merge.preview(session, [c1.id, c2.id])
    c2.overrides_json = json.dumps({"rpe": 5})
    from catch.sync.canonical import resolve_canonical

    session.add(c2)
    session.commit()
    resolve_canonical(session, c2.id)
    with pytest.raises(activity_merge.MergeError) as err:
        activity_merge.combine(session, [c1.id, c2.id], p["preview_hash"])
    assert err.value.status == 409


def test_a_resync_of_a_member_keeps_the_merge_and_updates_its_totals(session):
    c1, c2 = _two_parts(session)
    merged = _merge(session, [c1.id, c2.id])
    upsert_activity(session, "garmin", "part2", duration=1260.0, distance=5200.0)  # the provider corrected the record
    run_matching(session)
    from catch.sync.canonical import resolve_canonical

    resolve_canonical(session, merged.id)
    after = session.get(CanonicalActivity, merged.id)
    assert after.merge_mode == "combined"
    assert len(session.exec(select(CanonicalActivity)).all()) == 1
    assert after.distance == pytest.approx(12200) and after.duration == pytest.approx(3060)


def test_a_new_duplicate_of_one_part_joins_once_and_a_spanning_recording_is_flagged_not_merged(session):
    c1, c2 = _two_parts(session)
    merged = _merge(session, [c1.id, c2.id])
    # Concept2 later syncs the first part: it joins the merged workout as a duplicate of that part.
    _rec(session, "concept2", "c-part1", T0 + timedelta(seconds=15), 29.8, 141, 7050, type_="rower")
    run_matching(session)
    after = session.get(CanonicalActivity, merged.id)
    assert len(session.exec(select(Activity).where(Activity.canonical_id == merged.id)).all()) == 3
    assert after.distance == pytest.approx(7050 + 5000)  # not 7000 + 7050 + 5000
    # A whole-session recording from another device covers both parts: flagged for review, never merged in.
    spanning = _rec(session, "whoop", "span", T0 - timedelta(minutes=1), 62, 150, None)
    run_matching(session)
    session.refresh(spanning)
    assert spanning.canonical_id != merged.id
    flagged = list_flagged_duplicates(session)
    assert any({p["a"]["activity_id"], p["b"]["activity_id"]} & {spanning.id} and p["hard_block"] for p in flagged)
    # ...and the day's strain doesn't count that session twice in the meantime.
    strain = scoring.day_strain(session, after.local_date, get_settings(session))
    assert any(c.get("duplicate_of") for c in strain["components"])


def test_merging_into_a_merged_workout_through_the_duplicates_flow_is_refused(client, session):
    c1, c2 = _two_parts(session)
    _merge(session, [c1.id, c2.id])
    other = _rec(session, "garmin", "later", T0 + timedelta(minutes=70), 10, 150, 2000)
    run_matching(session)
    member = session.exec(select(Activity).where(Activity.external_id == "part1")).first()
    _login(client)
    resp = client.post("/api/activities/merge", json={"activity_id_a": member.id, "activity_id_b": other.id})
    assert resp.status_code == 422 and "Undo that merge first" in resp.json()["detail"]


def test_merging_across_local_midnight_keeps_the_earliest_day_and_its_change_day(session):
    update_settings(session, {"max_hr": 190})
    late = _rec(session, "garmin", "late", datetime(2026, 7, 15, 23, 30, tzinfo=timezone.utc), 25, 140, 6000)
    early = _rec(session, "garmin", "early", datetime(2026, 7, 16, 0, 5, tzinfo=timezone.utc), 20, 150, 5000)
    run_matching(session)
    session.refresh(late)
    session.refresh(early)
    first = session.get(CanonicalActivity, late.canonical_id)
    first_day = first.local_date
    merged = _merge(session, [late.canonical_id, early.canonical_id])
    assert merged.local_date == first_day
    # A "Change day" on the kept workout survives the merge and every re-resolve.
    from catch.sync.canonical import resolve_canonical

    merged.overrides_json = json.dumps({**json.loads(merged.overrides_json or "{}"), "local_date": (first_day + timedelta(days=1)).isoformat()})
    session.add(merged)
    session.commit()
    assert resolve_canonical(session, merged.id).local_date == first_day + timedelta(days=1)


def test_the_ordinary_duplicate_merge_now_moves_pieces_too(session):
    update_settings(session, {"max_hr": 190})
    a = _rec(session, "garmin", "dup-a", T0, 30, 140, 7000)
    b = _rec(session, "garmin", "dup-b", T0 + timedelta(hours=3), 30, 140, 7000)
    run_matching(session)
    session.refresh(a)
    session.refresh(b)
    piece, _ = piece_sync.create_piece(session, b.canonical_id, "custom", [], distance_m=1000.0, duration_s=200.0)
    from catch.sync.matching import manual_merge

    kept = manual_merge(session, a.id, b.id)
    session.expire_all()
    assert session.get(Piece, piece.id).canonical_id == kept.id


def test_api_preview_combine_detail_and_uncombine(client, session):
    c1, c2 = _two_parts(session)
    _login(client)
    p = client.post("/api/activities/combine/preview", json={"canonical_ids": [c1.id, c2.id]}).json()
    assert p["compatible"]
    stale = client.post("/api/activities/combine", json={"canonical_ids": [c1.id, c2.id], "preview_hash": "0" * 24})
    assert stale.status_code == 409
    done = client.post("/api/activities/combine", json={"canonical_ids": [c1.id, c2.id], "preview_hash": p["preview_hash"]})
    assert done.status_code == 200
    detail = done.json()
    assert detail["merge"]["recordings"] == 2 and detail["merge"]["can_undo"]
    samples = client.get(f"/api/activities/{c1.id}/samples").json()
    assert samples["n_samples"] >= 3000 and samples["member_offsets"]
    undo = client.post(f"/api/activities/{c1.id}/uncombine")
    assert undo.status_code == 200 and len(undo.json()["canonical_ids"]) == 2
    again = client.post(f"/api/activities/{c1.id}/uncombine")
    assert again.status_code == 422


def test_api_refuses_incompatible_merges_with_reasons(client, session):
    update_settings(session, {"max_hr": 190})
    row = _rec(session, "garmin", "row", T0, 30, 140, 7000)
    bike = upsert_activity(session, "garmin", "bike", type="indoor_cycling", start=T0 + timedelta(minutes=40), duration=1200.0, sport_family="cycling")
    run_matching(session)
    session.refresh(row)
    _login(client)
    ids = [row.canonical_id, bike.canonical_id]
    p = client.post("/api/activities/combine/preview", json={"canonical_ids": ids}).json()
    assert not p["compatible"] and any("different sports" in r for r in p["reasons"]) and p["result"] is None
    resp = client.post("/api/activities/combine", json={"canonical_ids": ids, "preview_hash": p["preview_hash"]})
    assert resp.status_code == 422 and resp.json()["detail"]["reasons"]
    assert client.post("/api/activities/combine/preview", json={"canonical_ids": [row.canonical_id, 99999]}).status_code == 404


def test_retention_keeps_the_undo_record_while_the_merged_workout_exists(session):
    from catch.sync import retention

    c1, c2 = _two_parts(session)
    merged = _merge(session, [c1.id, c2.id])
    log = activity_merge.latest_combine(session, merged.id)
    log.created_at = datetime.now(timezone.utc) - timedelta(days=900)
    session.add(log)
    session.commit()
    retention.prune_owner(session)
    assert activity_merge.latest_combine(session, merged.id) is not None
