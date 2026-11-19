# Data deletion and retention — DRAFT

> **DRAFT — NOT LEGALLY REVIEWED.** Describes what the code does today; the retention periods are engineering defaults, not legal advice.

## Delete part of your data (Settings → Privacy)

Each is a separate, confirmed request that removes only your own rows: coach conversations; coach memory (facts and goals); GPS tracks, routes and
weather; uploaded photos (and any stored files); notes and check-ins; nutrition logs; recovery, sleep and body data; notification history; AI usage
history. Recovery, sleep and body data come back on the next sync unless you disconnect the source first. Workouts themselves are removed with
your account (a per-workout delete is not built yet).

## Disconnect a source

Connections → Disconnect removes the stored credential and the sync cursor. Whoop access is revoked at Whoop. **Withings, Concept2 and Garmin
publish no revoke call**, so the grant stays active at those services until you remove it there (the app links to where). Imported data stays until
you delete it.

## Delete your account

Settings → Privacy → Delete account. It needs a recent sign-in and typing DELETE. In order: your stored files are removed; Whoop access is
revoked; your public leaderboard rows are removed and clubs you own pass to the longest-standing eligible member or are deleted; reports, appeals
and audit rows that name you are detached; a deleted-account marker is written; your sign-in account is deleted, which removes every row you own
(workouts, health data, notes, nutrition, conversations, settings, saved AI keys and connection credentials, device tokens) in the database. The
steps are safe to retry.

## What remains, and why

* A moderation decision about a published result and its reason, with your identity removed — so a decision stays explainable and cannot be undone by
  republishing under a new account.
* Posts, sessions and challenges you authored in a club, shown without your name — so a club's history is intelligible.
* Reports you filed (detached from you) and an audit trail of moderation actions.
* An opaque deleted-account marker (an id, a time) — so an old sign-in token cannot recreate your profile.
* Database backups and Supabase Auth logs, which the application cannot edit; they age out on the platform's schedule **[operator: state the
  backup/PITR window]**.
* Data already sent to an AI provider or another service you connected is under that service's own policy.

## Automatic retention

Notification log and tool-call log: 90 days. AI usage, merge and match history: 400 days. Resolved club reports: 12 months. Club audit entries: 24
months (the database refuses to delete a newer one). Everything else stays until you delete it.

## Open questions for counsel

Whether moderation records may outlive an account and for how long; erasure-request response times; backup retention after erasure; whether the
tombstone is necessary personal data; treatment of club posts authored by a deleted minor.
