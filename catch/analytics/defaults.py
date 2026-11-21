from __future__ import annotations

# Every numeric knob a coach might reasonably want to override lives here, under the single
# key a caller passes in. catch.core.settings_store merges a user's PUT /api/settings patch
# on top of this at read time; these are what ships before anyone touches /api/settings.
# Full rationale for each number is in docs/analytics.md — this module is just the values.
DEFAULT_SETTINGS: dict = {
    # % of max HR / % of 2k watts marking the *lower* bound of each zone, in ascending order.
    # Source: commonly published rowing zone tables (e.g. British Rowing, Concept2 OTW); not
    # physiology we verified against this athlete. Flagged to the user as "defaults, confirm
    # with your coach" wherever a zone table is returned.
    "zones": {
        # % of max HR — used when the athlete picks "% of max HR", or as the stated fallback when no resting HR is known.
        "hr_pct": {"UT2": 60, "UT1": 70, "AT": 80, "TR": 87, "AN": 93},
        # Session 33: % of heart-rate reserve (Karvonen: resting + (max − resting) × %). UT2 59 / UT1 67 / AT 75 / TR 85 are the
        # lower bounds of the GB Rowing Team training matrix's HRR bands as published secondary sources quote it (the matrix PDF
        # itself is no longer online); no published HRR band for AN was found, so 95 is Catch's own choice. docs/analytics.md §3.
        "hrr_pct": {"UT2": 59, "UT1": 67, "AT": 75, "TR": 85, "AN": 95},
        "power_pct": {"UT2": 55, "UT1": 65, "AT": 75, "TR": 85, "AN": 95},
    },
    # Session 33: "hrr" (heart-rate reserve, the default) or "max_pct" (% of max HR).
    "hr_zone_method": "hrr",
    # Session 33: a resting HR the athlete enters to override the measured one (median of the 14 days before each workout).
    "resting_hr": None,
    # Banister TRIMP: duration_min * HRr * 0.64 * e^(trimp_exponent * HRr), HRr = (avg_hr -
    # resting_hr) / (max_hr - resting_hr). 1.92 is Banister's male coefficient (1.67 female);
    # exposed as a flat number rather than a gender field since this is a single-user app.
    "trimp_exponent": 1.92,
    # sRPE fallback (no HR data): RPE(0-10) * duration_minutes = "AU". Scaled so a 60-minute
    # RPE-5 session (sRPE=300) lands near the Banister TRIMP for 60 min at HRr=0.5 (~50 AU),
    # so acute:chronic load doesn't jump when a session happens to lack HR.
    "srpe_to_trimp_scale": 50 / 300,
    # Whoop-style 0-21 strain = min(21, strain_log_a * ln(1 + trimp_like)). Calibrated so
    # trimp_like=50 (moderate ~1h session) -> ~10, trimp_like=250 (very hard, long) -> ~14.
    "strain_log_a": 2.54,
    "load_acute_days": 7,
    "load_chronic_days": 42,
    # Acute:chronic ratio bands, after Gabbett 2016's "sweet spot" framing.
    "acr_bands": {"undertraining": 0.8, "optimal_high": 1.3, "caution_high": 1.5},
    # Seeded from the Concept2 profile's `max_heart_rate` on first Concept2 sync if unset;
    # PUT /api/settings can always override it.
    "max_hr": None,
    # Session 15 (see PLAN.md Part A.2) — "checkin" is additive, not a slice of 1.0 taken
    # from the other four (see catch/analytics/recovery.py's comment): on a day with no
    # check-in the other four behave exactly as before this key existed. ~0.15 target share
    # per the task; its real effective share once added is weight/(1+weight) ≈ 13%.
    "recovery_weights": {"hrv": 0.4, "resting_hr": 0.25, "sleep": 0.2, "prior_strain": 0.15, "checkin": 0.15},
    # Task Part A.3: a training issue (stored as niggle_* fields) lasting this many consecutive days (or more) is flagged to the
    # coach as worth asking about.
    "niggle_flag_min_days": 3,
    "recovery_green": 67,
    "recovery_yellow": 34,
    "sleep_need_seconds": 8 * 3600,
    "min_hrv_nights_for_baseline": 7,
    "predict_lookback_days": 180,
    # Today-screen strain gauge target range per recovery band — illustrative coaching defaults (encourage more strain when
    # green, less when red), not a validated standard. Session 32 moved them up by about one point: ordinary daily movement is
    # now part of the day's one load sum, and 10,000 everyday steps alone read about 8 (docs/analytics.md §4), so "red = rest"
    # must still be reachable on a day with normal walking. The bands keep their old width and order.
    "strain_targets": {
        "calibrating": [0, 21],
        "green": [11, 17],
        "yellow": [7, 13],
        "red": [0, 9],
    },
    # Which table the zone/workout-detail screens default to showing — doesn't change how
    # zones are computed (both are always available), just the default view.
    "zone_mode": "hr",
    "units": "metric",
    # Garmin's personal-API-key swagger spec exposes no key-expiry field (checked
    # docs/garmin-openapi.json — the only "expir*" hit is an unrelated profile-image URL), so
    # this is a user-entered reminder, not data from the API. `GET /api/sync/status`'s
    # `token_expires_at` is the real, API-derived value (the 24h re-exchanged JWT), which is a
    # different thing and labelled separately in the UI.
    "garmin_key_expires_on": None,
    # -- Session 8/12 (see PLAN.md): cross-source matching, Peloton, editing, body comp,
    # samples-based zones/strain. Provenance labels are "garmin" (watch), "peloton" (a
    # Garmin-sourced activity whose FIT file's own creator isn't Garmin — see
    # docs/peloton.md), or "concept2". Task Part A.3's defaults.
    "field_priority": {
        "power": ["peloton", "concept2", "garmin"],
        "cadence": ["peloton", "concept2", "garmin"],
        "title": ["peloton", "concept2", "garmin"],
        "distance_indoor_bike": ["peloton", "garmin"],
    },
    # Cycling TSS-style load (docs/peloton.md) needs a threshold power; estimated from the
    # best 20-minute power x 0.95 when unset, flagged as an estimate in the UI.
    "ftp_watts": None,
    # Part D.2 — default Withings first, Garmin second; "manual" (a user-entered weight,
    # Part D.3) is always the last resort regardless of this order.
    "body_comp_priority": {
        "weight": ["withings", "garmin"],
        "fat_pct": ["withings", "garmin"],
        "muscle_kg": ["withings", "garmin"],
    },
    # Session 23 (docs/analytics.md §30): which provider's value wins for each recovery input when
    # more than one has one. Garmin first so a Garmin-only history scores exactly as before.
    "wellness_priority": {
        "hrv_rmssd": ["garmin", "whoop"],
        "resting_hr": ["garmin", "whoop"],
        "sleep_seconds": ["garmin", "whoop"],
        "sleep_respiration": ["garmin", "whoop"],
        "skin_temp_c": ["whoop", "garmin"],
        "spo2": ["garmin", "whoop"],
    },
    # Part E.4 — a zone needs at least this many minutes *or* this fraction of moving time
    # (whichever floor is lower) to lead the session label.
    "min_zone_minutes": 3.0,
    "min_zone_pct": 0.10,
    # Part E.6 — detect a trailing stretch of near-zero movement (cadence/stroke-rate) as
    # "likely watch left running" and exclude it from UI averages; never from stored samples.
    "auto_trim_enabled": True,
    "auto_trim_min_idle_s": 120,
    # Session 32 (docs/analytics.md §4): one strain curve over one load sum, in TRIMP units. A strength session enters as
    # its muscular AU scaled to the athlete's own typical session, and non-exercise movement as walking-minute TRIMP —
    # nothing is ever added in 0-21 space. See catch/analytics/strain.py's day_load_strain.
    #
    # A *typical* strength session for this athlete (the median of their own sessions' AU over `strength_baseline_days`)
    # counts as `strength_ref_trimp` — the session-RPE TRIMP of a hard hour of lifting: RPE 7 x 60 min x srpe_to_trimp_scale
    # (50/300) = 70, about a steady hour's row (~77). So kilograms lifted only matter relative to the athlete's own norm.
    "strength_ref_trimp": 70.0,
    "strength_baseline_days": 56,
    "strength_baseline_min_sessions": 3,
    # Until three sessions exist: ~4 exercises x 4 sets x 5 reps x 60 kg x the 7-reps-in-reserve intensity factor (0.81).
    "strength_default_baseline_au": 4000.0,
    # One session can count at most this many typical sessions (a mis-typed 1000 kg set can't dominate a day).
    "strength_session_cap_ratio": 2.5,
    # Non-exercise steps -> minutes of easy walking (100 steps/min) -> Banister TRIMP/min at 25 % heart-rate reserve
    # (0.25 x 0.64 x e^(1.92 x 0.25) ≈ 0.26 per minute; casual walking sits around 20-30 % HRR). Active kcal is used only
    # when steps are missing, at 4 kcal per walking minute. Capped so a very long walking day stays below a hard session.
    "daily_activity_steps_per_min": 100.0,
    "daily_activity_hrr": 0.25,
    "daily_activity_kcal_per_min": 4.0,
    "daily_activity_trimp_cap": 40.0,
    # Pre-session-32 knobs, no longer read (kept so a stored settings patch that names them still validates).
    "daily_activity_strain_cap": 1.5,
    "daily_activity_strain_weight": 1.0,
    "muscular_strain_log_a": 1.1,
    "muscular_strain_weight": 1.0,
    # Session 15 (see PLAN.md Part B) — illness early-warning. Each signal is a z-score vs.
    # its own trailing 30-night baseline (excluding today, excluding nights already flagged
    # "likely", and excluding nights dismissed with a confounding reason — see
    # catch/sync/scoring.py's illness loop), gated behind a minimum number of baseline
    # nights so a brand-new signal (check-in mood/soreness, or early in this app's life)
    # never contributes before it has enough history to mean anything.
    "illness_sd_threshold": 1.5,
    "illness_baseline_window_days": 30,
    "illness_min_baseline_nights": 14,
    "illness_min_checkin_baseline": 5,
    # A noise floor per signal's standard deviation — resting HR and whole-day respiration
    # are reported as integers (e.g. 47-51 bpm), so a real 1-2 unit day-to-day wobble could
    # otherwise look like >1.5 SD on its own. ln(HRV)'s floor is in log-space.
    "illness_sd_floor_rhr": 1.5,
    "illness_sd_floor_resp": 0.5,
    "illness_sd_floor_hrv_ln": 0.05,
    # "likely" requires 2-night persistence (see catch/analytics/illness.py) *and* is capped
    # back to "watch" when that persistence is itself explained by training load rather than
    # illness — i.e. ACR already above this threshold with no non-training signal (nightly
    # respiration or check-in) also deviating. A dedicated setting, not silently borrowed from
    # `acr_bands`, so tuning one doesn't quietly retune the other.
    "illness_acr_high_threshold": 1.3,
    # Session 16 (see PLAN.md Part A) — push notification preferences. Quiet hours suppress
    # every type uniformly, alerts included — a suppressed send is simply dropped, not
    # queued for later (task gives no "deliver once quiet hours end" requirement, and queuing
    # would need its own staleness handling — e.g. a morning-brief recovery number computed
    # hours ago). Times are "HH:MM" local (the Pi's own system timezone, same assumption
    # catch/sync/scoring.py already makes for "today").
    "notifications": {
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "06:00",
        "types": {
            "morning_brief": True,
            "illness": True,
            "garmin_key_expiring": True,
            "sync_broken": True,
            "test_reminder": True,
        },
    },
    # Session 18 (see PLAN.md) — training intelligence & recommendations. Flat, one level
    # deep: catch.core.settings_store._validate_patch only checks one level of nesting (the
    # top key, then — if its default is a dict — the immediate child keys), matching
    # "notifications.types" above, so a second level of nesting here would silently bypass
    # that validation rather than trigger it.
    # Session 21 (see PLAN.md, docs/calendar.md): calendar planning. Flat, one level deep, for the
    # same _validate_patch reason as "training_intelligence" below.
    "planning": {
        # A planned week this many percent above (or below) the reference week/average is
        # flagged for review — see catch.analytics.planning.workload_change_flags.
        "review_threshold_pct": 25,
    },
    "training_intelligence": {
        # Stand-in for "sessions completed vs. planned" — no training-plan/calendar
        # subsystem exists in this app (an Event is a race/test, not a weekly plan). docs/
        # analytics.md §26 documents this as a deliberate scope limit, not a hidden gap.
        "target_sessions_per_week": 5,
        "target_minutes_per_week": 300,
        "consistency_lookback_weeks": 8,
        # A week with >= this share of its volume on <=2 days is "unusually concentrated."
        "concentrated_block_max_day_share": 0.6,
        # Independently tunable from acr_bands.caution_high (which only drives the Trends
        # badge color) — this is a distinct alert threshold for the overload *warning*.
        "overload_acr_threshold": 1.5,
        "overload_min_consecutive_days": 3,
        # An A/B event within this many days suppresses any training suggestion that would
        # add load — never recommend loading up right before a race/test.
        "overload_suppress_near_event_days": 5,
        # == recovery_yellow by default; a dedicated key so tuning one doesn't retune the other.
        "recovery_suggestion_recovery_max": 34,
        # Shorter than recommendation_cooldown_days — recovery state changes daily, so a
        # recovery suggestion should be free to re-fire the next day.
        "recovery_suggestion_cooldown_days": 3,
        "data_quality_min_history_days": 14,
        # Mirrors erg_test.py's project_time() own refusal threshold (<3 points), exposed as
        # a knob here rather than duplicated as a new constant.
        "data_quality_min_pieces_for_trend": 3,
        "data_quality_missing_hr_pct_threshold": 0.5,
        "data_quality_lookback_sessions": 10,
        "recommendation_cooldown_days": 7,
        "confidence_days_medium": 28,
        "confidence_days_high": 84,
        "confidence_pieces_high": 6,
        # A bucket's avg stroke rate up by more than this fraction between two compared
        # pieces -> "possible pacing/rate change" rather than "likely real improvement."
        "rate_delta_material_pct": 0.05,
        "piece_trend_lookback_days": 365,
    },
    # Session 20 (see PLAN.md, docs/analytics.md §28) — GPS filtering, splits, route matching
    # and weather. Flat, one level deep, for the same _validate_patch reason as above.
    # Thresholds are illustrative defaults checked against this account's real rowing_v2 FIT
    # files, not validated constants.
    "on_water": {
        # Pair speeds below this are "stopped": that time isn't moving time and that distance
        # isn't moving distance (total distance still counts every pair — see gps.filter_track).
        "moving_speed_min_mps": 0.5,
        # Peak speed is the best chord speed over at least this long a stretch, not a single
        # fix-to-fix pair (which one noisy fix can inflate).
        "peak_window_s": 10,
        # A gap is dt > max(gap_median_multiple x median dt, gap_min_s); distance is never
        # interpolated across one.
        "gap_min_s": 30,
        "gap_median_multiple": 10,
        # N consecutive "impossible" points that agree with each other are a genuine
        # relocation (GPS lost then re-acquired), not noise — a new segment starts there.
        "reanchor_consecutive_points": 3,
        # Implied-speed ceilings for the impossible-jump filter, m/s.
        "speed_ceiling_rowing_mps": 10,
        "speed_ceiling_running_mps": 12,
        "speed_ceiling_walking_mps": 6,
        "speed_ceiling_cycling_mps": 25,
        "speed_ceiling_paddling_mps": 8,
        "speed_ceiling_other_mps": 15,
        "split_m_rowing": 500,
        "split_m_running": 1000,
        "split_m_cycling": 5000,
        "split_m_other": 1000,
        "pace_consistency_min_splits": 4,
        # Route alignment (catch/analytics/routes.py).
        "route_endpoint_tol_m": 150,
        "route_length_ratio_tol": 0.10,
        "route_coverage_min": 0.9,
        "route_coverage_dist_m": 50,
        "route_max_gap_fraction": 0.2,
        "weather_enabled": True,
    },
}
