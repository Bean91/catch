from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_ENV_LINE = __import__("re").compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def load_dotenv(path: Path) -> None:
    # No inline (end-of-line) "# comment" support — a trailing `KEY=value   # note` keeps the
    # comment as part of `value`. Found live (session 16): NTFY_TOPIC/VAPID_SUBJECT written
    # that way in .env picked up the comment text itself as their value — for a quoted value
    # it's silently swallowed by base64's lenient decoder if the value happens to be a Fernet
    # key (lucky, not something to rely on elsewhere), but for anything regex-validated
    # (py_vapid's `sub` claim) or used verbatim in a URL path (ntfy's topic) it's a live bug.
    # Put a key's comment on the line above instead, or on a bare `KEY=` line with nothing
    # after the `=`, matching the rest of .env.example.
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    env: str
    port: int
    db_path: str
    base_url: str
    password_hash: str
    session_secret: str
    fernet_key: str
    garmin_api_key: str
    withings_client_id: str
    withings_client_secret: str
    withings_redirect_uri: str
    concept2_access_token: str
    sync_interval_hours: float
    backfill_days: int
    mcp_http_enabled: bool
    usda_fdc_api_key: str
    vapid_public_key: str
    vapid_private_key: str
    vapid_subject: str
    healthchecks_sync_url: str
    healthchecks_backup_url: str
    ntfy_topic: str

    @property
    def db_file(self) -> Path:
        return Path(self.db_path)


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def load_settings() -> Settings:
    return Settings(
        env=_get("CATCH_ENV", "development"),
        port=int(_get("CATCH_PORT", "8000")),
        db_path=_get("CATCH_DB_PATH", "data/catch.db"),
        base_url=_get("CATCH_BASE_URL", "http://localhost:8000"),
        password_hash=_get("CATCH_PASSWORD_HASH"),
        session_secret=_get("CATCH_SESSION_SECRET"),
        fernet_key=_get("CATCH_FERNET_KEY"),
        garmin_api_key=_get("GARMIN_PERSONAL_API_KEY"),
        withings_client_id=_get("WITHINGS_CLIENT_ID"),
        withings_client_secret=_get("WITHINGS_CLIENT_SECRET"),
        withings_redirect_uri=_get("WITHINGS_REDIRECT_URI"),
        concept2_access_token=_get("CONCEPT2_ACCESS_TOKEN"),
        sync_interval_hours=float(_get("SYNC_INTERVAL_HOURS", "2")),
        backfill_days=int(_get("BACKFILL_DAYS", "30")),
        # Off by default: the `mcp` package is only imported when this is set, so a Pi
        # deployment that never uses Claude Desktop over Tailscale doesn't pay for it.
        mcp_http_enabled=_get("CATCH_MCP_HTTP_ENABLED", "0") == "1",
        usda_fdc_api_key=_get("USDA_FDC_API_KEY"),
        vapid_public_key=_get("VAPID_PUBLIC_KEY"),
        vapid_private_key=_get("VAPID_PRIVATE_KEY"),
        vapid_subject=_get("VAPID_SUBJECT"),
        healthchecks_sync_url=_get("HEALTHCHECKS_SYNC_URL"),
        healthchecks_backup_url=_get("HEALTHCHECKS_BACKUP_URL"),
        ntfy_topic=_get("NTFY_TOPIC"),
    )


settings = load_settings()
