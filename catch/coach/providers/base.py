from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

from catch.core.redact import redact

# Every provider speaks one normalized event stream, regardless of wire format:
#   {"type": "text_delta", "text": str}
#   {"type": "tool_call", "id": str, "name": str, "input": dict, "provider_meta"?: dict}
#   {"type": "usage", "usage": {"input_tokens", "output_tokens", "cache_creation_input_tokens",
#                                "cache_read_input_tokens"}}
#   {"type": "stop", "stop_reason": "end_turn" | "tool_use" | "max_tokens" | "refusal"}
#   {"type": "error", "message": str, "kind"?: ProviderError.kind}
#
# Messages passed in are provider-neutral blocks, not any provider's wire format (see
# catch/coach/chat.py): [{"role": "user"|"assistant", "blocks": [
#     {"type": "text", "text": str} |
#     {"type": "tool_call", "id": str, "name": str, "input": dict} |
#     {"type": "tool_result", "id": str, "output": Any, "is_error": bool}
# ]}]. Storing (and resuming) conversations in this shape is what lets a conversation switch
# providers mid-stream without the stored history being tied to one provider's schema. A
# tool_call block may carry `provider_meta` (e.g. Gemini's thought signature); only the provider
# that wrote it reads it back.

# Session 23: the BYOK providers. Only the first three take a secret API key; Ollama is a base
# URL on the user's own machine.
KEY_PROVIDERS = ("anthropic", "openai", "gemini")
PROVIDER_IDS = ("anthropic", "openai", "gemini", "ollama")

# Output ceiling per assistant response, and the wall-clock budget of one HTTP request.
MAX_OUTPUT_TOKENS = 8000
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 90.0

ERROR_KINDS = ("invalid_key", "rate_limited", "quota", "unavailable", "timeout", "unsupported", "bad_request")

_USER_MESSAGES = {
    "invalid_key": "The provider rejected this API key. It may be wrong, expired or revoked — replace it in Settings → AI Providers.",
    "rate_limited": "The provider is rate-limiting this key right now. Wait a moment and try again, or switch provider.",
    "quota": "The provider says this account is out of quota or credit. Add credit with the provider, or switch provider.",
    "unavailable": "The provider is unavailable right now. Try again shortly, or switch provider.",
    "timeout": "The provider took too long to answer. Try again, or switch provider.",
    "unsupported": "This provider or model doesn't support that feature.",
    "bad_request": "The provider couldn't process that request.",
}


class ProviderError(Exception):
    """A provider failure reduced to a fixed vocabulary. `str(exc)` is always the safe,
    user-facing message — raw provider text and URLs are never carried, so nothing a provider
    echoes back (a key fragment, a request URL) can reach a log, an SSE event or a stored block."""

    def __init__(self, kind: str, message: str | None = None):
        assert kind in ERROR_KINDS, kind
        self.kind = kind
        self.user_message = message or _USER_MESSAGES[kind]
        super().__init__(self.user_message)


def classify_http_status(status: int, body: Any = None) -> ProviderError:
    """Maps an HTTP status (and, for the 429 split, an error body) onto ProviderError. Both
    OpenAI and Anthropic reuse 429 for quota exhaustion, so the body decides."""
    text = redact(json.dumps(body) if not isinstance(body, str) else body).lower() if body else ""
    if status in (401, 403):
        return ProviderError("invalid_key")
    if status == 402 or (status == 429 and any(t in text for t in ("insufficient_quota", "credit_balance", "billing", "spend_limit", "usage_limit", "quota"))):
        return ProviderError("quota")
    if status == 429:
        return ProviderError("rate_limited")
    if status in (408, 504):
        return ProviderError("timeout")
    if status in (500, 502, 503, 529):
        return ProviderError("unavailable")
    if status == 400 and any(t in text for t in ("api_key_invalid", "api key not valid", "invalid api key", "api key expired")):
        return ProviderError("invalid_key")
    if status == 404:
        return ProviderError("bad_request", "The provider doesn't know that model. Pick another model in Settings → AI Providers.")
    return ProviderError("bad_request")


def safe_error_event(exc: ProviderError) -> dict:
    return {"type": "error", "message": exc.user_message, "kind": exc.kind}


@dataclass(frozen=True)
class ProviderCapabilities:
    streaming: bool = True
    tools: bool = True
    vision: bool = False  # provider-level: some model on this provider can read an image
    list_models: bool = True
    validate_key: bool = True
    # Does the provider's public API (with an ordinary key) report a balance or spend? None of the
    # four do as far as the official docs confirm, so the UI never shows one.
    reports_balance: bool = False

    def as_dict(self) -> dict:
        return {
            "streaming": self.streaming,
            "tools": self.tools,
            "vision": self.vision,
            "list_models": self.list_models,
            "validate_key": self.validate_key,
            "reports_balance": self.reports_balance,
        }


@dataclass(frozen=True)
class VisionRequest:
    system: str
    user_text: str
    image_bytes: bytes
    media_type: str
    tool: dict  # {"name", "description", "input_schema"} — the structured result to produce
    max_tokens: int = 2048


class CoachProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def stream_turn(self, *, system_blocks: list[dict], messages: list[dict], model: str) -> AsyncIterator[dict]: ...

    async def list_models(self) -> list[dict]:
        """[{"id", "display_name", "vision": bool | None}] — None means unknown."""

    async def validate(self) -> dict:
        """Cheap credential check that costs no tokens where the provider allows it. Returns
        {"ok": bool, "kind": ProviderError.kind | None, "message": str, "model_count": int | None}."""

    async def vision_structured(self, model: str, req: VisionRequest) -> tuple[dict, dict]:
        """(structured result, normalized usage). Raises ProviderError."""


def zero_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def validation_result(ok: bool, kind: str | None = None, message: str = "", model_count: int | None = None) -> dict:
    return {"ok": ok, "kind": kind, "message": message, "model_count": model_count}


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    first_newline = stripped.find("\n")
    body = stripped[first_newline + 1 :] if first_newline != -1 else stripped[3:]
    return (body[:-3] if body.endswith("```") else body).strip()


def normalize_tool_ids(messages: list[dict]) -> list[dict]:
    """Returns messages whose tool_call ids are unique across the whole history, with each
    tool_result re-pointed at the call it actually answers.

    Synthetic ids (Ollama has none of its own, Gemini's are optional) used to restart from 1 on every
    turn, so a stored conversation can hold several different calls sharing one id. Providers that
    key results by id (Anthropic, OpenAI) reject or mis-pair that, and Gemini's lookup of a result's
    function *name* by id would give turn 1's result turn 2's name. A result answers the calls of the
    assistant message immediately before it, so pairing is positional."""
    seen: set[str] = set()
    pending: dict[str, list[str]] = {}
    out: list[dict] = []
    for msg in messages:
        blocks = []
        if msg["role"] == "assistant":
            pending = {}
            for b in msg["blocks"]:
                if b["type"] == "tool_call":
                    new_id, n = b["id"], 1
                    while new_id in seen:
                        n += 1
                        new_id = f"{b['id']}~{n}"
                    seen.add(new_id)
                    pending.setdefault(b["id"], []).append(new_id)
                    blocks.append({**b, "id": new_id})
                else:
                    blocks.append(b)
        else:
            for b in msg["blocks"]:
                if b["type"] == "tool_result":
                    candidates = pending.get(b["id"])
                    blocks.append({**b, "id": candidates.pop(0) if candidates else b["id"]})
                else:
                    blocks.append(b)
        out.append({**msg, "blocks": blocks})
    return out
