from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from catch.core.models import Activity, CanonicalActivity, DailyWellness
from catch.core.settings_store import get_settings, update_settings
from catch.sync.canonical import _is_generic_garmin_title, auto_title, resolve_all_canonicals
from catch.sync.matching import run_matching
from catch.sync.samples import store_samples

T0 = datetime(2026, 7, 1, 7, tzinfo=timezone.utc)


def _jitter(base_hr: float, n: int) -> list[float]:
    """±1 bpm oscillation, not a flat value for `n` seconds straight — a real HR trace never
    holds one exact integer bpm for 30s+ (drop_dropouts, Part E.2, would correctly treat that
    as a stuck sensor and drop it, which a naive constant-value fixture would trigger)."""
    return [base_hr + (i % 3 - 1) for i in range(n)]


def test_generic_garmin_title_detection():
    assert _is_generic_garmin_title("Indoor Cycling", "indoor_cycling") is True
    assert _is_generic_garmin_title("indoor cycling", "indoor_cycling") is True  # case/spacing-insensitive
    assert _is_generic_garmin_title(None, "indoor_cycling") is True
    assert _is_generic_garmin_title("Power Zone Ride with Matt Wilpers", "cycling") is False


def test_auto_title_uses_a_real_garmin_title_hint_when_not_generic():
    renamed = Activity(source="garmin", external_id="g1", type="strength_training", title_hint="Leg Day (renamed in Connect)")
    assert auto_title("strength", [renamed]) == "Leg Day (renamed in Connect)"


def test_auto_title_ignores_garmins_own_generic_label(session):
    generic = Activity(source="garmin", external_id="g2", type="indoor_cycling", title_hint="Indoor Cycling", duration=1800.0)
    assert auto_title("cycling", [generic]) == "Ride"


def test_auto_title_prefers_a_real_peloton_class_name_over_the_synthesized_label():
    peloton = Activity(
        source="garmin", external_id="p1", type="cycling", origin="peloton", title_hint="45 min Power Zone Ride",
        duration=2700.0,
    )
    assert auto_title("cycling", [peloton], ["peloton", "concept2", "garmin"]) == "45 min Power Zone Ride"


def test_cycling_power_strain_uses_tss_not_hr_banister(session):
    """Task Part B.3: power-based TSS-style load wins over HR-based strain for cycling
    whenever power samples exist, end to end through resolve_canonical."""
    update_settings(session, {"max_hr": 190, "ftp_watts": 200.0})
    # avg_power on the row itself mirrors what the real Garmin sync sets from the activity
    # summary, independent of the FIT sample stream `_pick` isn't reading here.
    activity = Activity(source="garmin", external_id="bike1", type="indoor_cycling", start=T0, duration=1800.0, avg_power=200.0)
    session.add(activity)
    session.commit()

    # 30 minutes at 200W exactly at FTP -> TSS = 100 * 0.5h * 1.0^2 = 50.
    store_samples(session, activity.id, start=T0, hr=[None] * 1800, power=[200.0] * 1800, cadence=[85.0] * 1800)
    run_matching(session)
    session.refresh(activity)

    canonical = session.get(CanonicalActivity, activity.canonical_id)
    assert canonical.strain_method == "cycling_tss"
    assert canonical.strain_trimp == 50.0


def test_rowing_with_hr_samples_but_no_power_gets_a_muscular_share_that_tracks_max_hr(session):
    """Most real on-water rowing (and plenty of indoor erg entries) has per-sample HR but no
    power at all, so it never reaches the power-based sprint/moderate tiers — session 15's
    HR-trimp fallback is what gives these a nonzero muscular share. This also covers the
    "cache never goes stale" regression the max_hr test above guards for strain_trimp/zones:
    muscular_load_au must track a later max_hr change the same way, not freeze at whatever the
    first resolve computed."""
    update_settings(session, {"max_hr": 190})
    session.add(DailyWellness(date=T0.date(), resting_hr=50))
    activity = Activity(source="garmin", external_id="row-hr-only", type="rowing_v2", start=T0, duration=1800.0, avg_hr=150.0)
    session.add(activity)
    session.commit()
    store_samples(session, activity.id, start=T0, hr=_jitter(150.0, 1800), power=[None] * 1800, cadence=[None] * 1800)
    run_matching(session)
    session.refresh(activity)

    canonical = session.get(CanonicalActivity, activity.canonical_id)
    assert canonical.sport_family == "rowing"
    au_at_190 = canonical.muscular_load_au
    assert au_at_190 is not None and au_at_190 > 0.0

    # A lower max_hr reads the same 150bpm as a harder effort (higher HRr) -> more trimp ->
    # more muscular AU. Must change on re-resolve, not stay frozen at the first value.
    update_settings(session, {"max_hr": 160})
    resolve_all_canonicals(session)
    session.refresh(canonical)
    assert canonical.muscular_load_au is not None and canonical.muscular_load_au > au_at_190


def test_cycling_held_steadily_at_ftp_now_registers_some_muscular_share(session):
    """Session 15: before the moderate-tier muscular AU existed, holding power right at (or
    below) FTP the whole ride — the realistic case, since you can only hold *above* FTP for
    seconds to a couple minutes — scored exactly 0 muscular share, which read as "biking never
    loads muscle." It should now register something, while still staying well under what a
    short all-out effort above threshold would add."""
    update_settings(session, {"max_hr": 190, "ftp_watts": 200.0})
    activity = Activity(source="garmin", external_id="bike-steady", type="indoor_cycling", start=T0, duration=1800.0, avg_power=200.0)
    session.add(activity)
    session.commit()

    store_samples(session, activity.id, start=T0, hr=[None] * 1800, power=[200.0] * 1800, cadence=[85.0] * 1800)
    run_matching(session)
    session.refresh(activity)

    canonical = session.get(CanonicalActivity, activity.canonical_id)
    assert canonical.muscular_load_au is not None
    assert canonical.muscular_load_au > 0.0
    # 1800s at exactly the moderate rate (100% of FTP is inside the 55-110% band) -> 1800 * 200 * 0.00025.
    assert canonical.muscular_load_au == pytest.approx(90.0)


def test_cycling_power_strain_estimates_ftp_when_unset(session):
    update_settings(session, {"max_hr": 190})  # no ftp_watts configured
    activity = Activity(source="garmin", external_id="bike2", type="indoor_cycling", start=T0, duration=1800.0, avg_power=200.0)
    session.add(activity)
    session.commit()

    store_samples(session, activity.id, start=T0, hr=[None] * 1800, power=[200.0] * 1800, cadence=[85.0] * 1800)
    run_matching(session)
    session.refresh(activity)

    canonical = session.get(CanonicalActivity, activity.canonical_id)
    assert canonical.strain_method == "cycling_tss_estimated_ftp"
    # Estimated FTP = 200 * 0.95 = 190 -> IF = 200/190 -> TSS = 100 * 0.5 * (200/190)^2
    assert canonical.strain_trimp is not None and canonical.strain_trimp > 50.0


def test_quality_bar_fixture_end_to_end_through_the_real_pipeline(session):
    """The task's own motivating fixture, run through the *real* pipeline (store_samples ->
    resolve_canonical -> day_strain), not just the pure zones_samples functions directly —
    20 min warm-up, 10 min at ~95% max HR, 25 min cool-down, plus a trailing idle tail the
    watch kept running through. Label must be AN/TR-led (never UT2) and the day's combined
    strain must exceed a steady 55-minute UT2 piece of the same average HR, with the idle
    tail excluded from the per-sample average via auto-trim."""
    from catch.sync import scoring

    max_hr = 190.0
    resting_hr = 50.0
    warmup_hr, hard_hr = 118.0, 180.0  # UT2 and AN respectively at max_hr=190

    update_settings(session, {"max_hr": max_hr})
    # Noon UTC, not T0's early morning — keeps both sessions safely on the same local
    # calendar day regardless of the system's own timezone offset (the exact class of
    # UTC/local-day boundary bug this codebase has hit before — see scoring.py's
    # _earliest_date comment).
    hard_start = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
    day = hard_start.astimezone().date()
    session.add(DailyWellness(date=day, resting_hr=resting_hr))

    profile_hr = _jitter(warmup_hr, 20 * 60) + _jitter(hard_hr, 10 * 60) + _jitter(warmup_hr, 25 * 60)
    idle_tail = _jitter(60.0, 180)  # watch left running after the session ended
    cadence = [20.0] * len(profile_hr) + [0.0] * len(idle_tail)

    hard = Activity(source="garmin", external_id="qb1", type="indoor_rowing", start=hard_start, duration=float(len(profile_hr)))
    session.add(hard)
    session.commit()
    store_samples(session, hard.id, start=hard_start, hr=profile_hr + idle_tail, power=[None] * len(cadence), cadence=cadence)

    avg_hr = sum(profile_hr) / len(profile_hr)
    assert avg_hr < 133  # the average alone would read as UT2 — the whole point of this fixture
    steady_start = hard_start + timedelta(hours=1)  # same day, a separate, non-overlapping session
    steady = Activity(source="garmin", external_id="qb2", type="indoor_rowing", start=steady_start, duration=float(len(profile_hr)))
    session.add(steady)
    session.commit()
    store_samples(
        session, steady.id, start=steady_start, hr=_jitter(avg_hr, len(profile_hr)),
        power=[None] * len(profile_hr), cadence=[20.0] * len(profile_hr),
    )

    run_matching(session)
    session.refresh(hard)
    session.refresh(steady)

    hard_canonical = session.get(CanonicalActivity, hard.canonical_id)
    assert hard_canonical.auto_trimmed_tail_s == 180.0
    assert not hard_canonical.session_label.startswith("UT2")
    assert hard_canonical.session_label.startswith("AN") or hard_canonical.session_label.startswith("TR")

    steady_canonical = session.get(CanonicalActivity, steady.canonical_id)
    assert steady_canonical.session_label.startswith("UT2")

    # Both sessions landed on the same day — day_strain's per-component values (computed via
    # the exact scoring.py path /api/activities and Today both read) let us compare them.
    strain = scoring.day_strain(session, day, get_settings(session))
    by_canonical = {c["canonical_id"]: c for c in strain["components"]}
    assert by_canonical[hard_canonical.id]["value"] > by_canonical[steady_canonical.id]["value"]


def test_resolve_all_canonicals_picks_up_a_changed_max_hr(session):
    """Regression (advisor-caught): a max_hr change via Settings used to be a silent no-op
    for every already-resolved canonical, since day_strain reads the *cached*
    CanonicalActivity.strain_trimp/zones_json rather than recomputing live, and
    run_matching's own resolve calls only ever touch orphaned/blank/newly-merged canonicals.
    resolve_all_canonicals (wired into PUT /api/settings) must re-resolve everything."""
    update_settings(session, {"max_hr": 190})
    session.add(DailyWellness(date=T0.date(), resting_hr=50))
    activity = Activity(source="garmin", external_id="mh1", type="indoor_rowing", start=T0, duration=1800.0)
    session.add(activity)
    session.commit()
    store_samples(session, activity.id, start=T0, hr=_jitter(150.0, 1800), power=[None] * 1800, cadence=[20.0] * 1800)
    run_matching(session)
    session.refresh(activity)

    canonical_before = session.get(CanonicalActivity, activity.canonical_id)
    zones_before = canonical_before.zones_json
    trimp_before = canonical_before.strain_trimp
    assert zones_before is not None

    # 150 bpm against max_hr=190 is UT1 (78.9%); against a much lower max_hr it reads as a much
    # higher zone, and the Banister HRr (and so trimp) changes too.
    update_settings(session, {"max_hr": 160})
    resolve_all_canonicals(session)

    canonical_after = session.get(CanonicalActivity, activity.canonical_id)
    assert canonical_after.zones_json != zones_before
    assert canonical_after.strain_trimp != trimp_before


def test_cycling_without_power_falls_back_to_hr_banister(session):
    update_settings(session, {"max_hr": 190})
    session.add(DailyWellness(date=T0.date(), resting_hr=50))
    activity = Activity(source="garmin", external_id="bike3", type="indoor_cycling", start=T0, duration=1800.0, avg_hr=150)
    session.add(activity)
    session.commit()

    store_samples(session, activity.id, start=T0, hr=_jitter(150.0, 1800), power=[None] * 1800, cadence=[85.0] * 1800)
    run_matching(session)
    session.refresh(activity)

    canonical = session.get(CanonicalActivity, activity.canonical_id)
    assert canonical.strain_method == "trimp_samples"
    assert canonical.strain_trimp is not None
