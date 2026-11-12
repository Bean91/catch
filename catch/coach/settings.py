from __future__ import annotations

from catch.core.tenant import current_owner
from catch.core import tenant
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from catch.coach.providers.base import KEY_PROVIDERS, PROVIDER_IDS
from urllib.parse import urlparse

from catch.core import redact, secret_store, security
from catch.core.config import settings as app_config
from catch.core.models import AiCredential, CoachCredential, CoachSettings

_PRICE_FIELDS = {"input", "output", "cache_write", "cache_read"}
STATUSES = ("configured", "valid", "invalid", "unavailable")
# Fixed vocabulary for AiCredential.status_detail — provider-supplied text never lands there.
STATUS_DETAILS = ("rejected_by_provider", "rate_limited", "quota_exceeded", "provider_unreachable", "timed_out", "not_checked")


def _row(session: Session, owner_id: str) -> CoachSettings | None:
    return session.exec(select(CoachSettings).where(CoachSettings.owner_id == owner_id)).first()


def _models(row: CoachSettings | None) -> dict:
    models = json.loads(row.models_json) if row and row.models_json else {}
    if row:
        if row.anthropic_model:
            models.setdefault("anthropic", row.anthropic_model)
        if row.ollama_model:
            models.setdefault("ollama", row.ollama_model)
    return {k: v for k, v in models.items() if v}


def get_coach_settings(session: Session, owner_id: str | None = None) -> dict:
    owner_id = owner_id or current_owner()
    row = _row(session, owner_id)
    if row is None:
        return {
            "provider": "anthropic",
            "anthropic_model": None,
            "ollama_base_url": None,
            "ollama_model": None,
            "models": {},
            "daily_cap_usd": None,
            "daily_token_cap": None,
            "prices": {},
        }
    models = _models(row)
    return {
        "provider": row.provider,
        "anthropic_model": models.get("anthropic"),
        "ollama_base_url": row.ollama_base_url,
        "ollama_model": models.get("ollama"),
        "models": models,
        "daily_cap_usd": row.daily_cap_usd,
        "daily_token_cap": row.daily_token_cap,
        "prices": json.loads(row.prices_json) if row.prices_json else {},
    }


_PATCHABLE = {
    "provider", "anthropic_model", "ollama_base_url", "ollama_model", "models", "daily_cap_usd", "daily_token_cap", "prices",
}


def update_coach_settings(session: Session, patch: dict, owner_id: str | None = None) -> dict:
    owner_id = owner_id or current_owner()
    unknown = set(patch) - _PATCHABLE
    if unknown:
        raise ValueError(f"Unknown coach setting(s): {sorted(unknown)}")
    if "provider" in patch and patch["provider"] not in PROVIDER_IDS:
        raise ValueError(f"provider must be one of {sorted(PROVIDER_IDS)}")
    if not app_config.ollama_enabled and (patch.get("provider") == "ollama" or patch.get("ollama_base_url")):
        raise ValueError("Ollama isn't available on this server.")
    if patch.get("ollama_base_url"):
        parsed = urlparse(str(patch["ollama_base_url"]))
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("The Ollama address must look like http://host:11434 (no credentials in the URL).")
    if "models" in patch:
        models = patch["models"]
        if not isinstance(models, dict) or set(models) - set(PROVIDER_IDS):
            raise ValueError(f"models must be an object keyed by provider ({sorted(PROVIDER_IDS)})")
    if "prices" in patch:
        if not isinstance(patch["prices"], dict):
            raise ValueError("prices must be an object keyed by model id")
        for model_id, rates in patch["prices"].items():
            if not isinstance(rates, dict) or set(rates) - _PRICE_FIELDS:
                raise ValueError(f"prices.{model_id} must only contain {sorted(_PRICE_FIELDS)}")
    if patch.get("daily_token_cap") is not None and (not isinstance(patch["daily_token_cap"], int) or patch["daily_token_cap"] < 0):
        raise ValueError("daily_token_cap must be a non-negative integer")

    row = _row(session, owner_id)
    if row is None:
        row = CoachSettings(owner_id=owner_id)
        session.add(row)
    for key in ("provider", "ollama_base_url", "daily_cap_usd", "daily_token_cap"):
        if key in patch:
            setattr(row, key, patch[key])
    models = json.loads(row.models_json) if row.models_json else {}
    if "models" in patch:
        models.update({k: v or None for k, v in patch["models"].items()})
    for column, provider in (("anthropic_model", "anthropic"), ("ollama_model", "ollama")):
        if column in patch:
            setattr(row, column, patch[column])
            models[provider] = patch[column] or None
    row.models_json = json.dumps({k: v for k, v in models.items() if v})
    if "prices" in patch:
        current = json.loads(row.prices_json) if row.prices_json else {}
        current.update(patch["prices"])
        row.prices_json = json.dumps(current)
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return get_coach_settings(session, owner_id)


def _require_key_provider(provider: str) -> None:
    if provider not in KEY_PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(KEY_PROVIDERS)}")


def _adopt_legacy(session: Session, provider: str, owner_id: str) -> AiCredential | None:
    """Session 22 stored one Fernet-encrypted key per provider in `coach_credentials`. Copy it
    into the per-owner store on first read, leaving the legacy row in place so rolling back to the
    old code still works. Replace and Remove (below) delete it, so a superseded or removed key
    can't come back."""
    if owner_id != tenant.PERSONAL_OWNER:
        return None
    legacy = session.get(CoachCredential, tenant.pk(provider))
    if legacy is None:
        return None
    try:
        plaintext = security.decrypt(legacy.api_key_enc)
    except Exception:
        return None
    try:
        blob, key_id = secret_store.seal(plaintext, owner_id=owner_id, provider=provider)
    except secret_store.SecretStoreError:
        return None
    row = AiCredential(owner_id=owner_id, provider=provider, key_enc=blob, key_id=key_id, last4=secret_store.mask(plaintext))
    session.add(row)
    session.commit()
    return row


def _credential(session: Session, provider: str, owner_id: str) -> AiCredential | None:
    row = session.get(AiCredential, (owner_id, provider))
    return row or _adopt_legacy(session, provider, owner_id)


def masked_credential_info(session: Session, provider: str, owner_id: str | None = None) -> dict:
    owner_id = owner_id or current_owner()
    row = _credential(session, provider, owner_id) if provider in KEY_PROVIDERS else None
    return {
        "configured": row is not None,
        "last4": (row.last4 or None) if row else None,
        "status": row.status if row else "not_configured",
        "status_detail": row.status_detail if row else None,
        "status_checked_at": row.status_checked_at.isoformat() if row and row.status_checked_at else None,
    }


def set_credential(session: Session, provider: str, raw_key: str, owner_id: str | None = None) -> dict:
    owner_id = owner_id or current_owner()
    _require_key_provider(provider)
    raw_key = raw_key.strip()
    if not raw_key:
        raise ValueError("The key is empty.")
    blob, key_id = secret_store.seal(raw_key, owner_id=owner_id, provider=provider)
    redact.register_secret(raw_key)
    now = datetime.now(timezone.utc)
    row = session.get(AiCredential, (owner_id, provider))
    if row is None:
        row = AiCredential(owner_id=owner_id, provider=provider, key_enc=blob, key_id=key_id)
        session.add(row)
    row.key_enc, row.key_id, row.last4 = blob, key_id, secret_store.mask(raw_key)
    row.status, row.status_detail, row.status_checked_at, row.updated_at = "configured", None, None, now
    legacy = session.get(CoachCredential, tenant.pk(provider)) if owner_id == tenant.PERSONAL_OWNER else None
    if legacy is not None:
        session.delete(legacy)
    session.commit()
    return masked_credential_info(session, provider, owner_id)


def get_decrypted_credential(session: Session, provider: str, owner_id: str | None = None) -> str | None:
    """Server-side only — never return this value from an API response, a tool or an error."""
    owner_id = owner_id or current_owner()
    if provider not in KEY_PROVIDERS:
        return None
    row = _credential(session, provider, owner_id)
    if row is None:
        return None
    key = secret_store.open_sealed(row.key_enc, owner_id=owner_id, provider=provider)
    redact.register_secret(key)
    return key


def delete_credential(session: Session, provider: str, owner_id: str | None = None) -> bool:
    owner_id = owner_id or current_owner()
    if provider not in KEY_PROVIDERS:
        return False
    removed = False
    row = session.get(AiCredential, (owner_id, provider))
    if row is not None:
        session.delete(row)
        removed = True
    legacy = session.get(CoachCredential, tenant.pk(provider)) if owner_id == tenant.PERSONAL_OWNER else None
    if legacy is not None:
        session.delete(legacy)
        removed = True
    session.commit()
    return removed


def set_status(session: Session, provider: str, status: str, detail: str | None, owner_id: str | None = None) -> None:
    owner_id = owner_id or current_owner()
    if status not in STATUSES:
        raise ValueError("unknown status")
    if detail is not None and detail not in STATUS_DETAILS:
        raise ValueError("unknown status detail")
    row = session.get(AiCredential, (owner_id, provider))
    if row is None:
        return
    row.status, row.status_detail = status, detail
    row.status_checked_at = datetime.now(timezone.utc)
    session.commit()


def configured_providers(session: Session, owner_id: str | None = None) -> list[str]:
    owner_id = owner_id or current_owner()
    return [p for p in KEY_PROVIDERS if _credential(session, p, owner_id) is not None]
