"""Per-owner abuse protection for AI calls. In-memory and single-process by design (the Pi runs
one uvicorn worker); a multi-worker public deployment needs a shared store behind the same
interface — see PLAN.md's session 23 blockers."""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager

REQUESTS_PER_MINUTE = 20
VISION_REQUESTS_PER_MINUTE = 10
ADMIN_REQUESTS_PER_MINUTE = 30  # key validation / model listing — each is a real call to the provider
MAX_CONCURRENT_STREAMS = 2
MAX_MESSAGE_CHARS = 8000
HISTORY_TOKEN_BUDGET = 60_000  # approximate; chars / 4
TURN_WALL_CLOCK_S = 240.0


# Per-minute ceilings by bucket. Sensitive, rarely-repeated actions get a deliberately low one
# (a person doesn't delete an account, mint a token or export their data several times a minute).
BUCKET_LIMITS = {
    "vision": VISION_REQUESTS_PER_MINUTE,
    "admin": ADMIN_REQUESTS_PER_MINUTE,
    "leaderboard": 30,
    "report": 5,
    "club": 60,
    "account": 3,
    "token": 6,
    "tool": 60,
    "push": 10,
    "lookup": 30,
    "weather": 6,
    "oauth_token": 120,  # /authorize, /token, /revoke: per source address, apart from the provider callbacks so one cannot starve the other
    "oauth_register": 10,  # dynamic client registration is unauthenticated: keep it slow, per source address
    "callback": 60,  # keyed per source address, unauthenticated
    "internal": 30,
    "export": 2,
}


class LimitExceeded(Exception):
    def __init__(self, message: str, retry_after_s: int = 0):
        super().__init__(message)
        self.message = message
        self.retry_after_s = retry_after_s


_lock = threading.Lock()
_windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_streams: dict[str, dict[int, float]] = defaultdict(dict)
_next_token = 0
# A slot whose turn was abandoned without its generator being closed (a disconnect that left it
# suspended at a yield) must not lock the owner out until the process restarts.
_SLOT_TTL_S = TURN_WALL_CLOCK_S + 30.0


def _now() -> float:
    return time.monotonic()


def check_rate(owner_id: str, bucket: str = "chat") -> None:
    limit = BUCKET_LIMITS.get(bucket, REQUESTS_PER_MINUTE)
    now = _now()
    with _lock:
        window = _windows[(owner_id, bucket)]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            raise LimitExceeded("You're sending requests faster than Catch allows. Wait a moment and try again.", int(60 - (now - window[0])) + 1)
        window.append(now)


_daily: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def check_daily(owner_id: str, bucket: str, limit: int) -> None:
    """A rolling 24 h ceiling (export, mainly). Per replica and reset by a restart, like everything here; the per-minute bucket
    beside it keeps a burst from getting that far."""
    now = _now()
    with _lock:
        window = _daily[(owner_id, bucket)]
        while window and now - window[0] > 86400:
            window.popleft()
        if len(window) >= limit:
            raise LimitExceeded("You've reached today's limit for this. Try again tomorrow.", int(86400 - (now - window[0])) + 1)
        window.append(now)


def active_streams(owner_id: str) -> int:
    now = _now()
    with _lock:
        slots = _streams[owner_id]
        for token in [t for t, started in slots.items() if now - started > _SLOT_TTL_S]:
            del slots[token]
        return len(slots)


@contextmanager
def stream_slot(owner_id: str):
    global _next_token
    if active_streams(owner_id) >= MAX_CONCURRENT_STREAMS:
        raise LimitExceeded("Too many replies are already being written. Let one finish and try again.", 5)
    with _lock:
        _next_token += 1
        token = _next_token
        _streams[owner_id][token] = _now()
    try:
        yield
    finally:
        with _lock:
            _streams[owner_id].pop(token, None)


def check_message(text: str) -> None:
    if len(text) > MAX_MESSAGE_CHARS:
        raise LimitExceeded(f"That message is too long (limit {MAX_MESSAGE_CHARS:,} characters).")


def reset() -> None:  # tests
    with _lock:
        _windows.clear()
        _streams.clear()


def _approx_tokens(message: dict) -> int:
    return len(json.dumps(message["blocks"])) // 4 + 4


def _turn_starts(history: list[dict]) -> list[int]:
    """Indices where a new user turn begins — a user message with real text, not just tool results.
    Dropping only at these boundaries never separates a tool_call from its tool_result."""
    return [i for i, m in enumerate(history) if m["role"] == "user" and any(b["type"] == "text" for b in m["blocks"])]


def trim_history(history: list[dict], budget_tokens: int = HISTORY_TOKEN_BUDGET) -> list[dict]:
    """Drops the oldest whole turns from what is *sent* until the rest fits; stored history is
    never touched, and the latest turn is always kept."""
    starts = _turn_starts(history)
    total = sum(_approx_tokens(m) for m in history)
    kept_from = 0
    for start in starts[:-1]:
        if total <= budget_tokens:
            break
        next_boundary = next((s for s in starts if s > start), len(history))
        total -= sum(_approx_tokens(m) for m in history[kept_from:next_boundary])
        kept_from = next_boundary
    return history[kept_from:]
