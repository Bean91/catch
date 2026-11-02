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
        "hr_pct": {"UT2": 60, "UT1": 70, "AT": 80, "TR": 87, "AN": 93},
        "power_pct": {"UT2": 55, "UT1": 65, "AT": 75, "TR": 85, "AN": 95},
    },
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
    "recovery_weights": {"hrv": 0.4, "resting_hr": 0.25, "sleep": 0.2, "prior_strain": 0.15},
    "recovery_green": 67,
    "recovery_yellow": 34,
    "sleep_need_seconds": 8 * 3600,
    "min_hrv_nights_for_baseline": 7,
    "predict_lookback_days": 180,
    # Today-screen strain gauge target range per recovery band — illustrative coaching
    # defaults (encourage more strain when green, less when red), not a validated standard.
    "strain_targets": {
        "calibrating": [0, 21],
        "green": [10, 16],
        "yellow": [6, 12],
        "red": [0, 8],
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
    # Part E.4 — a zone needs at least this many minutes *or* this fraction of moving time
    # (whichever floor is lower) to lead the session label.
    "min_zone_minutes": 3.0,
    "min_zone_pct": 0.10,
    # Part E.6 — detect a trailing stretch of near-zero movement (cadence/stroke-rate) as
    # "likely watch left running" and exclude it from UI averages; never from stored samples.
    "auto_trim_enabled": True,
    "auto_trim_min_idle_s": 120,
}
