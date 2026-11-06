# Push notifications and monitoring (session 16)

## Web Push, from scratch

`catch/notify/push.py` implements RFC 8291 (message encryption) / RFC 8292 (VAPID) directly
on `py-vapid` + `http-ece` + `httpx`, not the full `pywebpush` package — `pywebpush` itself
transitively pulls in `requests` *and* `aiohttp` (plus aiohttp's compiled deps: multidict/
yarl/frozenlist) for a `.send()` method this app never calls, since the actual POST to the
push service goes through `httpx` directly. The round trip is tested for real in
`tests/notify/test_push.py` — it generates a fake browser subscriber keypair, encrypts a
payload with `push.py`, and decrypts it back with `http_ece.decrypt` using the subscriber's
own private key, which is the actual security property Web Push depends on (only the
holder of the browser-side private key, which never leaves the device, can read the payload).

**VAPID keys** (`VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` in `.env`) are generated once — see
`.env.example`'s exact one-liner. Rotating them invalidates every existing subscription
(every device has to re-subscribe), so do this before any real device has subscribed, not
after. `VAPID_SUBJECT` must be a `mailto:` address or a bare `https://` origin (no path) —
`py_vapid`'s own validation rejects anything else. The public key is served at runtime
(`GET /api/push/vapid-public-key`), never baked into the built JS bundle, since the laptop
that runs `npm run build` doesn't necessarily have the Pi's real `.env`.

## The five notification types

All five live in `catch/notify/triggers.py`, each gated by `_gated_notify` (a type-enabled
toggle + quiet hours, both in `catch/analytics/defaults.py`'s `notifications` settings key —
`GET`/`PUT /api/settings`, edited in Settings → Notifications). Quiet hours (default
22:00–06:00, HH:MM local) suppress **every** type uniformly, including alerts — a suppressed
send is dropped, not queued, except where noted below.

| Type | Trigger | Dedup | Deep link |
|---|---|---|---|
| `morning_brief` | Once a day, 30 min after the trailing-14-day average Garmin wake time (`DailyWellness.wake_time_minutes`, falls back to 7:30 with no history) — see `catch/analytics/wake_time.py`. Calls `run_sync("garmin", days=1)` first so it's never describing yesterday. | Once per day (`NotificationLog`) | `/` |
| `illness` | The moment `catch/sync/scoring.py`'s `recompute_scores` first sets `IllnessAck.first_flagged_at` for a "likely" night. Only considers today's/yesterday's flag (a historical flag from before this feature existed, or any day older than that, is marked handled without ever sending) and re-checks the *current* `daily_scores.illness_json` level in case a later recompute downgraded it. | Once per flagged date (`IllnessAck.notified_at`) | `/` |
| `garmin_key_expiring` | `settings.garmin_key_expires_on` reaches exactly 14, 3, or 1 day(s) out. | Once per day | `/settings/status` |
| `sync_broken` | Either: (a) a source's `SyncState.consecutive_failures` crosses 3 in a row (edge-triggered inside `catch/sync/state.py::record_error` — the *next* failure after 3, 4, 5…, doesn't re-alert); or (b) no successful sync in 36h for a source (`check_sync_stale`, a periodic check — `SyncState.last_success_at` going stale, read as "the sync stopped happening," not "nothing new was there to sync," since Concept2/Withings both run on a schedule regardless of whether they find anything new). | Once per "episode" (`SyncState.alert_sent_at`, cleared on the next success) — a send suppressed by quiet hours leaves this unset, so the next failure/tick retries | `/settings/status` |
| `test_reminder` | An `Event` dated tomorrow with `type == "2k_test"` or (`type == "race" and priority == "A"`), un-resulted. Includes the saved pacing plan's goal time if one exists. | Once per day (bundles multiple same-day events into one notification) | `/tests` |

`catch/sync/scheduler.py`'s `check_notifications` job runs all five every 10 minutes, each
wrapped individually (one failing doesn't block the others, same shape as `run_sync`).

## Subscriptions, devices, the service worker

One `PushSubscription` row per browser/device (`endpoint` is the natural unique key — a
device re-subscribing after e.g. clearing site data always gets a new endpoint from the
browser, there's no stable device id a PWA can read). `catch/api/routes_push.py`:
`subscribe`/`unsubscribe` (keyed on endpoint), `list`, and a per-device `test` send (prunes
the subscription on a 404/410 from the push service — confirmed gone/expired — leaves it
alone on any other failure).

`web/src/lib/push.ts`'s `enablePush()` calls `Notification.requestPermission()` as the very
first thing it does when invoked from a button's `onClick` — any `await` before that first
call (even fetching the VAPID key) loses iOS Safari's "this tap counts as real user
activation" window, so the key is fetched separately, on mount
(`NotificationsCard`). iOS only allows push for the PWA installed to the home screen (16.4+),
detected via `display-mode: standalone` / `navigator.standalone` — there's no official API
for "is this an installed PWA," this is the standard workaround.

The generated service worker (`vite.config.ts`'s `serviceWorkerPlugin` — there's no static
`public/sw.js`, see `CLAUDE.md`) handles `push` (always `showNotification` inside
`waitUntil`, unconditionally — a push that produces no visible notification risks iOS
revoking the subscription after a few repeats) and `notificationclick` (focuses an existing
client and `postMessage`s it the deep link, falling back to `openWindow` — not
`WindowClient.navigate()`, which has real gaps on iOS standalone WebKit; `App.tsx` listens for
that message and navigates via `react-router`).

## Monitoring (`GET /api/status`, Settings → Status)

`catch/api/routes_status.py`: per-source last success/consecutive failures/last error/token
expiry, the Garmin-key-expiry reminder, backup status, disk free, DB size (`catch.db` +
`-wal`/`-shm`), app uptime, and the build/commit from the frontend's own `version.json`.

**Dead-man's-switch pings** (healthchecks.io, free): `HEALTHCHECKS_SYNC_URL` is pinged by
`catch/core/healthchecks.py` after every successful individual-source sync (the three sources
run as independent APScheduler jobs on their own intervals, not as one combined "cycle," so
this is read as "after every successful sync," not "after all three"). `HEALTHCHECKS_BACKUP_URL`
is pinged by `deploy/backup.sh` directly (success, or `/fail` on a real failure) — the backup
runs as a separate systemd timer/oneshot entirely outside the Python app. Suggested check
settings: sync — period ~2h, grace ~1h; backup — period 1 day, grace ~6h. Both no-op (never
error) when unset.

**Off-Pi backup** (`BACKUP_SCP_TARGET`, Pi-only): see `deploy/backup.sh`'s own header comment
for the full design — integrity check, scp to a laptop over Tailscale when it happens to be
reachable (skipped silently, not alerted, when it isn't — no separate hourly retry timer),
remote 30-backup retention, and the `backups/status.json` (temp file + `mv`) the Status page
reads. `deploy/pi-bootstrap.sh` generates the `catch` user's own SSH key for this and prints
the exact laptop-side setup steps.

**ntfy** (`NTFY_TOPIC`, optional second channel for `sync_broken` specifically): a plain POST
to `https://ntfy.sh/<topic>`, no account. Best-effort — a failure here never blocks or fails
the alert path that called it.
