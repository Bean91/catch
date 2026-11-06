# MCP server

`catch/mcp_server/` exposes the same shared tool layer (`catch/coach/tools.py`) that the
in-app coach uses — read-only training data (canonical activities only, session 8/12 — see
PLAN.md: every id a tool takes or returns is a canonical id, never a raw per-source activity
id), the `remember`/`add_event`/`update_event`/`set_goal`/`forget`/`recall` memory tools,
(session 8/12) `rename_activity`/`tag_activity`/`merge_activities` for the cross-source
matching/editing tools, (session 13) `get_nutrition`/`log_food` for the nutrition diary, and
(session 14) `log_strength`/`get_strength`/`get_muscle_readiness` for the gym logger, and
(session 15) `get_tests`/`get_test`/`make_pacing_plan` for the erg test center —
27 tools total — to Claude Desktop (or any MCP client) over two transports:

- **stdio** — for Claude Desktop, running on your laptop while Catch itself runs on the Pi.
  Tool calls are thin `httpx` calls to Catch's `POST /api/coach/tools/{name}`, authenticated
  with a per-device bearer token (see below).
- **streamable-HTTP**, mounted at `/mcp/` (**trailing slash required** — see the gotcha
  below) — for anything that wants to reach the same tools over Tailscale without going
  through stdio. Off by default (`CATCH_MCP_HTTP_ENABLED=0` in `.env`); set it to `1` to
  mount it. Because it runs inside Catch's own process, its tool calls dispatch straight into
  the tool registry in-process rather than round-tripping through HTTP — a synchronous call
  back to the same single-worker uvicorn would deadlock. Behind a flat bearer-token check
  (same device tokens as stdio), not full OAuth — this is a single-user, Tailscale-only
  endpoint.

  **Gotcha, found by testing with real `curl` requests, not just reading the mount code**:
  `POST /mcp` (no trailing slash) 405s with `Allow: GET` — Starlette's `Mount("/mcp", ...)`
  only matches `/mcp/...`, so a bare `/mcp` falls through *past* the mount entirely to the
  SPA catch-all route (`GET /{full_path:path}` in `catch/main.py`), which rejects POST. Always
  point clients at `/mcp/`.

Both transports share one `catch/mcp_server/server.py::build_server()` — the tool
definitions (names, descriptions, parameter schemas inferred from each function's type
hints and docstring) are defined once and don't drift between transports.

## 1. Create a device token

The MCP server authenticates to Catch's API the same way a browser session does — except
with a long-lived bearer token instead of a password-derived cookie, since Claude Desktop on
your laptop can't go through the login flow. Create one on the machine running Catch (the
Pi), or against a dev instance:

```bash
uv run catch token create --name "laptop"
```

This prints the raw token **once** — copy it now, only its sha256 hash is stored. Manage
tokens afterward from Settings → Coach → Device tokens (list, see last-used time, revoke), or
`uv run catch token list`.

## 2. Configure Claude Desktop

Add this to `claude_desktop_config.json` (on macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "catch": {
      "command": "/absolute/path/to/Catch/.venv/bin/catch-mcp",
      "env": {
        "CATCH_BASE_URL": "https://<pi-name>.<tailnet>.ts.net",
        "CATCH_MCP_TOKEN": "<the raw token from step 1>"
      }
    }
  }
}
```

`CATCH_BASE_URL` is wherever Catch is reachable from your laptop. Against the Pi deployment
(`deploy/pi-bootstrap.sh`), uvicorn only binds `127.0.0.1:8000` — the Pi's tailnet IP doesn't
serve port 8000 directly — so the real reachable address is the HTTPS hostname `tailscale
serve` exposes, `https://<pi-name>.<tailnet>.ts.net`, not `http://<ip>:8000`. Against a local
dev instance it's `http://localhost:8000`. The `catch-mcp` entry point is installed into
`.venv/bin` by `uv sync` (it's `project.scripts` in `pyproject.toml`); use the absolute path
since Claude Desktop doesn't activate the venv.

Restart Claude Desktop after editing the config. It should list `get_today`, `get_wellness`,
`list_workouts`, `get_workout`, `get_trends`, `get_body_comp`, `get_load`, `predict_2k`,
`get_zones`, `add_note`, `remember`, `add_event`, `update_event`, `set_goal`, `forget`, and
`recall` under the `catch` server, plus two prompts, `daily_check_in` and `weekly_review`.

## 3. Test with the MCP Inspector

```bash
npx @modelcontextprotocol/inspector@latest --cli \
  -e CATCH_BASE_URL=http://127.0.0.1:8000 \
  -e CATCH_MCP_TOKEN=<token> \
  --method tools/list \
  /absolute/path/to/Catch/.venv/bin/catch-mcp
```

Swap `--method tools/list` for `--method tools/call --tool-name get_zones --tool-args-json
'{}'` to make a real call, or `--method prompts/list` / `--method prompts/get --prompt-name
daily_check_in` for the two bundled prompts. The inspector also has an interactive `--web` UI
if you'd rather click through it.

### What was actually verified (2026-10-31)

Run against a disposable throwaway instance (fresh password/session-secret/Fernet key, a
scratch SQLite DB, deleted afterward — never the real `.env`/`data/catch.db`), with Node
v22.14 and `@modelcontextprotocol/inspector@2.13.0`:

- `tools/list` returned all 16 tools with their inferred JSON schemas (enums for `category`/
  `type`/`priority`/`status`/`metric` came through correctly from the `Literal[...]` type
  hints in `server.py`).
- `prompts/list` returned both `daily_check_in` and `weekly_review`.
- A real `tools/call` for `get_zones` round-tripped stdio → `RestBackend` → `POST
  /api/coach/tools/get_zones` (confirmed via the request log: `HTTP Request: POST
  http://127.0.0.1:8077/api/coach/tools/get_zones "HTTP/1.1 200 OK"`) → Catch's tool registry
  → the same zone-table JSON `GET /api/coach/tools` + `curl` returns directly, round-tripped
  back through MCP's `content: [{"type": "text", "text": "..."}]` wrapper.

The streamable-HTTP `/mcp/` mount (`CATCH_MCP_HTTP_ENABLED=1`) was also live-verified, against
a second disposable instance, with raw `curl` rather than the Inspector (its `--transport
http` mode wants a full OAuth-capable client; this endpoint deliberately uses a flat bearer
token instead, matching stdio and the tool REST endpoint):

- `POST /mcp/` with no `Authorization` header → `401 {"detail": "Not authenticated"}`.
- `POST /mcp/` with `Authorization: Bearer <device token>` and a real `initialize` JSON-RPC
  body → `200`, `text/event-stream`, a real `mcp-session-id` header, and a correct
  `initialize` response (server name `catch`, the instructions string from
  `build_server()`, capabilities for `tools`/`prompts`/`resources`).
- The server log showed `StreamableHTTP session manager started` at startup, confirming the
  session manager is actually running inside Catch's own lifespan (not silently absent, which
  is the failure mode a mounted sub-app's lifespan not firing would otherwise cause).
