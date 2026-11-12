# Storage (public deployment)

**Decision: use Supabase Storage for user photos in the public deployment; keep `piece_photos` in SQLite on the Pi.**

## What is stored

Only one thing is a file: the PM5 photo a piece was read from (`piece_photos`, ≤ ~1500 px JPEG after the client's resize). Meal photos are never stored
(estimate, then discard). GPS tracks, strokes and samples are compact database blobs, not files. FIT files are Pi-only (a scale-to-zero host has no documented
persistent disk), so FIT-dependent features are Pi-only for now.

## Why Storage rather than a database column

Postgres `bytea` would work (RLS-protected, backed up with the database) but photos would count against the database size (500 MB on Free) and every backup.
Storage keeps them out of the database and gives short-lived signed URLs. The cost: Storage objects are **not in database backups**, and they block deletion of the
auth user — so account deletion removes them first (`catch/api/routes_account.py::purge_storage`).

## Model

* Bucket **`piece-photos`**, `public = false`, 5 MB limit, `image/jpeg|png|webp` only (enforced by Storage, migration `0003`).
* Object path **`<user id>/<piece id>.jpg`** — the first folder is the owner.
* `storage.objects` policies (`to authenticated`): select/insert/update/delete only where `(storage.foldername(name))[1] = (select auth.uid())::text`.
  Verified against the real Storage API (`tests/pg/test_storage.py`): Bob cannot write into, read from, or sign a URL for Alice's folder; the bucket is not
  readable at its public URL; non-images and oversized files are refused by Storage itself.
* Access is by **short-lived signed URL** (`createSignedUrl`, ≤ 60 s for display) minted with the *user's own* token; the service key is not involved.
  A signed URL can't be revoked individually (delete/rename the object); it expires on its own.
* Health-related photos are never public and are not placed in a public bucket by any code path.

## Limits and retention

Free: 50 MB per file globally (the bucket sets 5 MB); Pro: larger. Check your plan's total-storage quota in the dashboard. Retention is the user's: photos live until the piece or the account is deleted (`DELETE /api/account`
removes the folder; deleting a single piece's photo removes its object). There is no automatic expiry.

## Status

The bucket, policies and account-deletion purge are built and tested. **The piece-photo upload path itself still writes to the database table** in both
deployments; routing it through Storage in the public build (a `BlobStore` with a database and a Storage implementation) is the follow-up — until then, a public
user's PM5 photos sit in `catch.piece_photos` under RLS like any other row.
