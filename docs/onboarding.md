# First-run setup (session 32)

`/welcome` — six short steps (five before session 34 added privacy), each skippable, for a newly registered account on the public build. Progress is stored on the
person's own `user_profiles` row (`onboarding_state`, `onboarding_step`, `onboarding_json` = the skipped sources,
`onboarding_completed_at`), so it resumes on any device.

## Who sees it

- **New public accounts**: the Supabase sign-up trigger creates the profile with no onboarding state, so `GET /api/me` says
  `onboarding.show = true` and the app sends them from the landing page to `/welcome` once. Every other page stays reachable.
- **Accounts that existed before session 32** were marked completed by migration 0011 and never see it unprompted.
- **The personal Pi** never shows it unprompted (`show` is always false there); Settings → First-run setup → "Run setup again" opens it
  on either build (`/welcome?restart=1`).
- Once completed (or "Skip setup — I'll do this later in Settings"), it is not shown again unless restarted from Settings.

## Steps

1. **Welcome + time zone** — what Catch does, then the home zone, suggested from the device's IANA zone and changeable from the
   browser's own list. Nothing already known (email, name) is asked again.
2. **Connect your sources** — Garmin (the existing BYOK key sheet, shown only when the deployment offers it), Withings, Concept2
   (OAuth or a personal token) and Whoop, each with one line on what it brings. These are the same cards as Settings → Connections; no
   secret is ever shown back. Skipping a source is a tap and is remembered; it can be connected later. An OAuth sign-in started here
   returns to `/welcome` (the signed state cookie carries the fixed word `onboarding`, never a URL) with a plain sentence for
   "connected", "access wasn't granted" or "couldn't be connected"; a failure never blocks Next.
3. **Training basics** — max heart rate, sleep need and (for cyclists) FTP: existing settings only, each optional and range-checked
   before saving.
4. **Your privacy** (session 34) — see "Privacy step" below.
5. **Importing** — `POST /api/onboarding/start-sync` returns at once and runs each connected source's first 30-day window after the
   response (the scheduled sync tick carries on if the process stops). Each source's state is read from `GET /api/connections` every
   5 s. "Go to dashboard" and "Continue" are always enabled: older history keeps importing a month at a time in the background.
6. **All set** — what's connected, what isn't, and the time zone; "Go to my dashboard" completes setup.

## Privacy step (session 34)

Only controls the server enforces appear, and each is the **same control and endpoint as Settings → Privacy**. There is no separate
onboarding privacy store: a choice is saved the moment it is made, resuming re-reads those rows, and completing or skipping setup changes none
of them.

- **Your training and health data** — a statement, not a switch. Workouts, recovery, sleep, heart rate, weight, nutrition and everything a
  connected source sends are private to the account. Catch has no public profile or public workout feed, so there is nothing to turn
  off, and none is invented.
- **AI sharing** — `components/privacy/AiSharingCard`, unchanged (`PUT /api/ai/sharing`, enforced in `coach/ai_sharing.py` for the in-app
  coach and MCP). The disclosure must be acknowledged before any switch works; all seven categories start off and are switched one at a time.
- **Public leaderboards** (public build) — "Off" by default, plus an optional "Join the leaderboards…" that opens the same opt-in form as
  Settings (`components/leaderboards/JoinLeaderboardsForm`, `POST /api/leaderboards/me/opt-in`, which needs an explicit confirm). Joining
  only *allows* publishing: each result still needs its own previewed, confirmed publish, so joining makes nothing public.
- **Clubs** (public build) — a sentence: each club's "show my public results" and "share my numbers" are chosen inside that club and
  start off.
- **No analytics/telemetry switch**, because nothing is collected (docs/data-inventory.md).

Continue and Skip both leave everything as it is. **Resume:** progress is an index. An account saved at the old step 3 ("sync") resumes on
the new step 3, "privacy", which it hasn't seen — intended. Personal build: the step shows the data statement and AI sharing only.

Enforcement tests (real consent rules, not the suite's allow-everything default): `tests/tenancy/test_onboarding_privacy.py`.
- Finishing or skipping setup leaves AI tool calls refused, publishing refused (403) and no public athlete.
- Choices survive resume and restart, and are per account.
- Joining publishes nothing.
- The old index resumes on privacy.

## API

| Route | |
|---|---|
| `GET /api/onboarding` | `{state, step, steps, skipped, completed_at, show}` |
| `PUT /api/onboarding` | `{step?, skipped?, complete?, restart?}` — unknown provider names are dropped |
| `POST /api/onboarding/start-sync` | `{started: [...]}` — connected, not-needing-reconnect sources only |
| `POST /api/connections/{p}/oauth/start?return_to=onboarding` | only `onboarding` (or nothing) is accepted; anything else is 422 |

## Tests

`tests/test_onboarding.py` (persistence and resume, completion sticks, restart, public-only auto-show, start-sync returning at once
and skipping unconnected sources, the `return_to` allow-list and a denied sign-in landing back on setup);
`web/tests/touch/onboarding.spec.ts` (both mobile projects: skip everything, range checks, an existing account never redirected, a
refused sign-in carrying on, no horizontal overflow; session 34: privacy defaults off, a choice kept when leaving and returning, opting in to
leaderboards from setup) and `onboarding-desktop.spec.ts`; `tests/tenancy/test_onboarding_privacy.py` (server-side enforcement).
