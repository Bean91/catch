# AI providers (bring your own key)

Catch orchestrates AI requests; it never hosts a model and never pays for anyone's usage. Every user supplies their
own key for Anthropic, OpenAI or Google Gemini (or points Catch at their own Ollama). With nothing configured,
AI features say so and stay off — there is **no environment-variable or shared fallback key anywhere** (a test sets
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GEMINI_API_KEY` and asserts none is used).

Docs read 2026-11-12. As with Whoop, **no adapter has been run against a live account**: the tests use
`httpx.MockTransport` with synthetic payloads shaped from the docs (`tests/fixtures/ai/README.md`).

## The interface (`catch/coach/providers/`)

`base.py` defines `ProviderCapabilities` (streaming, tools, vision, list_models, validate_key, reports_balance),
`ProviderError(kind)` with a fixed vocabulary — `invalid_key | rate_limited | quota | unavailable | timeout |
unsupported | bad_request` — whose message is always a safe user-facing sentence, and `VisionRequest`. Every provider
offers `stream_turn()` (the existing normalized event stream), `list_models()`, `validate()` (costs no tokens where
the provider allows), `vision_structured()` and normalized usage
(`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`). Conversations are stored
as provider-neutral blocks, so **switching provider never loses history or memory**.

| | Anthropic | OpenAI | Gemini | Ollama |
|---|---|---|---|---|
| Transport | official SDK (lazy-imported) | `httpx` | `httpx` | `httpx` |
| Auth | key passed explicitly | `Authorization: Bearer` | `x-goog-api-key` **header** (never `?key=`) | none |
| Model list / validate | `GET /v1/models` (reports `capabilities.image_input.supported`) | `GET /v1/models`, chat models picked by id (no capability field) | `GET /v1beta/models`, `supportedGenerationMethods` ∋ `generateContent` | `/api/tags` + `/api/show` (`capabilities` ∋ `tools`, `vision`) |
| Chat | Messages API, streamed | **Responses API** (`/v1/responses`, `store:false`), streamed | `:streamGenerateContent?alt=sse` | `/api/chat`, streamed |
| Vision | image block + strict tool | `input_image` + strict `json_schema` | `inlineData` + JSON mime type | `images` + `format` schema |
| Balance via API key | not documented | not documented | not documented | n/a |

Why OpenAI uses the Responses API: its docs say Chat Completions "remains supported, but Responses is recommended
for all new projects", and some current models require Responses for tool calling.

### Confirmed vs not confirmed

Confirmed against the docs: error classes and status codes for Anthropic and OpenAI (401/402/403/429 incl. quota
codes, 5xx/529), Anthropic's `/v1/models` fields, OpenAI's tool-call item shapes (`function_call` /
`function_call_output`) and `json_schema` strict format, Gemini's model-list shape and `usageMetadata` fields, Ollama's
`/api/show` capabilities and tool-call shape.
**Not confirmed** (kept as the safest known shape, flagged here so the first real call can falsify them): OpenAI's
Responses streaming event names and `/v1/models` shape (the reference page was unreachable), Gemini `alt=sse`,
Gemini's error `status` strings (errors are classified on the HTTP status plus text), Gemini per-model vision/tool
support (all `gemini-*` models are assumed vision-capable), Anthropic's base64 image block shape (the long-standing
one is used), and the Gemini thought-signature round-trip for function calls (best effort).

## Storage, per user

See `docs/security.md`. Keys live in `ai_credentials` keyed `(owner_id, provider)`, sealed with AES-256-GCM under a
per-owner key and bound to owner+provider. `build_provider(session, owner_id, provider_id)` in
`providers/registry.py` is the only place a key is decrypted. The UI and every API response carry only
`{configured, last4, status}`; `last4` is empty for keys shorter than 12 characters.

## Behaviour

- **Statuses** (`ai_credentials.status`): `configured` (saved, not checked), `valid`, `invalid`, `unavailable`, plus
  "not configured". Set by Test connection, by saving (the key is validated *before* it replaces a working one — a
  rejected key is refused with 422, an unreachable provider saves with status `unavailable`), and by every chat turn
  (a successful turn marks `valid`; an auth failure marks `invalid`). `status_detail` is a fixed enum, never provider
  text.
- **Errors** reach the user as sentences ("The provider rejected this API key…") with a link to Settings → AI Providers
  and one-tap switches to any other configured provider. Nothing a provider echoes back is shown, logged or stored.
- **Models**: from the provider's live listing; `providers/model_catalog.json` holds *patterns* (never exact ids as
  truth) used only to hint vision support where the provider doesn't say. The user can type/keep a model that isn't
  listed.
- **Cost**: from prices the user enters per model. A hosted model with no price has **unknown** cost (`null`), not $0;
  the USD cap can't apply to it, so a **daily token cap** (per owner) also exists. Usage shown is only what Catch
  recorded — never a provider balance.
- **Vision** (meal photo, PM5 screen): through the active provider's `vision_structured`. The buttons are absent
  unless the active provider is configured, has a model and can read images (Ollama is checked per model).
- **Abuse protection** (`catch/coach/limits.py`, in-memory, per owner): 20 chat requests/min, 10 vision/min, 30
  key-validation/model-list calls/min, 2 concurrent streams, 8 000-character messages, history trimmed to ~60k tokens
  *for sending only* (whole oldest turns, never splitting a tool call from its result; stored history untouched), a
  240 s wall-clock cap per turn, 90 s read / 10 s connect timeouts, 8 000 output tokens, and the existing 8-tool-call
  loop cap. One worker only — a multi-worker deployment needs a shared store behind the same interface.

## API (cookie-only; device tokens and MCP can't reach it)

`GET /api/ai/providers`, `PUT|DELETE /api/ai/providers/{id}/key`, `POST …/test`, `GET …/models`, `PUT /api/ai/active`,
`GET /api/ai/usage`. The older `/api/coach/key` and `anthropic_key` remain as thin aliases.
