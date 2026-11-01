from __future__ import annotations

import os
import sys

from catch.mcp_server.backend import RestBackend
from catch.mcp_server.server import build_server


def main() -> None:
    # Read directly from the environment, not catch.core.config's .env — this process is
    # meant to run on a laptop that may have no Catch checkout at all, just the env vars
    # Claude Desktop's claude_desktop_config.json sets for it (see docs/mcp.md).
    base_url = os.environ.get("CATCH_BASE_URL")
    token = os.environ.get("CATCH_MCP_TOKEN")
    if not base_url or not token:
        print(
            "CATCH_BASE_URL and CATCH_MCP_TOKEN must both be set — see docs/mcp.md for how to "
            "create a device token with `uv run catch token create --name <device>`.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    backend = RestBackend(base_url, token)
    server = build_server(backend)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
