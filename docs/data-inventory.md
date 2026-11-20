# Data inventory (session 28)

What Catch stores about a person, where it comes from, where it lives, how long it is kept, who can read it, and whether it can reach an AI
provider. Written from the code (`catch/core/models.py`, the sync clients, `catch/sync/retention.py`), not from intent — when the code and this
file disagree, the code wins and this file is a bug. The user-facing summaries are in `docs/legal/` (drafts, not legally reviewed).

**Two deployments, nothing shared.** *Personal* (a Raspberry Pi, SQLite, one athlete, one owner `"owner"`) and *public* (Supabase Postgres +
Supabase Auth, many users, FastAPI Cloud). This inventory describes the public deployment; the personal install stores the same tables for one
person on their own hardware and has no accounts, no clubs, no leaderboards.

**Access in the public deployment.** Every user-owned table carries `owner_id`; the application filters by it (`catch/core/tenant*.py`) and
Postgres enforces it again with forced row-level security for the `authenticated` role. "Only the owner" below means that pair of controls. The
operator can read any table with the database admin login (a person with the Supabase/FastAPI Cloud credentials — `docs/security.md`
§Operator access). Platform moderators (`CATCH_MODERATOR_IDS`) can read only the moderation views listed under *Social*; no moderator route
touches an owned table (`tests/tenancy/test_structure.py`).

## 1. Categories

| Category | What | Purpose | Source | Storage | Retention | Who can read | Sent to an AI provider? |
|---|---|---|---|---|---|---|---|
| **Identity** | Email, display name (`user_profiles`, a copy of `auth.users`); Supabase Auth holds the email, password hash, sessions, sign-in logs | Sign in, account deletion | The person (sign-up) | Supabase Auth + `catch.user_profiles` | Until account deletion (Supabase Auth's own logs and backups follow Supabase's retention — **verify in the dashboard**) | Owner; operator | Never |
| **Public handle / age class** | A handle, a self-declared age band (adult, U14–U19), guardian-consent tick (`club_profiles`, `public_athletes`, `leaderboard_settings`) | Show on leaderboards and in clubs; apply junior-club and minor rules | The person | Postgres (global tables for what others see; owned table for consent) | Until opt-out / deletion (a moderator-closed result stays as a tombstone) | Owner; other signed-in users see handle + band where published; moderators | Only if the person's own coach chat mentions it |
| **Health: recovery & sleep** | HRV, resting HR, sleep + stages + wake time, respiration, skin temp, SpO₂, stress, body battery, steps, kcal; per-source readings; computed recovery/strain/load/illness | The app's core: recovery, strain, training advice | Garmin, Whoop, Withings (synced with the person's own credentials) | `daily_wellness`, `wellness_readings`, `daily_scores` | Until the person deletes the category or the account | Owner | Only through the `wellness` category, and only if switched on |
| **Health: on-device platforms (session 30)** | Workouts (type, times, distance, energy, the recording app), sleep + stages, resting HR, SpO₂, HRV (Android) read from Apple Health / Health Connect **only for the types the person ticked, after an in-app consent and a preview** (`health_consents` records the consent; imported rows are ordinary `activities` / `wellness_readings` with source `apple_health` / `health_connect`, the recording app in `raw_json` / reading meta) | The same as the provider data they join; shown with provenance | The person's phone | `health_consents` (owned) + the tables above | Until "Stop sharing and delete" (Settings → Connections → Health), the "Recovery, sleep and body data" category delete, or account deletion | Owner | Through the `workouts` / `wellness` categories only if switched on — **if on, it goes to the person's chosen AI provider like any other workout/wellness data** |
| **Health: body** | Weight, fat %, muscle, bone, hydration | Body-composition trends | Withings, manual entry | `body_comp` | As above | Owner | `wellness` category |
| **Workouts** | Activities (HR, power, cadence, zones, distance, calories), 1 Hz sample streams, strokes, pieces/intervals, strength sets, matching decisions, merge log; **`activities.raw_json`** = the provider's whole record (see §3) | Training log, strain, tests, predictions | Garmin, Concept2, Whoop (+ FIT files parsed transiently on public) | `activities`, `canonical_activities`, `activity_samples`, `strokes`, `pieces`, `piece_intervals`, `strength_sets`, `merge_log`, `match_decisions` | Workouts: until account deletion (no per-workout delete UI yet); `merge_log`/`match_decisions` 400 days | Owner | `workouts` category (titles/notes imported from a provider are labelled untrusted) |
| **Location** | GPS fixes (lat/lon/alt/speed/HR), route signatures, start/end coordinates inside `raw_json`, a place name, weather by 0.1° cell | On-water metrics, route history, weather context | Garmin FIT files | `activity_tracks`, `routes`, `activity_weather`; `weather_cells` (global cache, rounded) | Until the person deletes "GPS tracks, routes and weather" or the account. `weather_cells` is a shared cache of weather by rounded cell and day with no person attached; kept | Owner | Summaries only — **never coordinates** (`get_route` returns an area; `workouts` category) |
| **Nutrition** | Food log, custom foods, saved meals, targets; foods looked up by barcode/search | Intake vs. expenditure | The person; Open Food Facts / USDA (lookups send only the barcode or search text) | `food_logs`, `my_foods`, `saved_meals`, `nutrition_targets`, `foods` (shared cache) | Until deleted | Owner (`foods` cache rows from public databases are shared reference data) | `nutrition` category; a meal photo goes only through `photos` |
| **Subjective notes** | Workout notes + RPE, morning check-in sliders, niggle area/severity/note, illness-flag dismissals (free text), strength-set notes | Context for training advice, illness early-warning | The person | `notes`, `checkins`, `illness_acks`, `strength_sets.notes` | Until deleted | Owner | `notes_checkins` category |
| **Coaching text** | Technique notes, coach feedback (+ revisions), planned-workout notes/feedback, event goals/notes | Coach-athlete notes | The person; a coach with a coach token | `technique_notes`, `coach_feedback`, `coach_feedback_revisions`, `planned_workouts`, `events` | Until deleted; feedback soft-deletes keep revisions until account deletion | Owner; a coach sees only what is marked shared | `calendar_library` category |
| **Credentials** | AI provider keys, provider OAuth tokens / Garmin key / Concept2 token, device tokens, push subscriptions | Act for the person against their own accounts | The person | `ai_credentials`, `provider_connections` (AES-256-GCM, per-owner key, AAD = owner+provider+slot), `api_tokens` (SHA-256 hash only), `push_subscriptions`, **`native_push_tokens`** (session 30: APNs/FCM device tokens — a global, catch_api-only table, one account per token, never returned in full by any API) | Until the person disconnects/deletes; device tokens expire (90 d default) | Nobody can read a secret back: no API returns one; the operator holds the master key (`docs/security.md`) | Never |
| **Social: public** | Published leaderboard entries (value, board, verification, age label, weight class, note), club membership/posts/results/prefs | What the person chooses to publish | The person | Global tables `public_*`, `club_*` | Until withdrawal / leaving / deletion; moderation records longer (see §2) | Signed-in users (public boards, club members per club rules); moderators | Reads of other people's public posts can enter chat context labelled untrusted |
| **AI conversations & memory** | Coach messages (incl. saved tool results, which embed health data), remembered facts, goals, settings, usage events (tokens, cost) | The coach's continuity | The person; the model | `coach_conversations`, `coach_messages`, `athlete_facts`, `goals`, `coach_settings`, `ai_usage_events` | Conversations/facts/goals until the person deletes them or the account; `ai_usage_events` 400 days | Owner | The conversation itself is what is sent (see `docs/ai-data-sharing.md`) |
| **Logs & audit** | Notification log; tool-call log (tool, door, write/confirmed/outcome, args hash — no content); sync state; moderation events, club audit, account restrictions + actions, moderator-access log, deleted-account tombstone | Operate the service; accountability | The system | Postgres | `notification_log` 90 d; `tool_call_log` 90 d; resolved `club_reports` 12 m; `club_audit` 24 m (DB-enforced); `moderation_events`, `moderation_actions`, `moderator_access_log` — **no limit set (question for counsel)**; `deleted_accounts` — an opaque id, kept | Owner for their own log rows; moderators for moderation rows | Never |

## 2. Retention in one place

Pruned automatically (`catch/sync/retention.py`, run by the 24 h scheduler on the personal install and the `/internal/tick/retention` job on
public): notification log 90 d · tool-call log 90 d · AI usage events 400 d · merge log 400 d · match decisions 400 d · resolved club reports
12 m · club audit 24 m.

Kept until the person deletes it (Privacy → delete selected data, or account deletion): everything else a person owns.

Kept after account deletion, and why (`catch/api/routes_account.py`, `docs/leaderboards.md` §Moderation, `docs/clubs.md` §Retention): a
moderation decision about a published result and its reason (no longer linked to the person — the account id is nulled), the reason text of club
audit entries (until 24 m), reports a person filed (detached), club posts/sessions/challenges they authored (detached, so a club's history stays
intelligible), and an opaque deleted-account tombstone. Supabase Auth logs and database backups are outside the application's reach.

## 3. Data we receive that we do not need (recommendations)

`activities.raw_json` stores the provider's whole record verbatim. For Garmin, the activity DTO the OpenAPI document describes can carry
**other people's** data and fields Catch never reads: `ownerDisplayName`, `ownerFullName`, `ownerProfileImageUrl*`, `activityLikeAuthors`,
`activityLikeDisplayNames`, `activityLikeFullNames`, `activityLikeProfileImageUrls`, comment/like counts, `requestorRelationship`, plus
start/end coordinates and `locationName`. Concept2 results carry the Concept2 `user_id`, comments and the heart-rate stream. Whoop workouts carry the
scored record.

* **Recommended (not done in this session):** an allowlist at ingest in `garmin_client.py`/`whoop_client.py`/`concept2_client.py` that keeps the
  fields the app reads and drops the social/owner fields. It needs a migration of existing rows and a re-check that nothing reads the dropped
  keys (`routes_analytics.py` already excludes `raw_json` from API responses). Logged as finding F-13 in `docs/security-findings.md`.
* Dates of birth: a Concept2 DOB is read at publish time, reduced to an age band and discarded (`analytics/verification`); never stored.
* The operator's own contact address was being sent to Open Food Facts in a User-Agent; that was removed in this session.

## 4. External parties and what each receives

| Party | Receives | When | Notes |
|---|---|---|---|
| **Supabase** (Auth, Postgres, Storage) | Everything stored (it is the database); email + password hash (Auth) | Always (public) | EU/US region is the operator's choice; backups/PITR per plan; platform logs — verify |
| **FastAPI Cloud** (hosting) | Every request and response in transit; request logs | Always (public) | Log retention 1 day (Hobby) / 14 days (Pro) per `docs/public-setup.md`; verify OAuth callback `?code=` handling in their logs |
| **Garmin** (`personal.connectapi.garmin.com`) | The person's own Personal API key; date-range queries | Each sync | Garmin states the personal key is not for commercial multi-user apps (`docs/garmin-byok.md`) — disclosed in the UI |
| **Withings** (`wbsapi.withings.net`) | OAuth tokens, signed requests | Each sync | No documented token-revocation call: the grant stays live at Withings after disconnect |
| **Whoop** (`api.prod.whoop.com`) | OAuth tokens, scopes | Each sync; revoke on disconnect/deletion | Revocation supported and used |
| **Concept2** (`log.concept2.com`) | Personal token or OAuth token | Each sync | No documented revoke |
| **Apple (APNs) / Google (FCM)** | A notification (title, body, in-app path, type) addressed to a device token | Each push to the store app | Same content as Web Push; only if the operator configured the keys and the person enabled notifications |
| **Open-Meteo** | Latitude/longitude **rounded to 0.1° (~11 km)** and a date; generic User-Agent | Per GPS activity | No identifier; cached per cell-day |
| **Open Food Facts / USDA FDC** | A barcode or search text; the operator's USDA API key | When the person searches/scans | USDA key sits in the query string (known; scrubbed from logs) |
| **AI providers** — Anthropic, OpenAI, Google (Gemini), or the person's own Ollama host | See `docs/ai-data-sharing.md`: the conversation, the memory block, tool results by category, photos | Only on chat / photo / MCP use, with the person's own key, only after consent and per category | Under each provider's own terms; OpenAI is called with `store: false`; Ollama is off on the public deployment |
| **Browser push services** (FCM, Apple, Mozilla, Microsoft) | An encrypted notification (title, body, link) | When a notification fires | Endpoint validated against a fixed host list (`catch/core/netguard.py`) |
| **ntfy.sh**, **healthchecks.io** | Operator alerts (a sync-broken line; an empty ping) | Operator-configured, optional | A capability URL/topic; no person's data intended |
| **OpenStreetMap tile servers** (from the browser) | The viewer's IP address, the tiles (area) being viewed, the site origin | When a map is open | Not proxied by Catch |
| **Google/Apple/etc. sign-in** | — | Not used | Email + password only |

No analytics, error-reporting or advertising service is called from the server or the web app (verified: no third-party script or fetch in
`web/src`, none in `catch/`).

## 5. Storage locations

* Postgres schema `catch` (non-exposed schema; no Data API) — everything above.
* Supabase Storage bucket `piece-photos` (private, per-user folder policies) exists but **piece photos are currently stored in the database**
  (`piece_photos.image`); the Storage purge on deletion is therefore a no-op until that changes (`docs/public-storage.md`).
* The browser: Supabase session in localStorage (documented tradeoff, strict CSP), the service worker's API cache (cleared on sign-out and on a
  different person signing in; never holds credentials/exports — `vite.config.ts` NEVER_CACHE_PREFIXES), the offline gym queue in IndexedDB.
* Process memory only: rate-limit windows, session-liveness cache, redaction registry.
* Personal install only: SQLite file, downloaded FIT files, rotated backups (14 local + one copy to the operator's laptop).
