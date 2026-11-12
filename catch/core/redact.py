"""Scrub secrets out of any text that is about to be logged, stored or sent to a client.

Two layers: shape-based patterns for well-known key formats and credential-carrying URL
parts, and a runtime registry of the exact secrets the process has decrypted (so a key with an
unfamiliar shape is still caught). Applied to provider error messages, the chat `error` events,
tool-error blocks stored with a conversation, sync-error text, and every log record.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    (re.compile(r"(?i)([?&](?:api[_-]?key|key|access_token|token|secret|client_secret|code)=)[^&\s'\"]+"), r"\1[redacted]"),
    (re.compile(r"(?i)\b(x-api-key|x-goog-api-key|authorization|api-key)(['\"]?\s*[:=]\s*['\"]?)[^\s,'\"}]+"), r"\1\2[redacted]"),
    (re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]*@"), r"\1[redacted]@"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[redacted]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "[redacted]"),
    # Session 24: a Supabase access/refresh JWT (header.payload.signature, all base64url), Supabase's secret
    # keys, and a database URL's password.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[redacted]"),
    (re.compile(r"\bsb_secret_[A-Za-z0-9_-]{8,}"), "[redacted]"),
    (re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://)[^/\s:@]+:[^/\s@]*@"), r"\1[redacted]@"),
]

_lock = threading.Lock()
_registered: OrderedDict[str, None] = OrderedDict()
# Rotating tokens (Whoop's access token changes hourly) register a new secret each time; the oldest
# fall out so the set — scanned on every log record — stays small.
_MAX_REGISTERED = 64
_MIN_REGISTERED_LEN = 8


def register_secret(value: str | None) -> None:
    if value and len(value) >= _MIN_REGISTERED_LEN:
        with _lock:
            _registered[value] = None
            _registered.move_to_end(value)
            while len(_registered) > _MAX_REGISTERED:
                _registered.popitem(last=False)


def forget_secret(value: str | None) -> None:
    with _lock:
        _registered.pop(value or "", None)


def redact(text: object) -> str:
    out = str(text)
    with _lock:
        known = sorted(_registered, key=len, reverse=True)
    for secret in known:
        if secret in out:
            out = out.replace(secret, "[redacted]")
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def _scrub_record(record: logging.LogRecord) -> None:
    try:
        message = record.getMessage()
    except Exception:
        return
    scrubbed = redact(message)
    if scrubbed != message:
        # Keep the record's args as args when we can: uvicorn's access formatter unpacks exactly five of them, and
        # flattening them to a bare string made it raise on every request whose URL carried a `code=` parameter.
        if isinstance(record.args, tuple) and record.args and isinstance(record.msg, str):
            args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
            try:
                rebuilt = record.msg % args
            except Exception:
                rebuilt = None
            if rebuilt == scrubbed:
                record.args = args
                scrubbed = None
        if scrubbed is not None:
            record.msg = scrubbed
            record.args = ()
    if record.exc_info and record.exc_info[1] is not None:
        import traceback

        record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
        record.exc_info = None


_installed = False


def install_log_filter() -> None:
    """A record factory, not a Filter: a logger-level filter never sees records propagated from
    child loggers, and handler filters depend on which handlers exist. The factory runs for every
    record in the process."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        _scrub_record(record)
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
