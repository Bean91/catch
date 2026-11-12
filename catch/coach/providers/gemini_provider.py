"""Google Gemini over plain httpx (generativelanguage.googleapis.com, v1beta).

The API key travels in the `x-goog-api-key` header, never `?key=`: httpx puts the request URL in
its exception text, and a key in a URL ends up in logs and tracebacks. See docs/ai-providers.md
for what was confirmed against the live docs (and what wasn't: `alt=sse`, error statuses,
per-model capabilities) and tests/fixtures/ai/gemini_*.json (shaped from the docs).
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from typing import Any, AsyncIterator

import httpx

from catch.coach import tools as tools_module
from catch.coach.providers.base import (
    CONNECT_TIMEOUT_S,
    MAX_OUTPUT_TOKENS,
    READ_TIMEOUT_S,
    ProviderCapabilities,
    ProviderError,
    VisionRequest,
    classify_http_status,
    normalize_tool_ids,
    safe_error_event,
    strip_code_fence,
    validation_result,
)

BASE_URL = "https://generativelanguage.googleapis.com"

# Function parameters accept "a select subset of an OpenAPI 3.0 schema object". Keep only the
# keywords that subset is documented to have and convert JSON-Schema-isms (type arrays,
# additionalProperties) rather than send something the API may reject.
_ALLOWED_SCHEMA_KEYS = {"type", "format", "description", "nullable", "enum", "properties", "required", "items", "minItems", "maxItems", "minimum", "maximum", "anyOf", "title"}


_MODEL_ID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _model_path(model: str) -> str:
    if not _MODEL_ID.match(model or ""):
        raise ProviderError("bad_request", "That doesn't look like a valid Gemini model id.")
    return f"/v1beta/models/{model}"


def sanitize_schema(schema: Any) -> Any:
    if isinstance(schema, list):
        return [sanitize_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            out["type"] = non_null[0] if non_null else "string"
            if "null" in value:
                out["nullable"] = True
        elif key == "properties" and isinstance(value, dict):
            out["properties"] = {k: sanitize_schema(v) for k, v in value.items()}
        elif key in ("items", "anyOf"):
            out[key] = sanitize_schema(value)
        elif key in _ALLOWED_SCHEMA_KEYS:
            out[key] = value
    return out


def to_function_declarations() -> list[dict]:
    return [
        {"name": t["name"], "description": t["description"], "parameters": sanitize_schema(t["input_schema"])}
        for t in tools_module.anthropic_tool_schemas()
    ]


def to_gemini_contents(messages: list[dict]) -> list[dict]:
    """functionResponse needs the tool's *name*, which neutral tool_result blocks don't carry —
    it is looked up from the matching tool_call earlier in the history."""
    messages = normalize_tool_ids(messages)  # ids are unique and results pair with their own call
    names: dict[str, str] = {}
    for msg in messages:
        for block in msg["blocks"]:
            if block["type"] == "tool_call":
                names[block["id"]] = block["name"]
    contents: list[dict] = []
    for msg in messages:
        parts: list[dict] = []
        for block in msg["blocks"]:
            if block["type"] == "text":
                if block["text"]:
                    parts.append({"text": block["text"]})
            elif block["type"] == "tool_call":
                part: dict[str, Any] = {"functionCall": {"name": block["name"], "args": block["input"]}}
                signature = (block.get("provider_meta") or {}).get("gemini_thought_signature")
                if signature:
                    part["thoughtSignature"] = signature
                parts.append(part)
            elif block["type"] == "tool_result":
                output = block["output"]
                parts.append(
                    {"functionResponse": {"name": names.get(block["id"], "unknown_tool"), "response": output if isinstance(output, dict) else {"output": output}}}
                )
        if parts:
            contents.append({"role": "model" if msg["role"] == "assistant" else "user", "parts": parts})
    return contents


def normalize_usage(meta: dict | None) -> dict:
    meta = meta or {}
    cached = meta.get("cachedContentTokenCount") or 0
    return {
        "input_tokens": max((meta.get("promptTokenCount") or 0) - cached, 0),
        # Thinking tokens are billed as output.
        "output_tokens": (meta.get("candidatesTokenCount") or 0) + (meta.get("thoughtsTokenCount") or 0),
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": cached,
    }


class GeminiProvider:
    name = "gemini"
    capabilities = ProviderCapabilities(streaming=True, tools=True, vision=True)

    def __init__(self, api_key: str, *, base_url: str = BASE_URL, transport: httpx.AsyncBaseTransport | None = None):
        self._api_key = api_key
        self._base_url = base_url
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"x-goog-api-key": self._api_key},
            timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
            transport=self._transport,
        )

    @staticmethod
    def _error_from(resp: httpx.Response, body: bytes | None = None) -> ProviderError:
        try:
            payload = json.loads(body if body is not None else resp.content)
        except Exception:
            payload = None
        return classify_http_status(resp.status_code, payload)

    @staticmethod
    def _transport_error(exc: Exception) -> ProviderError:
        return ProviderError("timeout") if isinstance(exc, httpx.TimeoutException) else ProviderError("unavailable")

    def _synthetic_id(self) -> str:
        return f"gemini_call_{uuid.uuid4().hex[:10]}"

    async def list_models(self) -> list[dict]:
        out: list[dict] = []
        token = None
        try:
            async with self._client() as client:
                for _ in range(10):
                    params = {"pageSize": 100, **({"pageToken": token} if token else {})}
                    resp = await client.get("/v1beta/models", params=params)
                    if resp.status_code != 200:
                        raise self._error_from(resp)
                    payload = resp.json() or {}
                    for m in payload.get("models") or []:
                        if "generateContent" in (m.get("supportedGenerationMethods") or []):
                            out.append({"id": (m.get("name") or "").removeprefix("models/"), "display_name": m.get("displayName") or m.get("name"), "vision": None})
                    token = payload.get("nextPageToken")
                    if not token:
                        break
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from None
        return [m for m in out if m["id"]]

    async def validate(self) -> dict:
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return validation_result(False, exc.kind, exc.user_message)
        return validation_result(True, None, "Connected", len(models))

    async def test_connection(self) -> dict:
        result = await self.validate()
        return {"ok": True, "model_count": result["model_count"]} if result["ok"] else {"ok": False, "error": result["message"], "kind": result["kind"]}

    async def stream_turn(self, *, system_blocks: list[dict], messages: list[dict], model: str) -> AsyncIterator[dict]:
        try:
            path = _model_path(model)
        except ProviderError as exc:
            yield safe_error_event(exc)
            return
        body = {
            "systemInstruction": {"parts": [{"text": "\n\n".join(b["text"] for b in system_blocks)}]},
            "contents": to_gemini_contents(messages),
            "tools": [{"functionDeclarations": to_function_declarations()}],
            "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS},
        }
        tool_calls: list[dict] = []
        usage_meta: dict = {}
        finish = None
        try:
            async with self._client() as client:
                async with client.stream("POST", f"{path}:streamGenerateContent", params={"alt": "sse"}, json=body) as resp:
                    if resp.status_code != 200:
                        raise self._error_from(resp, await resp.aread())
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload:
                            continue
                        chunk = json.loads(payload)
                        usage_meta = chunk.get("usageMetadata") or usage_meta
                        for candidate in chunk.get("candidates") or []:
                            for part in (candidate.get("content") or {}).get("parts") or []:
                                if part.get("thought"):
                                    continue
                                if "text" in part and part["text"]:
                                    yield {"type": "text_delta", "text": part["text"]}
                                elif "functionCall" in part:
                                    fc = part["functionCall"]
                                    call = {"type": "tool_call", "id": fc.get("id") or self._synthetic_id(), "name": fc.get("name"), "input": fc.get("args") or {}}
                                    if part.get("thoughtSignature"):
                                        call["provider_meta"] = {"gemini_thought_signature": part["thoughtSignature"]}
                                    tool_calls.append(call)
                            finish = candidate.get("finishReason") or finish
        except ProviderError as exc:
            yield safe_error_event(exc)
            return
        except httpx.HTTPError as exc:
            yield safe_error_event(self._transport_error(exc))
            return
        except (json.JSONDecodeError, ValueError):
            yield safe_error_event(ProviderError("bad_request", "The provider sent a response Catch couldn't read."))
            return

        for call in tool_calls:
            yield call
        yield {"type": "usage", "usage": normalize_usage(usage_meta)}
        if tool_calls:
            stop = "tool_use"
        elif finish == "MAX_TOKENS":
            stop = "max_tokens"
        elif finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"):
            stop = "refusal"
        else:
            stop = "end_turn"
        yield {"type": "stop", "stop_reason": stop}

    async def vision_structured(self, model: str, req: VisionRequest) -> tuple[dict, dict]:
        schema = req.tool["input_schema"]
        # The schema is also spelled out in the prompt: structured-output field support varies
        # by model, and the server validates whatever comes back either way.
        instructions = f"{req.system}\n\nRespond with ONLY a JSON object matching this JSON Schema:\n{json.dumps(schema)}"
        body = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": req.user_text},
                        {"inlineData": {"mimeType": req.media_type, "data": base64.standard_b64encode(req.image_bytes).decode()}},
                    ],
                }
            ],
            "generationConfig": {"maxOutputTokens": req.max_tokens, "responseMimeType": "application/json"},
        }
        try:
            async with self._client() as client:
                resp = await client.post(f"{_model_path(model)}:generateContent", json=body)
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from None
        if resp.status_code != 200:
            raise self._error_from(resp)
        payload = resp.json()
        text = "".join(
            part.get("text", "")
            for cand in (payload.get("candidates") or [])[:1]
            for part in (cand.get("content") or {}).get("parts") or []
            if not part.get("thought")
        )
        try:
            result = json.loads(strip_code_fence(text))
        except json.JSONDecodeError:
            raise ProviderError("bad_request", "The model didn't return a structured result.") from None
        if not isinstance(result, dict):
            raise ProviderError("bad_request", "The model didn't return a structured result.")
        return result, normalize_usage(payload.get("usageMetadata"))
