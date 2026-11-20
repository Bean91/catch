# Connecting AI clients to Catch over MCP

Catch exposes one MCP server (66 tools, 3 prompts) in two ways:

- **Remote (public deployment):** `https://catch.openoted.com/mcp`. Streamable HTTP, stateless JSON, OAuth 2.1 with dynamic client
  registration and PKCE. You sign in with your Catch (Supabase) account and approve scopes on Catch's own consent page.
- **Local stdio (`catch-mcp`):** for desktop clients that launch a command. It talks to any Catch (Pi or public) over HTTPS with a
  device token.

Server internals, tokens and OAuth design are in [mcp.md](mcp.md). This page is the client-by-client guide, with what was actually
tested. Session 31, 2026-11-20.

## What every client gets, and what it never gets

- It acts as **you**: your user id comes from the OAuth grant or device token, which the server resolves to your Supabase identity.
  Postgres row-level security then applies to every query. Another person's records aren't reachable. That's tested with separate
  identities (`tests/pg`, `tests/tenancy/test_mcp_oauth.py`), and in production two disposable users could not see each other's
  data (smoke, 2026-11-20).
- **Scopes:**
  - `catch:read` covers tools that don't write.
  - `catch:write` adds the 22 write tools. Every write **previews first** and saves only when called again with `confirm=true`.
  - A read-scope token can't write (production smoke: PASS).
- **AI sharing.** What a client may read follows your switches in Settings → Privacy → AI sharing. With nothing allowed, tools
  answer "sharing is switched off". That is the consent gate working, not a fault.
- **Never available:** your provider credentials, AI keys, account deletion, publishing to leaderboards, and any club write.
- **The confirmation step depends on the client** (F-02 residual). Over MCP, Catch can only require that `confirm=true` is a
  separate, explicit call. Whether a person actually agreed is up to the client's UI. ChatGPT asks for confirmation on write tools
  by default. Claude asks per its tool-permission settings.

Tool output that contains text written by people or imported from providers is listed in `_untrusted_fields`. Clients should treat
it as data, never as instructions.

## Status by client

| Client | Transport / auth | Status (2026-11-20) |
|---|---|---|
| **Claude (claude.ai, web)**, remote connector | Streamable HTTP + OAuth | **TESTED, works.** Session 29: connected through OAuth. Session 31: through the owner's connector, a read (`get_connected_providers`, `get_sync_status`) returned the owner's own data, and `create_event` without `confirm` returned `saved: false` plus a preview; nothing was saved. |
| **Claude Desktop**, remote connector | same | Not separately tested. It uses the same claude.ai connector settings, depending on plan. |
| **Claude Desktop / Claude Code**, local `catch-mcp` (stdio) | stdio → HTTPS + device token | **TESTED (local).** `scripts/mcp_stdio_check.py`, 7/7: initialize, 66 tools, a read, a write that only previews with nothing saved, and an invalid token refused. |
| **ChatGPT**, custom connector (developer mode) | Streamable HTTP + OAuth | **NOT TESTED** (no ChatGPT account available). Setup below is from OpenAI's documentation. |
| **Gemini API** (google-genai SDK MCP support) | Streamable HTTP via the MCP Python/JS client you run | **NOT TESTED** (no Gemini key). It works through your own code; see below. |
| **Gemini CLI** | `httpUrl` + OAuth discovery, or stdio | **NOT TESTED** (CLI not installed). Setup below is from Google's documentation. |
| **MCP Inspector** | either | Tested in session 6 (stdio, against a local instance) |

## Claude (web, remote)

1. claude.ai → Settings → Connectors → Add custom connector → URL `https://catch.openoted.com/mcp`.
2. Claude registers itself and sends you to Catch. Sign in, then on Catch's consent page choose read, or read + write.
3. Manage or end the grant in Catch: Settings → Privacy → Connected apps.

Known behaviour:

- Claude registers as a confidential-style client. Catch records it as a public PKCE client and says so in the registration
  response (RFC 7591 §3.2.1, session 29).
- Before session 31, a connector that only ever refreshed its token was deleted after 30 days, and its next refresh failed (audit
  L-34). That's fixed: refresh and code exchange now count as use. On a deployment older than session 31, reconnect if Claude
  reports an auth error after about a month.

## Claude Desktop or Claude Code with local stdio

1. Create a device token: Settings → Privacy → Apps → Create token, choosing read or write. It expires in 90 days by default, and
   you can have at most 10. On the Pi: `uv run catch token create --name laptop`.
2. In `claude_desktop_config.json`:

   ```json
   { "mcpServers": { "catch": { "command": "/abs/path/Catch/.venv/bin/catch-mcp",
       "env": { "CATCH_BASE_URL": "https://catch.openoted.com", "CATCH_MCP_TOKEN": "<token>" } } } }
   ```

3. For Claude Code: `claude mcp add catch --env CATCH_BASE_URL=… --env CATCH_MCP_TOKEN=… -- /abs/path/.venv/bin/catch-mcp`.
4. Check it with `uv run python scripts/mcp_stdio_check.py`. It runs against a disposable local instance, never your data.

## ChatGPT (custom connector): from OpenAI's docs, untested

- **Availability varies by plan and is in flux.**
  - OpenAI's developer docs list developer mode for Plus, Pro, Business, Enterprise and Education on the web.
  - The Help Center says full MCP support with write actions is in beta for Business, Enterprise and Edu.
  - On Business, each admin or owner must enable developer mode for themselves.
- **Setup:** Settings → Connectors (Apps) → Advanced → Developer mode on → Create → MCP server URL
  `https://catch.openoted.com/mcp`, authentication **OAuth**. ChatGPT discovers Catch's metadata from
  `/.well-known/oauth-protected-resource/mcp`.
- **What to expect:**
  - Writes are confirmed in ChatGPT's UI by default. Catch still previews first.
  - Without write support on your plan, only the read tools are useful.
  - Community reports mention "Failed to resolve OAuth client" with some servers. If that happens, check Catch's OAuth log lines
    (`mcp_server/oauth_http.py` logs the reason for a rejected `/register|/authorize|/token`).
- **To verify (owner):** connect, call `get_today`, and confirm `create_event` without confirmation saves nothing.

## Gemini: from Google's docs, untested

- **Gemini CLI:** add Catch to `~/.gemini/settings.json`:

  ```json
  { "mcpServers": { "catch": { "httpUrl": "https://catch.openoted.com/mcp" } } }
  ```

  Then run `/mcp auth catch` to start OAuth. The CLI discovers OAuth from the server, and tokens are stored in
  `~/.gemini/mcp-oauth-tokens.json`. The stdio alternative is `"command": "/abs/path/.venv/bin/catch-mcp"` with the same two `env`
  values as above.
- **Gemini API (google-genai SDK):**
  - The SDK can take an MCP `ClientSession` as a tool (Python, async; marked experimental).
  - You run the MCP client yourself: open a Streamable HTTP session to `/mcp` with a bearer token you obtained (a device token via
    `catch-mcp`, or an OAuth access token), then pass the session in `tools=[…]`.
  - Gemini uses **tools only**, not MCP prompts or resources.
  - There is no hosted "Gemini connects to your MCP URL" product to configure. Remote MCP is your code calling Catch.
- **Not to be confused with** Catch's own Gemini BYOK coach provider (docs/ai-providers.md). That calls the Gemini API with your
  key and uses Catch's tools directly, not over MCP.

## Revoking access

- One app: Settings → Privacy → Connected apps → End.
- Everything at once: "End all app access" (tokens and OAuth grants).
- A device token: Settings → Privacy → Apps → Revoke.

Revocation takes effect on the next request (access tokens are checked against the grant). Tested in `tests/tenancy/test_mcp_oauth.py`
(revoke, replayed refresh token, end-all).

Sources for the untested sections: OpenAI developer-mode guide (developers.openai.com/api/docs/guides/developer-mode), OpenAI Help
Center article 12584461, Gemini CLI MCP docs (geminicli.com/docs/tools/mcp-server), python-genai MCP support guide.
