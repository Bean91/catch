# Leaderboards and verified results (session 26)

Public deployment only (the Pi's routes answer 404). Signed-in users only: there are no logged-out pages or endpoints. Everything is in
the existing FastAPI app and PostgreSQL — no separate service.

Code: `catch/analytics/leaderboards.py` and `verification.py` (pure rules), `catch/sync/leaderboards.py` (the athlete-facing service),
`catch/sync/leaderboard_store.py` (the only module that touches the shared tables), `catch/api/routes_leaderboards.py`,
`routes_moderation.py`, `catch/coach/leaderboard_tools.py`, migration `0005`.

## 1. What "verified" means

Three states, decided server-side by `analytics/verification.classify`:

| State | Rule |
|---|---|
| **Verified** | The result was fetched through the athlete's **own** Concept2 connection, **and** its Concept2 `user_id` equals the account that connection authenticated (`provider_connections.account_id`), **and** Concept2's own `verified` flag on the result is `true`. |
| **Provider-linked** | It comes from a source the athlete connected, but not every verified condition holds (flag false or absent, a different Concept2 account, or a typed piece Catch absorbed into a Concept2 result). |
| **Unverified** | Typed or photographed by the athlete (a manual or photo piece). |

"Verified" means **the source can be authenticated**. It does not mean Catch guarantees who rowed the piece, what equipment or conditions
were involved, or the athlete's physical condition. The UI, the coach and the docs all say so. Further rules:

- A **piece is never verified**: it keeps its typed distance, and Concept2's flag covers a whole result, not a window inside it.
- A Garmin link to a Concept2 workout **never raises or lowers** a state. Only the Concept2 member's own values are used.
- Concept2's `verified`, `user_id` and `weight_class` are promoted from `raw_json` to `activities.c2_*` columns on sync; older rows are read
  through the stored payload, so no backfill job is needed.
- **Unconfirmed assumption:** Concept2's documentation for the `verified` flag was read, but every fixture here is synthetic — the flag has
  never been checked against a live result. See PLAN.md "Blockers".
- If an athlete later disconnects Concept2, already-published entries stay as they were published; new ones can't be verified.

## 2. Which results qualify

Only exact matches, never the test center's 2 % suggestion tolerance (a 1,960 m piece is not a 2k):

- Boards: 500, 1,000, 2,000, 5,000, 6,000 m (ranked by time) and 30:00, 60:00 (ranked by distance). `30min_r20` is not a board: its stroke-rate
  cap is Catch's rule, not a Concept2 category.
- A Concept2 result must be a RowErg, a fixed-distance (`FixedDistanceSplits`) or fixed-time (`FixedTimeSplits`) workout, uninterrupted
  (`JustRow`, intervals and other ergs never qualify), with the exact distance or the exact duration.
- Eligibility comes only from the Concept2 `Activity` row's source values. The user's `test_type`/tag overrides are ignored, so a user can't
  change what counts by retyping a test.
- A typed or photographed piece qualifies on its own typed values, on the unverified/provider-linked tier only.

## 3. Ranking and ties

- The ranked value is an **integer**: tenths of a second for the distance boards (lower wins), metres for the timed boards (higher wins).
  Equal means equal, never a float comparison.
- **One best entry per athlete per board.** The athlete key is a keyed hash of the Concept2 user id for verified entries (so two Catch accounts
  connected to the same Concept2 account are one athlete) and of the Catch account otherwise.
- **Standard competition ranking** ("1224"): entries with the same value share a rank and the next rank skips. Order *inside* a tie is a hash
  of the entry's random id — stable, and it reveals nothing (never a date or the order of publication).
- **Only verified entries are ranked** by default. With "include unverified" the rest are listed in a separate, labelled section, ranked among
  themselves, never above a verified entry; an athlete who has a verified entry isn't repeated there.
- A board query reads at most 5,000 entries (documented scale limit); ranking is done in Python over that set.
- The page always states its context: board, age category, weight filter, club, which verification tiers are shown, how many athletes.

## 4. Categories

- **Overall**, **age**, **lightweight/open**, **club**.
- **Weight class** is the result's own `weight_class` as Concept2 recorded it (L/H). "Lightweight" shows only entries whose athlete opted in to
  showing it and whose result Concept2 marked L; "Open" is everyone. No weight value is ever stored or shown. Showing the class is a separate
  opt-in (it implies a body-weight fact).
- **Age** — Catch's own bands (not claimed to equal Concept2's official ranking categories, which should be checked before launch):
  youth **cumulative "under" boards** U14, U15, U16, U17, U18, U19 (U16 = under 16 on the result date; a 14-year-old appears on U15–U19) and
  exclusive adult bands 19–29, 30–39, … 70–79, 80+.
  - Where it comes from: if the Concept2 profile has a date of birth, Catch reads it at publish time, works out the age **on the result date**,
    and keeps **only the band** — never the date of birth. It then **wins** over any self-declared band (so nobody can self-declare into an
    easier youth band); the label says "as reported to Concept2". Otherwise the athlete declares a band themselves ("self-declared"; a declared
    "U16" is treated as 15, the oldest it could be). Both are claims, not proof — Concept2's date of birth is itself self-entered.
  - Not known, or not agreed to be shown → the athlete is on the Overall boards only. The band is not stored on the public row at all unless the
    athlete chose to show it.
- **Clubs** are a name and a join code; being in one is an opt-in and the code is shown once. A club board is the same board filtered to members.
- No gender categories (out of scope).

### Young athletes

Constants in `analytics/leaderboards.py`, listed as overridable decisions (a legal review is a launch blocker):

- `MIN_PUBLISH_AGE = 13` — below that nothing can be published (when an age is known).
- `GUARDIAN_CONSENT_BELOW = 16` — athletes under 16 need a recorded guardian-consent attestation.
- Anyone under 18 (and a self-declared youth band) appears only under a chosen handle or "Anonymous rower", and their date is limited to the year.
- If no age is known, the athlete attests they're old enough before publishing.

## 5. Privacy rules

- **Nothing is public unless the athlete publishes it**, and publishing is an explicit confirmed act: a preview, then `confirm: true` plus the
  preview's hash. The preview and the board rows are built by **one function** (`public_entry_view`), so the preview is exactly the public view;
  if anything changed since the preview, publishing is refused until it is previewed again.
- **Never in any public response** (a sentinel test asserts it end to end for every board, profile, preview and tool): recovery, strain, HRV,
  sleep, resting HR, weight, body composition, nutrition, check-ins, heart rate, power, calories, training history, notes other than a chosen
  public one, the Concept2 result id or user id, the date of birth, an exact date the athlete didn't agree to, the account name or email.
- **Dates**: hidden by default. The athlete chooses none / year / month / day, and the date is truncated **before** the public row is written.
- **Anonymous is a display name, not unlinkability**: an "Anonymous rower" keeps one stable public athlete id, so their results are linkable to each
  other on the profile page (just not to a name).
- **Names**: the athlete's chosen handle (3–24 characters, globally unique case-insensitively, reserved/impersonation words and anything
  link-shaped refused) or "Anonymous rower". Catch's account display name is never used.
- **Notes**: up to 140 characters, no links, public only if ticked.
- The athlete's own view of their results (`/api/leaderboards/me/results`) shows their exact date to them; it is not a public shape.
- Opting out takes every entry down at once, recorded in the history with the reason "you opted out".

## 6. Source changes

Publishing stores a private snapshot (provider, Concept2 user id and result id, original `date_utc`/timezone, the verification inputs and a
digest of the source values). After each Concept2 sync (and whenever the athlete opens their state) every published entry is compared with its
source; if the source changed or vanished the entry is **hidden with a recorded reason** ("The underlying result changed after it was published…")
until the athlete previews and republishes. Edits can't silently change a published number.

## 7. Duplicates

- The same Concept2 result (provider, provider user id, result id) can be published once across the whole system: a global unique key. The
  second attempt — including from another Catch account that synced the same result — gets a generic `409` that doesn't say who owns it.
- The same athlete publishing the same result twice gets a `409`.
- Even two different results of one athlete (or one Concept2 account) occupy one board row: the best.

## 8. Moderation, reports, audit trail, appeals

- Entry status is `active`, `hidden` or `removed`. It lives in a shared table the athlete's role has **no grant on**, so an athlete can't change it
  (or the audit log), only withdraw their own entry.
- **Every** status change goes through one function and writes a `moderation_events` row in the same transaction: who (athlete / moderator /
  system), from → to, a reason code and a **mandatory written reason**. The table is **append-only**: the runtime role can INSERT and SELECT, never DELETE, and may UPDATE only the two
  person-reference columns (so deleting an account can detach the person from the log; no decision's text or status can be rewritten). Nothing is
  hidden, removed or restored without a recorded reason.
- **Reports**: any signed-in user can report another's public result (reason + optional detail). One open report per reporter per entry; 10 per
  user per day; three distinct reporters automatically **hide it for review** (an event with the reason `report_threshold`). Reporters are never
  revealed to the athlete.
- **Moderators** are Supabase user ids in the `CATCH_MODERATOR_IDS` server secret; everyone else gets 404 on `/api/moderation/*`. A moderator
  can hide, remove, restore, or dismiss reports — each with a reason — and can't act on their own result.
- **Appeals**: the athlete sees every event on their entries with its reason and can appeal a hidden or removed entry (one open appeal per
  entry, three open at once). A moderator resolves it **overturned** (the entry is restored through the same function, recorded) or **upheld**
  (recorded), with a reason either way. The athlete sees the outcome and reason in Settings → Leaderboards.
- **Withdrawing can't undo a decision.** Taking down an active entry (or one hidden only because its source changed) records the event and deletes
  the public row. An entry a moderator hid or removed, or the report threshold hid, is **kept as a tombstone** when the athlete asks to take it down
  or opts out: the request is recorded, the entry stays closed, and it keeps its unique key, so withdrawing and publishing again is refused. The
  athlete's way out is an appeal; only an overturned appeal (a moderator) restores it.
- An entry hidden only because its source changed is cleared by the athlete: "Review and publish again" replaces it (recorded as
  `replaced_by_republish`), or "Take down" removes it.

## 9. Rate limits

Counted in the database, so they hold across replicas: 20 publications per athlete per day, 10 reports per user per day, one open report per
(reporter, entry), 3 open appeals. The in-memory limiter (30 requests/minute, 5 reports/minute) only smooths bursts.

## 10. Data and access

- **Owned** (`OwnedStrict`, forced RLS, one owner): `leaderboard_settings` (consent, attestations, display defaults), `result_publications`
  (the private snapshot). Excluded from the personal export.
- **Shared** (no owner column; the runtime role `catch_api` has direct grants, the `authenticated` role has none; every query goes through
  `leaderboard_store` in a fresh session outside any owner's context): `public_athletes`, `public_entries`, `clubs`, `club_members`,
  `moderation_events`, `result_reports`, `appeals`. The public row carries only the allowlisted public fields plus internal keys that are never
  serialized (athlete key, provider ids, age years for the youth boards).
- Publishing writes the shared row, then the owned snapshot; if the second fails the first is removed (it was never confirmed to the athlete).
- Not run: the Postgres side of the shared tables (grants, forced RLS with `TO catch_api` policies, append-only) has migration tests written but
  needs a Supabase stack — see PLAN.md.

## 11. Retention and deletion

Deleting an account removes the athlete's public rows, club memberships, appeals and the owned snapshot (cascade). The moderation log is kept
but detached from the person (`subject_owner_id`/`actor_id` nulled): a moderation decision must remain explainable. Reports the user made lose
their reporter id.

## 12. Surfaces

REST: `/api/leaderboards/*` and `/api/moderation/*` (above). Coach/MCP, read-only, athlete-only: `get_leaderboards`,
`get_public_athlete_profile`, `get_verified_results`. There are deliberately **no** publish/unpublish tools: confirmation is the athlete's own
act in the app (the endpoint demands `confirm` and the preview hash). Web: `/leaderboards`, `/leaderboards/athletes/:id`,
`/settings/leaderboards`, `/settings/moderation`.
