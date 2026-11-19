"""Master-key rotation (docs/security.md "Changing the master key").

Every sealed credential records the id of the master that sealed it, and `secret_store` can open blobs sealed by any master listed in
CATCH_SECRETS_MASTER_KEY_PREVIOUS. Rotation is therefore: set the new key as CATCH_SECRETS_MASTER_KEY, move the old one to
..._PREVIOUS, run `catch secrets rotate` (this module — it re-seals every blob under the new master), confirm `catch secrets status`
shows no blob on an old key, then drop ..._PREVIOUS. Plaintext never leaves this module's stack frames, is never logged, and a blob
that can't be opened is reported by owner/provider only and left exactly as it was."""

from __future__ import annotations

from collections import Counter

from sqlmodel import Session, select

from catch.core import secret_store, tenant
from catch.core.models import AiCredential, ProviderConnection
from catch.core.secret_store import SecretStoreError
from catch.sync import connections

CONNECTION_SLOTS = connections._SLOTS


def status(session: Session) -> Counter:
    """Counts of stored blobs by the id of the master that sealed them, for the current owner."""
    counts: Counter = Counter()
    for row in session.exec(select(AiCredential)).all():
        counts[row.key_id] += 1
    for conn in session.exec(select(ProviderConnection)).all():
        if any(getattr(conn, col) for col in CONNECTION_SLOTS.values()) and conn.key_id:
            counts[conn.key_id] += 1
    return counts


def rotate_owner(session: Session, *, dry_run: bool = False) -> dict:
    owner = tenant.current_owner()
    current = secret_store.current_key_id()
    done, skipped, failed = 0, 0, []
    for cred in session.exec(select(AiCredential)).all():
        if not secret_store.needs_reseal(cred.key_id):
            skipped += 1
            continue
        try:
            plain = secret_store.open_sealed(cred.key_enc, owner_id=owner, provider=cred.provider)
        except SecretStoreError:
            failed.append(f"ai:{cred.provider}")
            continue
        if not dry_run:
            cred.key_enc, cred.key_id = secret_store.seal(plain, owner_id=owner, provider=cred.provider)
            session.add(cred)
        done += 1
    for conn in session.exec(select(ProviderConnection)).all():
        if not conn.key_id or not secret_store.needs_reseal(conn.key_id):
            skipped += 1
            continue
        resealed: dict[str, str] = {}
        try:
            for slot, column in CONNECTION_SLOTS.items():
                blob = getattr(conn, column)
                if blob:
                    plain = secret_store.open_sealed(blob, owner_id=owner, provider=connections._scope(conn.provider, slot), purpose=secret_store.CONNECTION_PURPOSE)
                    resealed[column] = secret_store.seal(plain, owner_id=owner, provider=connections._scope(conn.provider, slot), purpose=secret_store.CONNECTION_PURPOSE)[0]
        except SecretStoreError:
            failed.append(f"connection:{conn.provider}")
            continue
        if not dry_run:
            for column, blob in resealed.items():
                setattr(conn, column, blob)
            conn.key_id = current  # one id for the row: every slot was just sealed under it
            session.add(conn)
        done += 1
    if not dry_run:
        session.commit()
    return {"resealed": done, "already_current": skipped, "failed": failed}
