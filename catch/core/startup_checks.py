"""Refuse to start a public deployment whose configuration would silently weaken a security
claim. Messages name settings, never values."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

MIN_SECRET_CHARS = 32
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def public_config_problems(settings) -> list[str]:
    problems: list[str] = []
    if settings.ollama_enabled:
        problems.append(
            "CATCH_OLLAMA_ENABLED must be 0 on a public deployment: the Ollama URL is user-supplied, "
            "so enabling it lets any signed-in user make the server call an address of their choosing"
        )
    master = settings.secrets_master_key
    if not master:
        problems.append("CATCH_SECRETS_MASTER_KEY is not set (the Pi-only CATCH_FERNET_KEY fallback is not accepted here)")
    elif len(master) < MIN_SECRET_CHARS:
        problems.append(f"CATCH_SECRETS_MASTER_KEY is shorter than {MIN_SECRET_CHARS} characters")
    for name, value in (("CATCH_SECRETS_MASTER_KEY_PREVIOUS", settings.secrets_master_key_previous),):
        for part in (p.strip() for p in value.split(",") if p.strip()):
            if len(part) < MIN_SECRET_CHARS:
                problems.append(f"an entry in {name} is shorter than {MIN_SECRET_CHARS} characters")
    if settings.tick_secret and len(settings.tick_secret) < MIN_SECRET_CHARS:
        problems.append(f"CATCH_TICK_SECRET is shorter than {MIN_SECRET_CHARS} characters")
    problems.extend(_base_url_problems(settings.base_url))
    problems.extend(_pool_problems(settings.database_url, settings.db_pool_mode))
    return problems


def _base_url_problems(base_url: str) -> list[str]:
    # It becomes the MCP Host allowlist and the OAuth issuer: left at the localhost default, every request via the public
    # hostname is answered "421 Invalid Host" and OAuth metadata points at a dead address.
    if os.environ.get("CATCH_ALLOW_LOCAL_BASE_URL") == "1":  # a local rehearsal against a throwaway stack (docs/operations.md); never set it on a deployment
        logging.getLogger("catch").warning("CATCH_ALLOW_LOCAL_BASE_URL=1: the public base-URL check is OFF (MCP host allowlist / OAuth issuer unchecked)")
        return []
    parts = urlsplit(base_url or "")
    if parts.scheme != "https" or not parts.hostname:
        return ["CATCH_BASE_URL must be the public https:// URL of this deployment (it is the MCP host allowlist and the OAuth issuer)"]
    if parts.hostname in _LOCAL_HOSTS:
        return ["CATCH_BASE_URL points at a loopback address; set it to the public https:// URL"]
    return []


def _pool_problems(database_url: str, pool_mode: str) -> list[str]:
    if pool_mode not in ("session", "transaction"):
        return ["CATCH_DB_POOL_MODE must be 'session' or 'transaction'"]
    # Supavisor's transaction pooler (6543) has no prepared-statement support; a client-side pool on top of it fails on the
    # first reused connection, under load rather than at boot, so the mismatch is refused here.
    if pool_mode == "session" and urlsplit(database_url or "").port == 6543:
        return ["DATABASE_URL uses the transaction pooler port (6543) but CATCH_DB_POOL_MODE is 'session'; set it to 'transaction' or use port 5432"]
    return []


def warnings(settings, static_index) -> list[str]:
    out: list[str] = []
    if not settings.tick_secret:
        out.append("CATCH_TICK_SECRET is not set: /internal/* answers 404, so no scheduled sync, notification or retention work will run")
    if not static_index.is_file():
        out.append("catch/api/static/index.html is missing: the app will serve the API only (build the frontend before `fastapi deploy`)")
    return out


def enforce_public_config(settings) -> None:
    problems = public_config_problems(settings)
    if problems:
        raise RuntimeError("Refusing to start the public deployment:\n- " + "\n- ".join(problems))
