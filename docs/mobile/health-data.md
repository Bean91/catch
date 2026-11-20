# Apple Health and Health Connect (session 30)

Researched from the platform documentation and the plugin's own type definitions (`@capgo/capacitor-health` 8.13), then implemented consent-first.

## Platform facts that shaped the design

| | Apple HealthKit | Android Health Connect |
|---|---|---|
| Can an app tell that read access was denied? | **No.** A denied type simply returns no data. | Yes (granted permissions are listed) |
| Availability check | always on iPhone | needs Android 8+; built in on Android 14+, otherwise a Play Store app (`isAvailable()`) |
| History | no cap | ~30 days unless the app also holds `READ_HEALTH_DATA_HISTORY` (not requested in v1) |
| HRV | **SDNN** | **RMSSD** |
| Permission model | one system sheet, per type | per-type `health.READ_*` permissions declared in the manifest |
| Store requirements | HealthKit capability + `NSHealthShareUsageDescription`; health data may not be used for advertising or sold; no storing in iCloud | Permissions Declaration + Health apps declaration in Play Console; a privacy-policy page reachable from the permission sheet |

Consequences: the UI never says "denied" on iOS (it says "no data returned — check Settings → Health"); Apple Health can **never** feed Catch's `hrv_rmssd` signal
(SDNN is a different quantity — rejected by the server per platform), so HRV is Android-only; no write access is requested on either platform (no
`NSHealthUpdateUsageDescription`; the plugin's ~40 Android permissions are reduced in `AndroidManifest.xml` to the seven Catch reads: exercise, sleep, resting HR, SpO₂, HRV, distance, active calories).

## What is imported

Workouts (type, start/end, distance, energy, **originating app** — no per-workout heart rate: the plugin exposes none), sleep per night with stages, resting HR (daily), SpO₂ (daily mean),
HRV RMSSD (Android). Weight is excluded (Withings owns body composition and a second scale source would conflict).

## Consent flow (Settings → Connections → Apple Health / Health Connect)

1. The person ticks categories on a screen that says exactly what each is, where it goes (Catch's servers, stored with their training data, shown with the recording app,
   not used for advertising, not shared with people or clubs, visible to the AI coach only if allowed in Privacy → AI sharing) and how to stop/delete.
2. "Continue" **records the consent on the server first** (`PUT /api/health/consent`, `health_consents`), then shows the OS permission sheet.
3. The device is read and a **preview** (counts by type, date range, how many were left out as duplicates) is shown. **Nothing has left the phone yet.**
4. "Send to Catch" uploads in server-sized batches (200 workouts / 500 readings). Only then does the first import happen.
5. After that, a foreground sync runs when the app opens/resumes (from a cursor, re-reading the last 2 days, idempotently). No background delivery in v1.
6. Stop sharing (consent revoked: the server refuses imports) and Delete imported data (removes the rows, re-decides the affected days' wellness values, removes canonical activities left with no source unless a piece is attached) are separate buttons.

Server: the import accepts only categories the consent lists, only valid values (ranges, plausible durations, window of 400 days), never echoes a rejected value, and is
per-account (RLS + owner scoping). Throttled (`health` bucket). Account deletion removes everything (owned tables cascade).

Permissions are used strictly. On Health Connect only the types the OS reports as allowed are read — if none were allowed the page says so and offers "Open Health Connect"; the foreground sync re-checks `checkAuthorization` each time, so a permission switched off in system settings stops that type at once. HealthKit cannot report denial, so there the consented list is read and a denied type returns nothing.

Delete paths: the Health data page ("Stop sharing", "Delete imported data…") and Settings → Privacy → "Recovery, sleep and body data" (which also removes imported wellness readings); account deletion removes everything.

## No double counting

1. The client leaves out samples whose recording app is one Catch already syncs from the source **while that provider is connected** (Garmin Connect, Withings Health Mate,
   Concept2, Whoop — one marker table, `analytics/health_import.py::PROVIDER_APP_MARKERS`, which the server returns to the app so both sides use the same list).
2. The server applies the same rule (a hand-built client can't bypass it).
3. Anything left that overlaps another source goes through the existing matching engine (start within 180 s and ≥70 % overlap) into one canonical activity where Garmin/Concept2/Whoop outrank
   the health platforms field by field (`canonical.py` priority: health sources last; HR from a health source only as a last resort). Wellness signals resolve one winner per day by priority
   (Garmin → Whoop → Apple Health → Health Connect), never averaged.

## Provenance

Every imported row keeps its source (`apple_health` / `health_connect`) and, in `raw_json`/reading meta, the recording app. The workout field-source panel and the recovery
inputs list show the provider; the Connections page shows the platform's counts.

## Not verified here

No real HealthKit or Health Connect data was read: the simulators have no sample-injection path used here, so the device side (`buildPreview`) is type-checked and the
server side is tested with fixtures (`tests/tenancy/test_health_import_api.py`, `tests/analytics/test_health_import.py`). Verify on a real iPhone and an Android phone with Health Connect.
The plugin's field mapping (e.g. whether Android reports rowing machine as `rowingMachine`, whether SpO₂ arrives as a fraction) is handled defensively but is a device check.
