"""End-to-end check of the local stdio MCP server (`catch-mcp`), the transport Claude Desktop uses (docs/mcp-client-setup.md).

Boots a disposable personal instance (scratch SQLite DB + freshly generated secrets, never the real .env or data/), mints a device
token, consents to AI sharing for the disposable athlete, then drives `python -m catch.mcp_server` over stdio with the official MCP
client: list tools, call a read tool, call a write tool without confirm (must only preview), and call one with a bad token (must
fail). Prints PASS/FAIL lines and never a token. No external network.

    uv run python scripts/mcp_stdio_check.py
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
RESULTS: list[tuple[bool, str]] = []


def record(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((ok, label))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}{' — ' + detail if detail else ''}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def disposable_env(tmp: Path, port: int, password: str) -> dict:
    from argon2 import PasswordHasher
    from cryptography.fernet import Fernet

    env = {k: v for k, v in os.environ.items() if not k.startswith(("CATCH_", "GARMIN_", "WITHINGS_", "CONCEPT2_", "WHOOP_", "VAPID_", "HEALTHCHECKS_", "NTFY_", "DATABASE_", "SUPABASE_"))}
    env.update({
        "CATCH_ENV": "test", "CATCH_DEPLOYMENT": "personal", "CATCH_PORT": str(port), "CATCH_DB_PATH": str(tmp / "catch.db"),
        "CATCH_BASE_URL": f"http://127.0.0.1:{port}", "CATCH_PASSWORD_HASH": PasswordHasher().hash(password),
        "CATCH_SESSION_SECRET": secrets.token_hex(32), "CATCH_FERNET_KEY": Fernet.generate_key().decode(), "SYNC_INTERVAL_HOURS": "24",
    })
    return env


async def drive(base_url: str, token: str) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "catch.mcp_server"], cwd=str(ROOT),
                                   env={**{k: v for k, v in os.environ.items() if k in ("PATH", "HOME")}, "CATCH_BASE_URL": base_url, "CATCH_MCP_TOKEN": token})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        record(bool(init.server_info.name), "stdio initialize", init.server_info.name)
        tools = (await session.list_tools()).tools
        record(len(tools) == 66, "tools/list over stdio", f"{len(tools)} tools")
        today = await session.call_tool("get_today", {})
        body = json.loads(today.content[0].text) if today.content else {}
        record(not today.is_error and "recovery" in body, "read tool get_today returns the athlete's own payload")
        preview = await session.call_tool("create_event", {"name": "stdio check", "date": "2027-01-01", "type": "camp"})
        pbody = json.loads(preview.content[0].text) if preview.content else {}
        record(not preview.is_error and pbody.get("saved") is False and "preview" in pbody, "a write without confirm only previews")
        events = await session.call_tool("get_upcoming_events", {})
        record("stdio check" not in (events.content[0].text if events.content else ""), "nothing was saved by the preview")


async def bad_token(base_url: str) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "catch.mcp_server"], cwd=str(ROOT),
                                   env={**{k: v for k, v in os.environ.items() if k in ("PATH", "HOME")}, "CATCH_BASE_URL": base_url, "CATCH_MCP_TOKEN": "not-a-real-token"})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        out = await session.call_tool("get_today", {})
        text = out.content[0].text if out.content else ""
        record(out.is_error or "401" in text or "unauthor" in text.lower() or "error" in text.lower(), "an invalid device token gets no data", text[:60])


def main() -> int:
    port, password = free_port(), secrets.token_urlsafe(16)
    with tempfile.TemporaryDirectory(prefix="catch-mcp-stdio-") as d:
        tmp = Path(d)
        env = disposable_env(tmp, port, password)
        base = env["CATCH_BASE_URL"]
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "catch.main:app", "--host", "127.0.0.1", "--port", str(port)],
                                  cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(80):
                try:
                    if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.25)
            else:
                record(False, "disposable instance started")
                return 1
            out = subprocess.run([sys.executable, "-m", "catch.cli", "token", "create", "--name", "stdio-check"], cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout
            token = out.strip().splitlines()[-1].strip()
            with httpx.Client(base_url=base) as c:
                assert c.post("/api/login", json={"password": password}).status_code == 200
                r = c.put("/api/ai/sharing", json={"acknowledge": True, "categories": {k: True for k in ("wellness", "workouts", "nutrition", "notes_checkins", "memory", "calendar_library")}})
                record(r.status_code == 200, "disposable athlete consents to AI sharing", str(r.status_code))
            asyncio.run(drive(base, token))
            asyncio.run(bad_token(base))
        finally:
            server.terminate()
            server.wait(timeout=10)
    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
