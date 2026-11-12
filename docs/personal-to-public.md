# Moving a personal install's data into a public account

Optional, one-way, and **never automatic**: nothing in Catch uploads personal data anywhere. You run two commands yourself.

1. **On the Pi** (or wherever the personal database is): `uv run catch export-personal --out catch-export.jsonl.gz`.
   One gzip'd JSON-lines file, streamed table by table (parents first), with a manifest line (counts + SHA-256) last.
2. **Create the public account** (sign up in the public app, confirm the email, sign in once so the profile exists) and find its user id
   (`GET /api/me`, or Supabase → Auth → Users).
3. **Dry run**, with the public environment (`CATCH_DEPLOYMENT=public`, `DATABASE_URL` = the runtime `catch_api` URL):
   `uv run catch import-personal --file catch-export.jsonl.gz --user-id <uuid> --dry-run`
4. **Import**: the same without `--dry-run`. It runs *as that user* under row level security, refuses a file whose checksum doesn't match, and refuses an
   account that already has data.

## What moves, and what doesn't

| Moves (fresh ids, every reference re-pointed) | Does not move |
|---|---|
| workouts + strokes/samples/tracks/routes/weather, canonical workouts, pieces + intervals + photos, wellness (+ readings), body composition, notes, check-ins, illness acknowledgements, events/goals/athlete facts, planned workouts, phases, templates, technique notes, coach feedback, nutrition logs/foods/saved meals/targets, gym sets/stations/templates, settings | **Credentials and device bindings** — OAuth tokens, AI keys, device tokens, push subscriptions, sync cursors: re-create them in the new account · **Derived data** — daily scores and recommendations: recomputed after import · **AI conversations** — they embed opaque tool results; start fresh · coach settings and AI usage |

Seeded reference rows (the exercise library, example templates) are matched to the public database's own copies by their stable external id. Custom exercises and
manual foods come across as the user's own. JSON columns that embed ids (`saved_meals`, `strength_templates`, `workout_templates`/`planned_workouts` structures) are
re-pointed; an id that wasn't carried over becomes `null` rather than pointing at a stranger's row.

## What was verified

`tests/tenancy/test_personal_transfer.py`: a populated personal database exports, a *different* user in a database that already holds another user's colliding ids
imports it, every cross-reference lands on the importer's own rows, credentials are absent, a damaged file is refused, a dry run writes nothing, a second import is
refused. **Not** exercised: an export of a large real database (the real `data/catch.db` here is a 270 KB October copy) or an import into a hosted project.
