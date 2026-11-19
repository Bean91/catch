# What reaches an AI provider — engineering detail (session 28)

The user-facing explanation is `docs/legal/ai-data-sharing.md` (a draft). This file maps it to code.

**Consent and categories** — `catch/coach/ai_sharing.py`, table `ai_sharing_settings` (one row per person: `consent_version`, `consented_at`,
`categories_json`, optional `age_band`, `guardian_ack_at`). No row, or a withdrawn one, means nothing is agreed. Seven categories, all off by default:
`wellness`, `workouts`, `nutrition`, `notes_checkins`, `memory`, `calendar_library`, `photos`. API: `GET/PUT/DELETE /api/ai/sharing` (cookie/JWT only — never a device
token). A declared age band of u19…u14 requires `guardian_ack` before any health category (`wellness`, `workouts`, `nutrition`, `notes_checkins`, `memory`, `photos`) can be enabled.

**Enforcement points** (all server-side; none is a prompt instruction):

| Path | Where | Behaviour when not allowed |
|---|---|---|
| In-app chat | `chat._run_turn` | `consent_required` event; the provider is never resolved |
| System-prompt memory block | `memory.memory_block(allowed=…)` | sections for disabled categories are omitted (events/goals/facts, check-in/niggle, illness, recommendation) |
| Tool calls — reads **and writes** — on a model-bound path (`via` = `ai_coach` or `mcp`; a device token is always `mcp`, decided by the credential) | `tools.call_tool` | the result is replaced by `{"unavailable": true, "reason": "sharing_disabled", …}`; the denial is audited |
| Photo features | `vision.run_vision` / `vision_available` | `VisionError` / `reason: "sharing_off"`; the image is never sent |
| Direct REST tool calls (`via` = `rest`) | not gated | the person's own API client, not a model |

`TOOL_CATEGORY` classifies every tool (a test fails if a tool is missing); `None` = no personal data (connection status, other people's public
leaderboard/club information). Mixed payloads are trimmed (`ai_sharing.limit_result`: `get_today` drops check-in and upcoming events, workouts drop notes/RPE when those categories are off; `get_trends` over a `checkin_*` metric is refused), and `scrub_history` re-applies the rules to stored tool results every time a conversation is replayed.

**Payloads** (`coach/providers/*`, `coach/vision.py`): chat = system prompt + memory block + history (≈ 60k tokens, `limits.trim_history`) + tool schemas;
vision = a fixed system prompt, one line of user text and the image bytes. Credentials, account ids, emails, device tokens and raw GPS coordinates are
never in any payload (`tests/test_ai_no_leak.py`). OpenAI is called with `store: false`; Gemini's key is a header; Ollama is the person's own host (off on
a public deployment).

**Untrusted text** — `coach/untrusted.py` sanitises and labels free-text fields in every tool result and the memory block; see `docs/security.md`.

**Not built:** per-provider choices of categories, per-conversation overrides, an in-chat "what was sent" viewer, a retention setting for chat history.
