# Garmin: bring your own key (session 25)

**Short version.** Catch connects to Garmin with **your own Garmin Connect Personal API key** — an official, self-service credential that Garmin issues to
you. Nobody running Catch needs Garmin Developer Program approval, and Catch never asks for your Garmin password. Catch does not use any unofficial or
reverse-engineered Garmin interface.

## What Garmin offers (verified against Garmin's own pages, 2026-11)

| Mechanism | What it is | Used by Catch? |
|---|---|---|
| **Personal API key** ([developer.garmin.com/gc-developer-program/personal](https://developer.garmin.com/gc-developer-program/personal/personal-api/)) | You create a key at `connect.garmin.com/app/settings/personalApiToken`, accept Garmin's terms, and pick an expiry of 30, 90, 180 or 365 days. The key is shown **once**. It can't be used directly: `POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token` with `Authorization: ApiKey <key>` returns a 24-hour bearer token (a raw JWT). No refresh tokens — you exchange the key again. Pull-only. | **Yes** — this is the Garmin connection, on the Pi and on the public build. |
| Garmin Connect Developer Program (Starter / Enterprise) | A business programme for organisations building products for many users. Starter is push-only with no historical data; approvals are reported to be paused. | **No.** Not required, never used as a fallback. |
| Unofficial Garmin Connect logins / session scrapers | Reverse-engineered, password- and MFA-based. | **No.** Not implemented, not recommended. |
| Garmin's "Export your data" archive | A user-requested account export (FIT/CSV/JSON) delivered by email. | Not built. A possible future user-controlled import; the format has only been checked in third-party guides. |

## The terms caveat you should read

Garmin's Personal API FAQ says: *"The Personal API is intended for individual Garmin users who want programmatic access to their own data. It is **not
intended for commercial applications serving multiple end users**."* Garmin's pages don't say whether a self-hosted or hosted open-source app may hold a
user's own key on their behalf.

- On a **personal install** (the Pi) there is one user and one key: this is the intended use.
- On a **public deployment** many people each paste their own key into one server. That sits in the grey area above. Catch discloses it on the Garmin card,
  and the operator can switch it off with `CATCH_GARMIN_BYOK_ENABLED=0` (the Garmin card then says it isn't available on this server). Whether to offer it
  is the operator's decision; check Garmin's terms first. Nothing in the code resolves the ambiguity.

## Setting it up (for users)

1. In a browser, sign in to **Garmin Connect (web)** → **Settings → Personal API Key** (`https://connect.garmin.com/app/settings/personalApiToken`).
2. Create a key, accept Garmin's terms, choose how long it lasts, and **copy it immediately** — Garmin shows it only once.
3. In Catch: **Settings → Connections → Garmin → Add your Garmin key.** Paste the key. Optionally enter the expiry date you chose (Garmin doesn't tell
   Catch; Catch uses it to remind you 14, 3 and 1 days before).
4. Catch exchanges the key with Garmin **before** saving anything. A mistyped key is refused and a working key is never replaced by a bad one. On success
   it is stored encrypted (AES-256-GCM, a key derived per user and per purpose) and only its last four characters are ever shown again.
5. Catch imports recent days straight away and your history **in 30-day windows, one per scheduled sync**, so connecting never has to finish a long import
   inside one request. The card says "Importing history from …" until it catches up.

**Replacing a key** (it expired, or you rotated it): *Replace key*, paste the new one. **Disconnecting** removes Catch's copy and stops syncing; what was
already imported stays. Catch **cannot** revoke the key at Garmin — delete it in Garmin Connect to end access completely.

## What Catch reads (and what it can't)

Activities (summary + the original FIT file, parsed for heart-rate, power, cadence, laps and GPS and then, on a public deployment, discarded — nothing is
kept on the server's disk), daily summaries (resting HR, stress, body battery, SpO₂, respiration, steps), sleep and stages, overnight HRV, and weight/body
composition. Every row keeps its source (`garmin`) and the raw summary JSON.

Not available, so reported as such rather than failing silently — see `catch/sync/providers/__init__.py` (the one capability table the UI, the coach and
these docs share):

- **Skin temperature** — absent from Garmin's Personal API spec.
- **Push / webhooks** — Garmin's Personal API is pull-only; Catch polls.
- **Published rate limits and history depth** — Garmin states neither. Catch backs off on a 429 (honouring `Retry-After`) and imports history in small windows.
  A refusal is shown as a status, not a bug.
- **Revoking a key from Catch** — only Garmin Connect can.
- **Keys longer than a year** — Garmin's maximum.

## Troubleshooting

| You see | Meaning | Do |
|---|---|---|
| "Reconnect needed — Garmin rejected the key" | The key expired, was deleted, or was mistyped. Scheduled syncs stop (they'd fail the same way); you're notified once. | Create a new key in Garmin Connect → *Replace key*. Or *Sync now* after fixing it in `.env` on a personal install. |
| "Waiting — provider is rate limiting" | Garmin asked Catch to slow down. | Nothing: Catch retries on its own with growing pauses. |
| "Problem syncing" | A network or Garmin error. | It retries (5 min, 10, 20 … up to 6 h). *Test connection* tells you whether the key still works. |
| "Garmin isn't available on this server" | The operator switched Garmin BYOK off (`CATCH_GARMIN_BYOK_ENABLED=0`). | Ask the operator. |
| Key exchange succeeds but some days are empty | Garmin returned nothing for those days (no device data, or outside what the API serves). | Not a Catch bug; the history window moves on. |

## For operators / developers

- Code: `catch/sync/garmin_client.py` (`exchange_key`, `GarminClient`), the Garmin entry in `catch/sync/providers/__init__.py`, and the generic
  `catch/sync/connections.py`. The rest of Catch only sees "a Garmin connection"; a future official integration replaces the Garmin client and that table
  entry, not the sync engine, routes, UI or tools.
- A **public** deployment never reads `GARMIN_PERSONAL_API_KEY`; the Pi still does (it appears as a connection with "Using the credential in this server's
  environment"). A test asserts both.
- Not verified live: the endpoint set is the one recorded in `docs/garmin-endpoints.md` / `docs/garmin-openapi.json` (the Swagger spec Garmin embeds in its
  docs page, checked against a real account on the Pi in session 1); the per-user flow added here ran only against synthetic fixtures. Garmin's FAQ and
  Personal API pages state no rate limits, history depth or endpoint-level terms, and that is reported as "not published", not guessed.

## Status at the session 31 launch audit (2026-11-20)

- Catch has **no Garmin Connect Developer Program approval**. The public deployment can only offer each user's own Personal API
  key, which this page's terms caveat applies to.
- Whether to offer it at launch is an owner decision (docs/launch-audit.md, blocker B-6). Set `CATCH_GARMIN_BYOK_ENABLED` to `1` or
  `0` **explicitly**. Leaving it unset now logs a startup warning, and Settings/Connections hide Garmin when it is `0`.
- Verified in production: the owner's own key syncs through the per-user connection (last success 2026-11-20 15:07 UTC).
