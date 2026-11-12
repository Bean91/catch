"""Private Storage bucket for user photos, with per-user folder policies (docs/public-storage.md).

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

BUCKET = "piece-photos"
UID = "(SELECT auth.uid())::text"
FOLDER = "(storage.foldername(name))[1]"


def upgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF to_regnamespace('storage') IS NULL THEN RAISE EXCEPTION 'Supabase Storage is not enabled on this database'; END IF;
    END $$""")
    # Private by default; a 5 MB cap and image-only types are enforced by Storage itself, not just by the client.
    op.execute(f"""INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
        VALUES ('{BUCKET}', '{BUCKET}', false, 5242880, ARRAY['image/jpeg', 'image/png', 'image/webp'])
        ON CONFLICT (id) DO UPDATE SET public = false, file_size_limit = 5242880,
            allowed_mime_types = ARRAY['image/jpeg', 'image/png', 'image/webp']""")
    for cmd, clause in (
        ("select", f"USING (bucket_id = '{BUCKET}' AND {FOLDER} = {UID})"),
        ("insert", f"WITH CHECK (bucket_id = '{BUCKET}' AND {FOLDER} = {UID})"),
        ("update", f"USING (bucket_id = '{BUCKET}' AND {FOLDER} = {UID}) WITH CHECK (bucket_id = '{BUCKET}' AND {FOLDER} = {UID})"),
        ("delete", f"USING (bucket_id = '{BUCKET}' AND {FOLDER} = {UID})"),
    ):
        op.execute(f"DROP POLICY IF EXISTS catch_piece_photos_{cmd} ON storage.objects")
        op.execute(f"CREATE POLICY catch_piece_photos_{cmd} ON storage.objects FOR {cmd.upper()} TO authenticated {clause}")


def downgrade() -> None:
    for cmd in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS catch_piece_photos_{cmd} ON storage.objects")
    # Objects must be deleted through the Storage API (a DELETE here would orphan the files); the bucket row stays.
