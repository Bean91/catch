"""Per-owner, per-provider encryption for user-supplied AI provider keys.

Not the Pi's single-Fernet arrangement: a key is sealed with AES-256-GCM under a key derived
from a deployment master secret *and the owner id*, and the ciphertext is bound (as AAD) to
`owner|provider`. A blob copied to another owner's or provider's row therefore fails to
decrypt instead of quietly yielding someone else's key. See docs/security.md.

The master secret comes from `CATCH_SECRETS_MASTER_KEY`; on the personal Pi, where that is
unset, it falls back to the existing `CATCH_FERNET_KEY` so no new setup is needed there. The
public deployment must set its own master key in its secret manager, never in the database.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from catch.core.config import settings

FORMAT = "v1"
_INFO = b"catch/ai-credential/v1"


class SecretStoreError(RuntimeError):
    """Never carries key material or ciphertext in its message."""


def _masters() -> list[tuple[str, bytes]]:
    """(key_id, raw secret bytes), current master first, then any previous ones (rotation)."""
    configured = [
        settings.secrets_master_key or settings.fernet_key,
        *[part.strip() for part in settings.secrets_master_key_previous.split(",") if part.strip()],
    ]
    masters = []
    for secret in configured:
        if not secret:
            continue
        raw = secret.encode()
        masters.append((hashlib.sha256(b"key-id:" + raw).hexdigest()[:8], raw))
    return masters


def _derive(master: bytes, owner_id: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=owner_id.encode(), info=_INFO).derive(master)


def _aad(owner_id: str, provider: str) -> bytes:
    return f"{FORMAT}|{owner_id}|{provider}".encode()


def current_key_id() -> str:
    masters = _masters()
    if not masters:
        raise SecretStoreError("No secrets master key is configured (CATCH_SECRETS_MASTER_KEY).")
    return masters[0][0]


def seal(plaintext: str, *, owner_id: str, provider: str) -> tuple[str, str]:
    """Returns (blob, key_id)."""
    key_id = current_key_id()
    master = _masters()[0][1]
    nonce = os.urandom(12)
    ct = AESGCM(_derive(master, owner_id)).encrypt(nonce, plaintext.encode(), _aad(owner_id, provider))
    return f"{FORMAT}.{key_id}.{base64.urlsafe_b64encode(nonce + ct).decode()}", key_id


def open_sealed(blob: str, *, owner_id: str, provider: str) -> str:
    try:
        fmt, key_id, payload = blob.split(".", 2)
        raw = base64.urlsafe_b64decode(payload.encode())
    except Exception as exc:
        raise SecretStoreError("Stored credential is malformed.") from exc
    if fmt != FORMAT:
        raise SecretStoreError("Stored credential has an unsupported format.")
    master = next((raw_master for kid, raw_master in _masters() if kid == key_id), None)
    if master is None:
        raise SecretStoreError("The master key that sealed this credential is not configured.")
    try:
        return AESGCM(_derive(master, owner_id)).decrypt(raw[:12], raw[12:], _aad(owner_id, provider)).decode()
    except InvalidTag as exc:
        raise SecretStoreError("Stored credential could not be verified for this owner and provider.") from exc


def needs_reseal(key_id: str) -> bool:
    return key_id != current_key_id()


def mask(secret: str) -> str:
    """Last four characters only, and only for keys long enough that four characters reveal
    nothing useful. Short strings are never echoed."""
    return secret[-4:] if len(secret) >= 12 else ""
