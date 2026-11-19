"""Refuse to start a public deployment whose configuration would silently weaken a security
claim. Messages name settings, never values."""

from __future__ import annotations

MIN_SECRET_CHARS = 32


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
    return problems


def enforce_public_config(settings) -> None:
    problems = public_config_problems(settings)
    if problems:
        raise RuntimeError("Refusing to start the public deployment:\n- " + "\n- ".join(problems))
