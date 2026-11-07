from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from catch.core.models import Activity, CanonicalActivity, DailyWellness, Piece, PiecePhoto, Stroke
from catch.core.settings_store import get_settings, update_settings
from catch.sync import piece as piece_sync
from catch.sync.canonical import resolve_canonical
from catch.sync.matching import run_matching
from catch.sync.samples import store_samples

T0 = datetime(2026, 7, 1, 7, tzinfo=timezone.utc)

# The task's own worked example (session 17 Part B.3's fixture), reused across these tests.
_SPLITS = [
    {"split_index": 1, "distance_m": 500.0, "split_s": 96.8, "rate": 32.0, "watts": None, "hr": None},
    {"split_index": 2, "distance_m": 1000.0, "split_s": 98.9, "rate": 30.0, "watts": None, "hr": None},
    {"split_index": 3, "distance_m": 1500.0, "split_s": 99.0, "rate": 31.0, "watts": None, "hr": None},
    {"split_index": 4, "distance_m": 2000.0, "split_s": 97.7, "rate": 32.0, "watts": None, "hr": None},
]


def _make_activity(session, external_id="g1", duration=3600.0, sport_family="rowing", start=None) -> Activity:
    a = Activity(source="garmin", external_id=external_id, type="rowing_v2", start=start or T0, duration=duration, sport_family=sport_family)
    session.add(a)
    session.commit()
    canonical = CanonicalActivity(sport_family=sport_family)
    session.add(canonical)
    session.commit()
    a.canonical_id = canonical.id
    session.add(a)
    session.commit()
    return a


def test_create_piece_rejects_invalid_splits_without_force(session):
    activity = _make_activity(session)
    bad_splits = [dict(s) for s in _SPLITS]
    bad_splits[-1]["split_s"] = 10.0  # breaks the total-time check
    result, validation = piece_sync.create_piece(session, activity.canonical_id, "2000m", bad_splits, distance_m=2000.0, duration_s=392.4)
    assert result is None
    assert not validation["ok"]
    assert piece_sync.list_pieces_for_canonical(session, activity.canonical_id) == []


def test_create_piece_saves_valid_splits_and_computes_aggregates(session):
    activity = _make_activity(session)
    piece, validation = piece_sync.create_piece(session, activity.canonical_id, "2000m", [dict(s) for s in _SPLITS], distance_m=2000.0, duration_s=392.4)
    assert validation["ok"]
    assert piece is not None
    assert piece.distance_m == 2000.0
    assert piece.duration_s == pytest.approx(392.4)
    assert piece.avg_rate == pytest.approx((32 + 30 + 31 + 32) / 4)


def test_create_piece_can_be_forced_to_save_despite_issues(session):
    activity = _make_activity(session)
    bad_splits = [dict(s) for s in _SPLITS]
    bad_splits[0]["rate"] = 99.0
    piece, validation = piece_sync.create_piece(session, activity.canonical_id, "2000m", bad_splits, distance_m=2000.0, duration_s=392.4, force=True)
    assert piece is not None
    assert not validation["ok"]  # the issue is still reported, just not blocking


def test_piece_auto_aligns_inside_warmup_piece_cooldown_fixture(session):
    """Session 17's quality-bar fixture (mirrors session 12's): a 20-min warm-up at ~120bpm,
    a ~6.5min piece at ~175bpm, a 25-min cool-down at ~130bpm — the piece should land inside
    the hard stretch, get per-split HR, and refine (not add to) this activity's own strain."""
    activity = _make_activity(session, duration=3600.0)
    warmup = [120.0 + (i % 3 - 1) for i in range(1200)]
    hard = [175.0 + (i % 3 - 1) for i in range(int(392.4))]
    cooldown = [130.0 + (i % 3 - 1) for i in range(3600 - 1200 - len(hard))]
    hr = warmup + hard + cooldown
    store_samples(session, activity.id, start=T0, hr=hr, power=[None] * len(hr), cadence=[20.0] * len(hr))
    update_settings(session, {"max_hr": 190})

    piece, validation = piece_sync.create_piece(session, activity.canonical_id, "2000m", [dict(s) for s in _SPLITS], distance_m=2000.0, duration_s=392.4)
    assert validation["ok"]
    session.refresh(piece)
    assert piece.window_activity_id == activity.id
    assert 1150 <= piece.window_start_s <= 1250  # lands on the hard stretch, not drifted far

    splits = json.loads(piece.splits_json)
    assert all(s["hr"] is not None and 170 <= s["hr"] <= 180 for s in splits)
    assert piece.time_in_zone_json is not None


def test_piece_power_overlay_refines_zones_without_adding_strain(session):
    """Task Part D.3: the piece's own watts fill the activity's power-zone computation for
    its window only — and the day's total strain must not double-count it on top of the
    activity's own HR-based strain."""
    activity = _make_activity(session, duration=3600.0)
    hr = [130.0 + (i % 3 - 1) for i in range(3600)]
    store_samples(session, activity.id, start=T0, hr=hr, power=[None] * 3600, cadence=[20.0] * 3600)
    update_settings(session, {"max_hr": 190})
    session.add(DailyWellness(date=T0.date(), resting_hr=55))
    session.commit()

    # Baseline: strain from HR alone, before any piece exists. A flat 130bpm hour against
    # resting 55/max 190 sits in UT2 throughout — no power data yet, so the label is HR-only.
    canonical_before = resolve_canonical(session, activity.canonical_id)
    trimp_before = canonical_before.strain_trimp
    assert trimp_before is not None
    assert canonical_before.session_label == "UT2 (60 min)"

    splits = [dict(s) for s in _SPLITS]
    for s in splits:
        from catch.analytics.piece import watts_for_split

        s["watts"] = round(watts_for_split(s["split_s"]))
    piece, validation = piece_sync.create_piece(session, activity.canonical_id, "2000m", splits, distance_m=2000.0, duration_s=392.4)
    assert validation["ok"]

    canonical = resolve_canonical(session, activity.canonical_id)
    zones = json.loads(canonical.zones_json)
    assert zones["power"] is not None
    assert any(v > 0 for v in zones["power"].values())
    # The real assertion this test is for (task Part D.2's "gets labelled correctly"): the
    # piece's own watts for its ~6.5min window are fast enough to land in AN, which outranks
    # the HR label's UT2 — a 2k inside an otherwise-easy long row is no longer mislabelled.
    # Checking only "power zones are non-empty" (an earlier version of this test) would pass
    # even if the overlay fed the wrong window or the wrong zone entirely.
    assert canonical.session_label == "AN (7 min)"
    assert zones["power"]["AN"] > 0
    assert zones["power"]["UT2"] == 0.0

    # The piece's watts refine the *power-zone label* (and feed the muscular-load split) but
    # never change strain_trimp itself — rowing strain stays HR-Banister-based regardless of
    # whether a piece exists, so the exact same number before and after is the real
    # no-double-counting guarantee, not just "strain_trimp is not None" (an earlier,
    # weaker version of this test — an advisor review flagged it as checking nothing).
    assert canonical.strain_trimp == trimp_before

    from catch.sync.scoring import day_strain

    day = T0.astimezone().date()
    strain = day_strain(session, day, get_settings(session))
    matching = [c for c in strain["components"] if c["canonical_id"] == activity.canonical_id]
    assert len(matching) == 1


def test_delete_piece_removes_photo_too(session):
    activity = _make_activity(session)
    piece, _ = piece_sync.create_piece(session, activity.canonical_id, "2000m", [dict(s) for s in _SPLITS], distance_m=2000.0, duration_s=392.4)
    piece_sync.attach_photo(session, piece.id, b"fake-jpeg-bytes", "image/jpeg")
    assert piece_sync.get_photo(session, piece.id) is not None

    assert piece_sync.delete_piece(session, piece.id)
    assert session.get(Piece, piece.id) is None
    assert session.get(PiecePhoto, piece.id) is None


def test_piece_pb_candidates_includes_confirmed_pieces_but_not_absorbed_ones(session):
    activity = _make_activity(session, duration=3600.0)
    piece, validation = piece_sync.create_piece(session, activity.canonical_id, "2000m", [dict(s) for s in _SPLITS], distance_m=2000.0, duration_s=392.4)
    assert validation["ok"]

    candidates = piece_sync.piece_pb_candidates(session)
    assert len(candidates) == 1
    assert candidates[0]["distance"] == 2000.0
    assert candidates[0]["canonical_id"] == activity.canonical_id

    piece.concept2_activity_id = 12345  # pretend it was absorbed (Part D.4)
    session.add(piece)
    session.commit()
    assert piece_sync.piece_pb_candidates(session) == []


def test_manual_realign_refreshes_derived_hr_and_never_touches_typed_hr(session):
    """Part D.1/D.2, and the specific regression an advisor review caught: the first
    auto-align's derived HR must not survive untouched after a later drag to a different
    window, but a typed/photo HR must survive every align untouched."""
    activity = _make_activity(session, duration=3600.0)
    hr = [120.0] * 1200 + [175.0] * 400 + [130.0] * 2000
    store_samples(session, activity.id, start=T0, hr=hr, power=[None] * 3600, cadence=[20.0] * 3600)

    splits = [dict(s) for s in _SPLITS]
    splits[0]["hr"] = 160.0  # typed by the athlete — must never be overwritten by any align
    piece, validation = piece_sync.create_piece(session, activity.canonical_id, "2000m", splits, distance_m=2000.0, duration_s=392.4)
    assert validation["ok"]
    session.refresh(piece)
    first_rows = json.loads(piece.splits_json)
    assert first_rows[0]["hr"] == 160.0
    assert first_rows[0]["hr_source"] == "typed"
    derived_hr_at_hard_window = first_rows[1]["hr"]
    assert derived_hr_at_hard_window is not None

    moved = piece_sync.align_piece(session, piece.id, activity_id=activity.id, start_s=2000)  # the easy 130bpm stretch
    moved_rows = json.loads(moved.splits_json)
    assert moved_rows[0]["hr"] == 160.0  # typed value survives the drag untouched
    assert moved_rows[1]["hr"] != derived_hr_at_hard_window  # derived value refreshed, not stale
    assert moved_rows[1]["hr"] == pytest.approx(130.0, abs=1.0)


def test_confirmed_piece_pace_candidates_filters_by_the_activitys_own_date(session):
    """Not Piece.created_at — the piece's containing activity's date, so a piece typed in
    long after the fact (reviewing an old photo) is judged by when the effort happened."""
    from catch.sync.piece import confirmed_piece_pace_candidates

    old_activity = _make_activity(session, external_id="old", duration=3600.0, start=T0 - timedelta(days=200))
    piece_sync.create_piece(session, old_activity.canonical_id, "2000m", [dict(s) for s in _SPLITS], distance_m=2000.0, duration_s=392.4)

    cutoff = T0 - timedelta(days=30)
    candidates = confirmed_piece_pace_candidates(session, cutoff)
    assert candidates == []  # the old piece's activity predates the cutoff

    recent_activity = _make_activity(session, external_id="recent", duration=3600.0, start=T0)
    piece_sync.create_piece(session, recent_activity.canonical_id, "2000m", [dict(s) for s in _SPLITS], distance_m=2000.0, duration_s=392.4)

    candidates = confirmed_piece_pace_candidates(session, cutoff)
    assert len(candidates) == 1
    assert candidates[0]["label"] == T0.date().isoformat()


def test_absorb_concept2_piece_result_absorbs_a_pm5_only_result_without_corrupting_the_parent(session):
    """Part D.4, case 1: a PM5-only 2k result syncs later as its own tiny canonical (duration
    ratio against the 90-min parent session fails run_matching's merge gate). An earlier
    version of this absorb reassigned the Concept2 Activity's canonical_id onto the parent —
    an advisor review caught that this corrupts the parent via ordinary field-priority
    (Concept2 wins duration/distance/HR), shrinking a 90-minute session down to a 6-minute
    one. The fix leaves the Concept2 result on its own (now-marked-absorbed) canonical
    instead, so the parent's own resolved fields and strain are never touched."""
    activity = _make_activity(session, duration=5400.0)  # 90 min
    hr = [130.0] * 5400
    store_samples(session, activity.id, start=T0, hr=hr, power=[None] * 5400, cadence=[20.0] * 5400)
    update_settings(session, {"max_hr": 190})
    session.add(DailyWellness(date=T0.date(), resting_hr=55))
    session.commit()

    piece, validation = piece_sync.create_piece(session, activity.canonical_id, "2000m", [dict(s) for s in _SPLITS], distance_m=2000.0, duration_s=392.4)
    assert validation["ok"]
    assert piece.concept2_activity_id is None

    parent_before = resolve_canonical(session, activity.canonical_id)
    parent_duration_before = parent_before.duration
    parent_strain_before = parent_before.strain_trimp
    assert parent_duration_before == 5400.0

    # The real Concept2 2k syncs later, same local day, matching distance/duration closely,
    # with real strokes so split recomputation (rate/watts/hr) is actually exercised.
    c2 = Activity(source="concept2", external_id="c2-1", type="rower", start=T0, duration=392.6, distance=2000.0, workout_type="FixedDistanceSplits")
    session.add(c2)
    session.commit()
    c2_canonical = CanonicalActivity(sport_family="rowing", start=T0, duration=392.6, distance=2000.0, avg_hr=170.0, category="erg")
    session.add(c2_canonical)
    session.commit()
    c2.canonical_id = c2_canonical.id
    session.add(c2)
    session.commit()
    t_cum = 0.0
    for i, (dist, split_s, rate) in enumerate([(500.0, 96.8, 32.0), (500.0, 98.9, 30.0), (500.0, 99.0, 31.0), (500.0, 97.7, 32.0)]):
        t_cum += split_s
        session.add(Stroke(activity_id=c2.id, seq=i, interval_index=0, t=t_cum, distance=(i + 1) * 500.0, watts=220.0 + i, stroke_rate=rate, hr=165.0 + i))
    session.commit()
    orphan_id = c2_canonical.id

    absorbed = piece_sync.absorb_concept2_piece_results(session)
    assert absorbed == 1

    session.refresh(piece)
    assert piece.concept2_activity_id == c2.id
    assert piece.source == "concept2"
    rows = json.loads(piece.splits_json)
    assert [r["split_s"] for r in rows] == pytest.approx([96.8, 98.9, 99.0, 97.7])
    assert all(r["watts"] is not None for r in rows)  # real per-split watts, not dropped (Part D.3)
    assert all(r["hr"] is not None for r in rows)

    # The orphan canonical still exists (never deleted — it may carry user overrides) but is
    # marked absorbed and excluded from totals; its Activity row never moved.
    orphan = session.get(CanonicalActivity, orphan_id)
    assert orphan is not None
    assert orphan.absorbed_into_piece_id == piece.id
    assert json.loads(orphan.overrides_json)["exclude_from_totals"] is True
    assert session.get(Activity, c2.id).canonical_id == orphan_id  # never reassigned

    # The parent's own resolved fields and strain are completely unaffected.
    parent_after = resolve_canonical(session, activity.canonical_id)
    assert parent_after.duration == parent_duration_before
    assert parent_after.strain_trimp == parent_strain_before

    from catch.sync.erg_test import list_candidates, list_tests

    # The absorbed canonical never shows up as its own (duplicate) test-center row.
    assert all(c["canonical_id"] != orphan_id for c in list_candidates(session))
    assert all(t["canonical_id"] != orphan_id for t in list_tests(session))

    # Running the full matching pass (what actually happens after every sync) must not
    # re-absorb or re-flag the already-absorbed pair.
    run_matching(session)
    assert session.get(Activity, c2.id).canonical_id == orphan_id
