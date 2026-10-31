from __future__ import annotations

import base64
import hashlib
import hmac
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from catch.core.config import settings

_hasher = PasswordHasher()
_fernet = Fernet(settings.fernet_key.encode()) if settings.fernet_key else None

SESSION_COOKIE_NAME = "catch_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def verify_password(password: str) -> bool:
    try:
        return _hasher.verify(settings.password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def _sign(message: str) -> str:
    sig = hmac.new(settings.session_secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def make_session_cookie() -> str:
    issued_at = str(int(time.time()))
    return f"{issued_at}.{_sign(issued_at)}"


def verify_session_cookie(value: str | None) -> bool:
    if not value or "." not in value:
        return False
    issued_at, _, sig = value.partition(".")
    if not hmac.compare_digest(_sign(issued_at), sig):
        return False
    try:
        age = time.time() - int(issued_at)
    except ValueError:
        return False
    return 0 <= age <= SESSION_MAX_AGE_SECONDS


def encrypt(value: str) -> str:
    if not _fernet:
        raise RuntimeError("CATCH_FERNET_KEY is not set")
    return _fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if not _fernet:
        raise RuntimeError("CATCH_FERNET_KEY is not set")
    return _fernet.decrypt(token.encode()).decode()
