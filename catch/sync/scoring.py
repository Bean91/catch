from __future__ import annotations

import json
import logging
import math
import threading
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import defer
from sqlmodel import Session, delete, select

from catch.analytics.checkin import checkin_badness, checkin_recovery_score
from catch.analytics.illness import illness_score
from catch.analytics.load import training_load
from catch.analytics.strain import (
    banister_trimp,
    daily_activity_trimp,
    day_load_strain,
    muscular_trimp_equivalent,
    srpe_load,
    strain_from_load,
    strength_baseline_au,
    strength_session_load,
)
from catch.analytics.wellness_inputs import SIGNALS, RecoveryInputs, baseline_mixed, calibration_status, data_availability, recovery_from_inputs
from catch.core import localtime, tenant
from catch.core.models import Activity, CanonicalActivity, CheckIn, DailyScore, DailyWellness, IllnessAck, Note
from catch.core.settings_store import get_settings

log = logging.getLogger("catch.scoring")

# Session 32: the strain model these rows were computed with. A stored row without it (or with an older one) is recomputed once
# by `ensure_current_model` — personal startup and the public sync tick — so nobody keeps pre-fix numbers.
SCORING_MODEL = 2

_CONFOUND_REASONS = {"alcohol", "travel", "late_night", "vaccine"}
_ON_FOOT = ("running",)
_ON_FOOT_TYPES = ("walk", "hik", "run", "trail")

# Session 32: one lock per owner, waited on (not skipped). The old single process-wide non-blocking lock meant that on the
# public build one user's recompute silently skipped any other user's that ran at the same moment.
_locks_guard = threading.Lock()
_owner_locks: dict[str, threading.RLock] = {}


def _owner_lock(owner: str) -> threading.RLock:
    with _locks_guard:
        lock = _owner_locks.get(owner)
        if lock is None:
            lock = _owner_locks[owner] = threading.RLock()
        return lock


def _ln_hrv(row: DailyWellness) -> float | None:
    if row.hrv_rmssd and row.hrv_rmssd > 0:
        return math.log(row.hrv_rmssd)
    return None


def _overrides(canonical: CanonicalActivity) -> dict:
    return json.loads(canonical.overrides_json) if canonical.overrides_json else {}


def _is_strength(c: CanonicalActivity) -> bool:
    return bool(c.muscular_by_muscle_json) or (c.sport_family == "strength" and bool(c.muscular_load_au))


def _on_foot(c: CanonicalActivity, members: list[Activity]) -> bool:
    if c.sport_family in _ON_FOOT:
        return True
    return any(any(t in (m.type or "").lower() for t in _ON_FOOT_TYPES) for m in members)


class _Range:
    """Everything a recompute over [lo, hi] reads, loaded in a handful of queries instead of ~10 per day (session 32,
    docs/performance.md). Days are the athlete's local days (catch.core.localtime stamps)."""

    def __init__(self, session: Session, lo: date, hi: date) -> None:
        self.wellness = {w.date: w for w in session.exec(select(DailyWellness).where(DailyWellness.date >= lo, DailyWellness.date <= hi)).all()}
        self.wellness_dates = sorted(self.wellness)
        self.checkins = {c.date: c for c in session.exec(select(CheckIn).where(CheckIn.date >= lo, CheckIn.date <= hi)).all()}
        self.checkin_dates = sorted(self.checkins)
        self.note_rpe: dict[date, int] = {}
        for n in session.exec(select(Note).where(Note.date >= lo, Note.date <= hi).order_by(Note.id)).all():
            if n.rpe is not None:
                self.note_rpe[n.date] = n.rpe
        lo_utc, _ = localtime.day_range(session, lo - timedelta(days=1))
        _, hi_utc = localtime.day_range(session, hi + timedelta(days=1))
        canonicals = session.exec(
            select(CanonicalActivity).where(
                or_(
                    (CanonicalActivity.local_date >= lo) & (CanonicalActivity.local_date <= hi),
                    CanonicalActivity.local_date.is_(None) & (CanonicalActivity.start >= lo_utc) & (CanonicalActivity.start < hi_utc),
                )
            ).order_by(CanonicalActivity.start)
        ).all()
        self.by_day: dict[date, list[CanonicalActivity]] = defaultdict(list)
        for c in canonicals:
            day = localtime.day_of(session, c)
            if day is not None and lo <= day <= hi:
                self.by_day[day].append(c)
        ids = [c.id for c in canonicals]
        self.members: dict[int, list[Activity]] = defaultdict(list)
        for i in range(0, len(ids), 500):
            for a in session.exec(select(Activity).options(defer(Activity.raw_json)).where(Activity.canonical_id.in_(ids[i : i + 500]))).all():
                self.members[a.canonical_id].append(a)
        strength: list[tuple[date, float]] = []
        for day, rows in self.by_day.items():
            for c in rows:
                if _is_strength(c) and not _overrides(c).get("exclude_from_totals") and c.muscular_load_au:
                    strength.append((day, c.muscular_load_au))
        strength.sort()
        self.strength_days = [d for d, _ in strength]
        self.strength_au = [au for _, au in strength]
        self.scores = {r.date: r for r in session.exec(select(DailyScore).where(DailyScore.date >= lo, DailyScore.date <= hi)).all()}

    def wellness_before(self, day: date, days: int) -> list[DailyWellness]:
        i, j = bisect_left(self.wellness_dates, day - timedelta(days=days)), bisect_left(self.wellness_dates, day)
        return [self.wellness[d] for d in self.wellness_dates[i:j]]

    def checkins_before(self, day: date, days: int) -> list[CheckIn]:
        i, j = bisect_left(self.checkin_dates, day - timedelta(days=days)), bisect_left(self.checkin_dates, day)
        return [self.checkins[d] for d in self.checkin_dates[i:j]]

    def strength_before(self, day: date, days: int) -> list[float]:
        i, j = bisect_left(self.strength_days, day - timedelta(days=days)), bisect_left(self.strength_days, day)
        return self.strength_au[i:j]


def _daily_movement(r: _Range, day: date, activities: list[CanonicalActivity], settings: dict) -> dict:
    """Non-exercise movement: the day's wearable step/kcal totals minus every logged workout's own share — a Garmin-recorded
    activity's steps and active kcal, and any on-foot workout recorded elsewhere (its steps, or its minutes at walking cadence
    when it has none) — so a walk logged by Whoop or a phone is never counted twice."""
    wellness = r.wellness.get(day)
    if wellness is None or (wellness.steps is None and wellness.active_kcal is None):
        return daily_activity_trimp(None, None, settings)
    exercise_steps, exercise_kcal = 0.0, 0.0
    for c in activities:
        members = r.members.get(c.id, [])
        garmin = [m for m in members if m.source == "garmin"]
        for m in garmin:
            exercise_steps += m.steps or 0
            exercise_kcal += max(0.0, (m.calories or 0.0) - (m.bmr_kcal or 0.0))
        if not garmin and _on_foot(c, members):
            steps = sum(m.steps or 0 for m in members)
            exercise_steps += steps if steps else (c.duration or 0) / 60.0 * settings["daily_activity_steps_per_min"]
            exercise_kcal += c.calories or 0.0
    steps = None if wellness.steps is None else max(0.0, wellness.steps - exercise_steps)
    kcal = None if wellness.active_kcal is None else max(0.0, wellness.active_kcal - exercise_kcal)
    return daily_activity_trimp(steps, kcal, settings)


def _overlap_s(a: CanonicalActivity, b: CanonicalActivity) -> float:
    if a.start is None or b.start is None or not a.duration or not b.duration:
        return 0.0
    lo = max(a.start, b.start)
    hi = min(a.start + timedelta(seconds=a.duration), b.start + timedelta(seconds=b.duration))
    return max(0.0, (hi - lo).total_seconds())


def _drop_unmerged_duplicates(sessions: list[dict], by_id: dict[int, CanonicalActivity], members: dict[int, list[Activity]]) -> None:
    """Two cardio sessions from *different* sources that cover the same time (over half of the shorter one) are one session the
    matcher didn't merge — a watch's auto-detected workout beside the erg's own result, say. Only the larger load counts; the other
    stays listed with `duplicate_of` and no load. Merging (or "not a duplicate") on the Duplicates screen is still the athlete's
    call; this only keeps the day's load honest meanwhile. Lifting is left alone: a strength record with heart rate beside the gym
    log of the same session is exactly the "heart rate + muscular" combination the model intends."""
    cardio = sorted((s for s in sessions if s["kind"] == "cardio" and s.get("load") is not None), key=lambda s: -s["load"])
    kept: list[dict] = []
    for s in cardio:
        a = by_id[s["canonical_id"]]
        sources_a = {m.source for m in members.get(a.id, [])}
        for k in kept:
            b = by_id[k["canonical_id"]]
            sources_b = {m.source for m in members.get(b.id, [])}
            shorter = min(a.duration or 0, b.duration or 0)
            if shorter > 0 and not (sources_a & sources_b) and _overlap_s(a, b) > 0.5 * shorter:
                s["duplicate_of"] = b.id
                s["load"], s["value"], s["trimp_like"], s["components"] = None, None, None, []
                break
        else:
            kept.append(s)


def _day_strain(r: _Range, day: date, settings: dict) -> dict:
    all_day = r.by_day.get(day, [])
    activities = [a for a in all_day if not _overrides(a).get("exclude_from_totals")]
    movement = _daily_movement(r, day, all_day, settings)
    day_rpe = r.note_rpe.get(day)
    max_hr = settings.get("max_hr")
    wellness = r.wellness.get(day)
    resting_hr = wellness.resting_hr if wellness else None
    baseline_au, baseline_source = strength_baseline_au(r.strength_before(day, settings["strength_baseline_days"]), settings)

    sessions = []
    muscular_au = 0.0
    for a in activities:
        # A per-activity RPE (task Part C.1) beats the day's single Note.rpe.
        rpe = _overrides(a).get("rpe", day_rpe)
        minutes = (a.duration or 0) / 60.0
        if a.strain_trimp is not None:
            hr, hr_method = a.strain_trimp, a.strain_method or "trimp_samples"
        else:
            hr, hr_method = banister_trimp(minutes, a.avg_hr, resting_hr, max_hr, settings["trimp_exponent"]), "trimp"
        srpe = srpe_load(rpe, minutes, settings["srpe_to_trimp_scale"])
        entry = {"canonical_id": a.id, "title": a.title, "hr_trimp": hr, "srpe_trimp": srpe, "duration_minutes": minutes}
        if _is_strength(a):
            eq = muscular_trimp_equivalent(a.muscular_load_au, baseline_au, settings)
            load, method = strength_session_load(hr, srpe, eq)
            muscular_au += a.muscular_load_au or 0.0
            entry.update(kind="strength", load=load, method=method, muscular_au=a.muscular_load_au, muscular_equivalent=eq,
                         muscular_load=min(eq, load))
        else:
            load, method = (hr, hr_method) if hr is not None else (srpe, "srpe" if srpe is not None else None)
            entry.update(kind="cardio", load=load, method=method, muscular_load=0.0)
        # A session's own strain, as if it were the day's only load (workout detail); its share of the day is `share`.
        entry["value"] = strain_from_load(load, settings) if load is not None else None
        entry["band"] = None if load is None else ("light" if entry["value"] < 10 else "moderate" if entry["value"] < 14 else "high" if entry["value"] < 18 else "all_out")
        entry["trimp_like"] = load
        entry["components"] = [{"method": method, "trimp_like": load, "duration_minutes": minutes}] if load is not None else []
        sessions.append(entry)

    by_id = {a.id: a for a in activities}
    _drop_unmerged_duplicates(sessions, by_id, r.members)
    rowing = sum(x["load"] for x in sessions if x.get("load") is not None and by_id[x["canonical_id"]].sport_family == "rowing")
    result = day_load_strain(sessions, movement, settings)
    value = result["value"] or 0.0
    shares = result["shares"]
    out = {
        "model": SCORING_MODEL,
        "value": result["value"],
        # The same curve over the sessions alone (no everyday walking): what recovery's "prior-day strain" input has always meant,
        # so its calibration is unchanged by daily movement joining the headline number (docs/analytics.md §4).
        "training_value": strain_from_load(result["load"] - result["daily_activity_load"], settings) if result["value"] is not None else None,
        "band": result["band"],
        "load": result["load"],
        "trimp_like": result["load"],
        "rowing_trimp_like": rowing,
        "components": sessions,
        "cardio": {"value": value * shares.get("cardio", 0.0), "load": result["cardio_load"], "trimp_like": result["cardio_load"],
                   "share": shares.get("cardio", 0.0)},
        "muscular": {"value": value * shares.get("muscular", 0.0), "load": result["muscular_load"], "share": shares.get("muscular", 0.0),
                     "au": muscular_au, "baseline_au": baseline_au, "baseline_source": baseline_source,
                     "explanation": (f"Lifting AU {muscular_au:.0f} against your typical session ({baseline_au:.0f} AU, "
                                     f"{'your own last ' + str(settings['strength_baseline_days']) + ' days' if baseline_source == 'personal' else 'default until 3 sessions'})"
                                     f" = {result['muscular_load']:.1f} TRIMP-equivalent." if muscular_au else "No lifting logged.")},
        "daily_activity": {"value": value * shares.get("daily_activity", 0.0), "share": shares.get("daily_activity", 0.0), **movement},
        "explanation": result["explanation"] if activities or movement["load"] else "No sessions logged.",
    }
    return out


def day_strain(session: Session, day: date, settings: dict) -> dict:
    """One day's strain, loaded on its own (the recompute loop uses the batched `_Range` directly)."""
    lo = day - timedelta(days=max(settings["strength_baseline_days"], 1) + 1)
    return _day_strain(_Range(session, lo, day), day, settings)


def _day_recovery(r: _Range, day: date, settings: dict, strain_cache: dict[date, float | None]) -> dict:
    wellness = r.wellness.get(day)
    rows = r.wellness_before(day, 60)
    hrv_history = [v for v in (_ln_hrv(w) for w in rows) if v is not None]
    rhr_history = [w.resting_hr for w in rows if w.resting_hr is not None]
    prior_day_strain = strain_cache.get(day - timedelta(days=1))
    checkin = r.checkins.get(day)
    today_checkin_score = checkin_recovery_score(checkin.soreness, checkin.stress, checkin.mood, checkin.sleep_quality) if checkin else None
    result = recovery_from_inputs(
        RecoveryInputs(
            today_ln_hrv=_ln_hrv(wellness) if wellness else None,
            hrv_history_ln=hrv_history,
            today_resting_hr=wellness.resting_hr if wellness else None,
            rhr_history=rhr_history,
            today_sleep_seconds=wellness.sleep_seconds if wellness else None,
            prior_day_strain=prior_day_strain,
            today_checkin_score=today_checkin_score,
        ),
        settings,
    )
    result["calibration"] = calibration_status(len(hrv_history), settings)
    result["data_availability"] = _availability(wellness, rows, hrv_history, rhr_history, prior_day_strain, checkin, settings)
    result["baseline_mixed_sources"] = _mixed_sources(rows, ("hrv_rmssd", "resting_hr", "sleep_seconds"))
    return result


def _sources_of(row: DailyWellness | None) -> dict:
    return json.loads(row.field_sources_json) if row is not None and row.field_sources_json else {}


def _mixed_sources(rows: list[DailyWellness], signals: tuple[str, ...]) -> list[str]:
    """Signals whose last seven nights came from more than one provider. A row with no recorded
    source predates provider tracking and counts as Garmin, the only source then."""
    mixed = []
    for signal in signals:
        column = SIGNALS[signal][0]
        nights = [(_sources_of(r).get(signal) or "garmin") for r in rows if getattr(r, column) is not None]
        if baseline_mixed(nights):
            mixed.append(signal)
    return mixed


def _availability(wellness, rows, hrv_history, rhr_history, prior_day_strain, checkin, settings) -> list[dict]:
    sources = _sources_of(wellness)
    today = {
        signal: ((getattr(wellness, column) if wellness else None), (sources.get(signal) or ("garmin" if wellness and getattr(wellness, column) is not None else None)))
        for signal, (column, _) in SIGNALS.items()
    }
    counts = {
        "hrv_rmssd": len(hrv_history),
        "resting_hr": len(rhr_history),
        **{signal: sum(1 for r in rows if getattr(r, column) is not None) for signal, (column, _) in SIGNALS.items() if signal not in ("hrv_rmssd", "resting_hr")},
    }
    return data_availability(
        today=today,
        history_counts=counts,
        prior_strain_available=prior_day_strain is not None,
        checkin_available=checkin is not None,
        settings=settings,
    )


def _day_illness(r: _Range, day: date, settings: dict, prev_deviated_count: int, acr_yesterday: float | None, exclude_dates: set[date]) -> dict:
    """Session 15 Part B. `exclude_dates` (days already flagged "likely", or dismissed with a
    confounding reason) are dropped from every baseline window so a run of illness — or a
    known alcohol/travel/vaccine night — never teaches the baseline that those values are
    normal. `acr_yesterday` must be the *prior* day's training-load figure, so a workout that
    syncs in later today can't retroactively change this morning's flag."""
    window = settings["illness_baseline_window_days"]
    history_rows = [w for w in r.wellness_before(day, window) if w.date not in exclude_dates]
    rhr_history = [w.resting_hr for w in history_rows if w.resting_hr is not None]
    hrv_history = [v for v in (_ln_hrv(w) for w in history_rows) if v is not None]
    resp_history = [w.sleep_respiration_avg for w in history_rows if w.sleep_respiration_avg is not None]
    checkin_history = [
        v for v in (checkin_badness(c.soreness, c.mood) for c in r.checkins_before(day, window) if c.date not in exclude_dates) if v is not None
    ]
    wellness = r.wellness.get(day)
    checkin_today = r.checkins.get(day)
    result = illness_score(
        today_resting_hr=wellness.resting_hr if wellness else None,
        resting_hr_history=rhr_history,
        today_ln_hrv=_ln_hrv(wellness) if wellness else None,
        hrv_history_ln=hrv_history,
        today_resp=wellness.sleep_respiration_avg if wellness else None,
        resp_history=resp_history,
        today_checkin_badness=checkin_badness(checkin_today.soreness, checkin_today.mood) if checkin_today else None,
        checkin_badness_history=checkin_history,
        prev_deviated_count=prev_deviated_count,
        acr=acr_yesterday,
        settings=settings,
    )
    result["baseline_mixed_sources"] = _mixed_sources(history_rows, ("hrv_rmssd", "resting_hr", "sleep_respiration"))
    return result


def day_recovery(session: Session, day: date, settings: dict, strain_cache: dict[date, float | None]) -> dict:
    return _day_recovery(_Range(session, day - timedelta(days=61), day), day, settings, strain_cache)


def _earliest_date(session: Session) -> date | None:
    wellness_min = session.exec(select(DailyWellness.date).order_by(DailyWellness.date)).first()
    stamped = session.exec(select(CanonicalActivity.local_date).where(CanonicalActivity.local_date.is_not(None)).order_by(CanonicalActivity.local_date)).first()
    unstamped = session.exec(
        select(CanonicalActivity).where(CanonicalActivity.local_date.is_(None), CanonicalActivity.start.is_not(None)).order_by(CanonicalActivity.start)
    ).first()
    candidates = [d for d in (wellness_min, stamped, localtime.day_of(session, unstamped) if unstamped else None) if d]
    return min(candidates) if candidates else None


class _Seed:
    def __init__(self, trimp: list[float], rowing: list[float], prior_strain: float | None, prev_acr: float | None,
                 prev_illness_count: int, likely: set[date]) -> None:
        self.trimp, self.rowing, self.prior_strain = trimp, rowing, prior_strain
        self.prev_acr, self.prev_illness_count, self.likely = prev_acr, prev_illness_count, likely


def _seed_from_stored(session: Session, since: date, lookback: int, illness_window: int) -> _Seed | None:
    """The state the chronological loop would have reached on the day before `since`, read back from stored rows — so a write
    that only touches recent days recomputes from that day, not from the first day of history. None (= recompute everything)
    if any needed day is missing or was computed with an older model."""
    span = max(lookback, illness_window)
    first = since - timedelta(days=span)
    rows = {r.date: r for r in session.exec(select(DailyScore).where(DailyScore.date >= first, DailyScore.date < since)).all()}
    earliest = _earliest_date(session)
    trimp: list[float] = []
    rowing: list[float] = []
    likely: set[date] = set()
    prev = None
    day = max(first, earliest) if earliest else first
    while day < since:
        row = rows.get(day)
        if row is None or not row.strain_json:
            return None
        strain = json.loads(row.strain_json)
        if strain.get("model") != SCORING_MODEL:
            return None
        trimp.append(strain.get("trimp_like") or 0.0)
        rowing.append(strain.get("rowing_trimp_like") or 0.0)
        illness = json.loads(row.illness_json) if row.illness_json else {}
        if illness.get("level") == "likely":
            likely.add(day)
        prev = (strain.get("training_value"), json.loads(row.load_json).get("value") if row.load_json else None, illness.get("deviated_count", 0))
        day += timedelta(days=1)
    if prev is None:
        return None
    return _Seed(trimp, rowing, prev[0], prev[1], prev[2] or 0, likely)


_dirty_guard = threading.Lock()
_FULL = object()
_dirty: dict[str, object] = {}  # owner -> earliest day (or _FULL) a waiting caller asked for while a recompute held the lock


def _note_dirty(owner: str, since: date | None) -> None:
    with _dirty_guard:
        prev = _dirty.get(owner)
        if since is None or prev is _FULL:
            _dirty[owner] = _FULL
        else:
            _dirty[owner] = since if prev is None else min(prev, since)


def _take_dirty(owner: str) -> object | None:
    with _dirty_guard:
        return _dirty.pop(owner, None)


def recompute_scores(session: Session, since: date | None = None, *, full: bool = False, wait_s: float = 30.0) -> int:
    """Recompute the cached daily_scores rows, from `since` (or from the earliest day a write in this session touched, which
    catch.core.localtime tracks) through today; everything when neither is known or `full` is set.

    Days before the start are read back from their stored rows to seed the load/illness state, so a check-in recomputes a few
    days, not years; a test asserts the result equals a full recompute. If another recompute for the same person holds the lock
    longer than `wait_s`, this one is handed to it (it re-runs from the earliest day asked for) instead of keeping a request
    waiting — the session-32 replacement for silently skipping.

    This is the one choke point run after every sync, backfill, settings PUT, note/check-in POST and coach-memory write — so it is
    also where GET /api/series's per-owner cache is invalidated."""
    touched = localtime.pending_recompute_from(session)
    if full:
        since = None
    elif since is None:
        since = touched
    elif touched is not None:
        since = min(since, touched)
    owner = tenant.current_owner()
    lock = _owner_lock(owner)
    if not lock.acquire(timeout=wait_s):
        _note_dirty(owner, since)
        log.info("recompute handed to the one already running for this owner")
        return 0
    try:
        count = _recompute(session, owner, since)
        while (more := _take_dirty(owner)) is not None:
            count += _recompute(session, owner, None if more is _FULL else more)
        return count
    finally:
        lock.release()


def _recompute(session: Session, owner: str, since: date | None) -> int:
    """One pass; the caller holds the owner's lock."""
    from catch.sync.matching import run_matching

    run_matching(session)
    matched = localtime.pending_recompute_from(session)
    if matched is not None and since is not None:
        since = min(since, matched)
    settings = get_settings(session)
    earliest = _earliest_date(session)
    if earliest is None:
        return 0
    today = localtime.today(session)
    lookback = settings["load_chronic_days"] * 2
    illness_window = settings["illness_baseline_window_days"]

    seed = None
    start = earliest
    if since is not None and since > earliest:
        seed = _seed_from_stored(session, min(since, today), lookback, illness_window)
        if seed is not None:
            start = min(since, today)
    trimp_series = list(seed.trimp) if seed else []
    rowing_trimp_series = list(seed.rowing) if seed else []
    strain_cache: dict[date, float | None] = {start - timedelta(days=1): seed.prior_strain} if seed else {}
    confound_dates = set(session.exec(select(IllnessAck.date).where(IllnessAck.dismiss_reason.in_(_CONFOUND_REASONS))).all())
    acked = set(session.exec(select(IllnessAck.date)).all())
    illness_exclude_dates: set[date] = set(confound_dates) | (seed.likely if seed else set())
    prev_acr = seed.prev_acr if seed else None
    prev_illness_count = seed.prev_illness_count if seed else 0

    span = max(61, illness_window + 1, settings["strength_baseline_days"] + 1)
    r = _Range(session, start - timedelta(days=span), today)
    now = datetime.now(timezone.utc)
    count = 0
    day = start
    while day <= today:
        strain = _day_strain(r, day, settings)
        trimp_series.append(strain.get("trimp_like") or 0.0)
        rowing_trimp_series.append(strain.get("rowing_trimp_like") or 0.0)
        strain_cache[day] = strain.get("training_value") if "training_value" in strain else strain.get("value")
        load = training_load(trimp_series[-lookback:], settings)
        # Rowing-only load (task Part B.3): the same EWMA over rowing-only load, so cycling/other volume never inflates
        # the number the athlete trains rowing against.
        rowing_load = training_load(rowing_trimp_series[-lookback:], settings)
        recovery = _day_recovery(r, day, settings, strain_cache)
        illness = _day_illness(r, day, settings, prev_illness_count, prev_acr, illness_exclude_dates)
        if illness["level"] == "likely":
            illness_exclude_dates.add(day)
        prev_illness_count = illness["deviated_count"]
        prev_acr = load.get("value")

        row = r.scores.get(day)
        if row is None:
            row = DailyScore(date=day)
            session.add(row)
        row.recovery_json = json.dumps(recovery)
        row.strain_json = json.dumps(strain)
        row.load_json = json.dumps(load)
        row.rowing_load_json = json.dumps(rowing_load)
        row.illness_json = json.dumps(illness)
        row.updated_at = now
        count += 1
        if illness["level"] == "likely" and day not in confound_dates and day not in acked:
            # Insert-only (task Part B.3/B.4): a dismissal, its reason, or a backtest mark is never overwritten later.
            session.add(IllnessAck(date=day, first_flagged_at=now))
            acked.add(day)
        day += timedelta(days=1)

    # A move west can make "today" yesterday: a row dated after today would otherwise linger as a phantom future day.
    session.exec(delete(DailyScore).where(DailyScore.owner_id == owner, DailyScore.date > today))
    session.commit()
    localtime.pending_recompute_from(session)  # this pass's own IllnessAck inserts are already accounted for

    from catch.api.routes_analytics import invalidate_series_cache

    invalidate_series_cache(owner)

    # Session 18 — scoped to `today` only, isolated so a bug in this newer subsystem can't undo the rows committed above.
    try:
        from catch.sync.training_intelligence import generate_recommendations

        generate_recommendations(session, settings, today)
    except Exception:
        session.rollback()
        log.exception("recommendation generation failed")

    return count


def changed_since(session: Session, instant: datetime) -> date:
    """The earliest local day touched by anything written since `instant` (a sync's own start): where its recompute must begin.
    Never later than today, so the current day is always refreshed."""
    from sqlalchemy import func

    days = [localtime.today(session)]
    for model, col in ((CanonicalActivity, CanonicalActivity.local_date), (Activity, Activity.local_date)):
        d = session.exec(select(func.min(col)).where(model.updated_at >= instant)).first()
        if d is not None:
            days.append(d)
    d = session.exec(select(func.min(DailyWellness.date)).where(DailyWellness.updated_at >= instant)).first()
    if d is not None:
        days.append(d)
    return min(days)


def model_is_current(session: Session) -> bool:
    """Whether the newest stored row was computed with SCORING_MODEL (one indexed read). No rows at all counts as current."""
    row = session.exec(select(DailyScore).order_by(DailyScore.date.desc())).first()
    if row is None:
        return True
    try:
        return json.loads(row.strain_json or "{}").get("model") == SCORING_MODEL
    except ValueError:
        return False


def zones_model_is_current(session: Session) -> bool:
    """Session 33: whether the newest workout with cached zones was resolved with the current zone model (heart-rate reserve, basis
    stored). One indexed read; no cached zones at all counts as current."""
    from catch.analytics.zones import ZONES_MODEL

    row = session.exec(
        select(CanonicalActivity.zones_json).where(CanonicalActivity.zones_json.is_not(None)).order_by(CanonicalActivity.start.desc()).limit(1)
    ).first()
    if row is None:
        return True
    try:
        return ((json.loads(row) or {}).get("basis") or {}).get("model") == ZONES_MODEL
    except ValueError:
        return False


def ensure_current_model(session: Session) -> bool:
    """Recompute everything once when the newest stored row predates SCORING_MODEL. Idempotent."""
    if model_is_current(session):
        return False
    recompute_scores(session, full=True)
    return True
