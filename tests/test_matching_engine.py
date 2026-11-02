from __future__ import annotations

from datetime import datetime, timedelta, timezone

from catch.core.models import Activity, CanonicalActivity, MatchDecision, MergeLog
from catch.sync.matching import (
    list_flagged_duplicates,
    manual_merge,
    mark_not_duplicate,
    run_matching,
    split_activity,
)

T0 = datetime(2026, 2, 1, 7, 0, 0, tzinfo=timezone.utc)


def _add(session, **kwargs) -> Activity:
    row = Activity(**kwargs)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_watch_and_peloton_pushed_ride_merge_into_one_canonical_with_field_sources(session):
    """Part A.3: a Peloton-origin Garmin record (power/cadence) and the watch's own
    recording (HR) of the same ride merge into one canonical that prefers Peloton's power."""
    watch = _add(
        session,
        source="garmin",
        external_id="watch1",
        type="indoor_cycling",
        start=T0,
        duration=2700.0,
        avg_hr=145,
        origin="watch",
    )
    peloton = _add(
        session,
        source="garmin",
        external_id="peloton1",
        type="indoor_cycling",
        start=T0 + timedelta(seconds=15),
        duration=2700.0,
        avg_power=180.0,
        avg_cadence=85.0,
        origin="peloton",
    )

    run_matching(session)
    session.refresh(watch)
    session.refresh(peloton)
    assert watch.canonical_id == peloton.canonical_id

    canonical = session.get(CanonicalActivity, watch.canonical_id)
    assert canonical.avg_power == 180.0  # from Peloton (field_priority.power default)
    assert canonical.avg_hr == 145  # only the watch has HR
    sources = __import__("json").loads(canonical.field_sources_json)
    assert sources["avg_power"] == "garmin:peloton1"
    assert sources["avg_hr"] == "garmin:watch1"


def test_back_to_back_rowing_sessions_stay_separate(session):
    a = _add(session, source="garmin", external_id="a1", type="indoor_rowing", start=T0, duration=1800.0)
    b = _add(
        session,
        source="garmin",
        external_id="b1",
        type="indoor_rowing",
        start=T0 + timedelta(hours=3),
        duration=1800.0,
    )

    run_matching(session)
    session.refresh(a)
    session.refresh(b)
    assert a.canonical_id != b.canonical_id


def test_indoor_vs_outdoor_cycling_flagged_but_never_auto_merged(session):
    indoor = _add(session, source="garmin", external_id="i1", type="indoor_cycling", start=T0, duration=1800.0)
    outdoor = _add(session, source="garmin", external_id="o1", type="cycling", start=T0, duration=1800.0)

    result = run_matching(session)
    session.refresh(indoor)
    session.refresh(outdoor)
    assert indoor.canonical_id != outdoor.canonical_id
    assert result["auto_merged"] == 0


def test_manual_merge_then_split_restores_two_canonicals(session):
    a = _add(session, source="garmin", external_id="a2", type="strength_training", start=T0, duration=3600.0)
    b = _add(session, source="garmin", external_id="b2", type="strength_training", start=T0 + timedelta(days=1), duration=3600.0)
    run_matching(session)
    session.refresh(a)
    session.refresh(b)
    assert a.canonical_id != b.canonical_id  # too far apart to auto-match

    canonical = manual_merge(session, a.id, b.id)
    session.refresh(a)
    session.refresh(b)
    assert a.canonical_id == b.canonical_id == canonical.id

    split_activity(session, b.id)
    session.refresh(a)
    session.refresh(b)
    assert a.canonical_id != b.canonical_id

    # Re-running matching must not silently re-merge them (task Part A.5's "manual split
    # staying split after re-sync").
    run_matching(session)
    session.refresh(a)
    session.refresh(b)
    assert a.canonical_id != b.canonical_id
    assert session.exec(
        __import__("sqlmodel").select(MatchDecision)
    ).first().decision == "split"


def test_mark_not_duplicate_prevents_future_auto_merge(session):
    a = _add(session, source="garmin", external_id="nd1", type="indoor_rowing", start=T0, duration=1800.0)
    b = _add(session, source="concept2", external_id="nd2", type="rower", start=T0 + timedelta(seconds=20), duration=1800.0)

    mark_not_duplicate(session, a.id, b.id)
    run_matching(session)
    session.refresh(a)
    session.refresh(b)
    assert a.canonical_id != b.canonical_id


def test_duplicates_review_lists_flagged_but_unmerged_pairs(session):
    # A pair that clears the "candidate" bar (same family, start within the 3-minute window,
    # equal duration) but whose short pieces barely overlap — low score, flagged rather than
    # auto-merged.
    a = _add(session, source="garmin", external_id="f1", type="indoor_rowing", start=T0, duration=200.0)
    b = _add(
        session,
        source="garmin",
        external_id="f2",
        type="indoor_rowing",
        start=T0 + timedelta(seconds=170),
        duration=200.0,
    )

    run_matching(session)
    pairs = list_flagged_duplicates(session)
    assert any({p["a"]["activity_id"], p["b"]["activity_id"]} == {a.id, b.id} for p in pairs)


def test_run_matching_resolves_a_blank_migrated_canonical(session):
    """Regression: catch/core/db.py's one-time linked_activity_id migration creates a
    canonical but never resolves it — a never-merged migrated activity must not stay
    permanently blank (start/duration/avg_hr all NULL) on every later run_matching call."""
    activity = _add(session, source="garmin", external_id="old1", type="indoor_rowing", start=T0, duration=1800.0, avg_hr=140)
    blank_canonical = CanonicalActivity(sport_family="rowing")  # deliberately never resolved
    session.add(blank_canonical)
    session.commit()
    activity.canonical_id = blank_canonical.id
    session.add(activity)
    session.commit()
    assert blank_canonical.start is None

    run_matching(session)
    session.refresh(blank_canonical)
    assert blank_canonical.start == T0
    assert blank_canonical.avg_hr == 140


def test_run_matching_is_idempotent_over_repeated_backfill_runs(session):
    a = _add(session, source="concept2", external_id="i1", type="rower", start=T0, duration=1800.0)
    b = _add(session, source="garmin", external_id="i2", type="indoor_rowing", start=T0 + timedelta(seconds=10), duration=1800.0)

    first = run_matching(session)
    assert first["auto_merged"] == 1
    second = run_matching(session)
    assert second["auto_merged"] == 0  # already merged — nothing left to do

    merges = session.exec(__import__("sqlmodel").select(MergeLog)).all()
    assert len(merges) == 2  # one MergeLog row per member of the one real merge, logged once
