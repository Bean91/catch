from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session

from catch.core import security
from catch.core.models import CoachCredential, CoachSettings

SETTINGS_ID = 1
_PROVIDERS = {"anthropic", "ollama"}
_PRICE_FIELDS = {"input", "output", "cache_write", "cache_read"}


def get_coach_settings(session: Session) -> dict:
    row = session.get(CoachSettings, SETTINGS_ID)
    if row is None:
        return {
            "provider": "anthropic",
            "anthropic_model": None,
            "ollama_base_url": None,
            "ollama_model": None,
            "daily_cap_usd": None,
            "prices": {},
        }
    return {
        "provider": row.provider,
        "anthropic_model": row.anthropic_model,
        "ollama_base_url": row.ollama_base_url,
        "ollama_model": row.ollama_model,
        "daily_cap_usd": row.daily_cap_usd,
        "prices": json.loads(row.prices_json) if row.prices_json else {},
    }


def update_coach_settings(session: Session, patch: dict) -> dict:
    allowed = {"provider", "anthropic_model", "ollama_base_url", "ollama_model", "daily_cap_usd", "prices"}
    unknown = set(patch) - allowed
    if unknown:
        raise ValueError(f"Unknown coach setting(s): {sorted(unknown)}")
    if "provider" in patch and patch["provider"] not in _PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(_PROVIDERS)}")
    if "prices" in patch:
        if not isinstance(patch["prices"], dict):
            raise ValueError("prices must be an object keyed by model id")
        for model_id, rates in patch["prices"].items():
            if not isinstance(rates, dict) or set(rates) - _PRICE_FIELDS:
                raise ValueError(f"prices.{model_id} must only contain {sorted(_PRICE_FIELDS)}")

    row = session.get(CoachSettings, SETTINGS_ID)
    if row is None:
        row = CoachSettings(id=SETTINGS_ID)
        session.add(row)
    for key in ("provider", "anthropic_model", "ollama_base_url", "ollama_model", "daily_cap_usd"):
        if key in patch:
            setattr(row, key, patch[key])
    if "prices" in patch:
        current = json.loads(row.prices_json) if row.prices_json else {}
        current.update(patch["prices"])
        row.prices_json = json.dumps(current)
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return get_coach_settings(session)


def masked_credential_info(session: Session, provider: str) -> dict:
    row = session.get(CoachCredential, provider)
    return {"configured": row is not None, "last4": row.last4 if row else None}


def set_credential(session: Session, provider: str, raw_key: str) -> dict:
    if provider not in _PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(_PROVIDERS)}")
    row = session.get(CoachCredential, provider)
    encrypted = security.encrypt(raw_key)
    last4 = raw_key[-4:] if len(raw_key) >= 4 else raw_key
    if row is None:
        row = CoachCredential(provider=provider, api_key_enc=encrypted, last4=last4)
        session.add(row)
    else:
        row.api_key_enc = encrypted
        row.last4 = last4
        row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return masked_credential_info(session, provider)


def get_decrypted_credential(session: Session, provider: str) -> str | None:
    """Server-side only — never return this value from an API response."""
    row = session.get(CoachCredential, provider)
    return security.decrypt(row.api_key_enc) if row else None


def delete_credential(session: Session, provider: str) -> bool:
    row = session.get(CoachCredential, provider)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
