"""The one place a provider key is decrypted and a provider object is built."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from catch.coach import settings as coach_settings
from catch.coach.providers.base import KEY_PROVIDERS, PROVIDER_IDS, ProviderCapabilities, ProviderError
from catch.core.config import settings
from catch.core.principal import OWNER_ID
from catch.core.secret_store import SecretStoreError

_CATALOG = json.loads((Path(__file__).parent / "model_catalog.json").read_text())


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    needs_key: bool
    key_hint: str
    docs_url: str
    capabilities: ProviderCapabilities


SPECS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec("anthropic", "Anthropic", True, "sk-ant-…", "https://console.anthropic.com/settings/keys", ProviderCapabilities(vision=True)),
    "openai": ProviderSpec("openai", "OpenAI", True, "sk-…", "https://platform.openai.com/api-keys", ProviderCapabilities(vision=True)),
    "gemini": ProviderSpec("gemini", "Google Gemini", True, "AIza…", "https://aistudio.google.com/app/apikey", ProviderCapabilities(vision=True)),
    "ollama": ProviderSpec("ollama", "Ollama (local)", False, "", "https://ollama.com", ProviderCapabilities(vision=True)),
}
assert tuple(SPECS) == PROVIDER_IDS


def enabled_provider_ids() -> tuple[str, ...]:
    return tuple(p for p in PROVIDER_IDS if p != "ollama" or settings.ollama_enabled)


class NotConfigured(ProviderError):
    def __init__(self, provider: str):
        self.provider = provider
        if provider == "ollama":
            msg = "Ollama isn't set up. Add its URL in Settings → AI Providers."
        else:
            msg = f"AI features need a configured provider. Add your {SPECS.get(provider, SPECS['anthropic']).label} key in Settings → AI Providers."
        super().__init__("invalid_key", msg)


def build_provider(session: Session, owner_id: str, provider_id: str):
    """Raises NotConfigured when the owner hasn't supplied what this provider needs. There is no
    environment-variable or shared fallback key, by design: Catch never pays for AI usage."""
    if provider_id not in PROVIDER_IDS:
        raise ProviderError("bad_request", "Unknown AI provider.")
    if provider_id == "ollama":
        if not settings.ollama_enabled:
            raise ProviderError("unsupported", "Ollama isn't available on this server.")
        from catch.coach.providers.ollama_provider import OllamaProvider

        url = coach_settings.get_coach_settings(session, owner_id)["ollama_base_url"]
        if not url:
            raise NotConfigured("ollama")
        return OllamaProvider(url)
    try:
        key = coach_settings.get_decrypted_credential(session, provider_id, owner_id)
    except SecretStoreError:
        # The server's master secret changed (or the row was damaged): the stored key can't be read.
        raise ProviderError(
            "invalid_key",
            "Your stored key can't be read any more (the server's encryption secret changed). Re-enter it in Settings → AI Providers.",
        ) from None
    if not key:
        raise NotConfigured(provider_id)
    if provider_id == "anthropic":
        from catch.coach.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(key)
    if provider_id == "openai":
        from catch.coach.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(key)
    from catch.coach.providers.gemini_provider import GeminiProvider

    return GeminiProvider(key)


def looks_vision_capable(provider_id: str, model_id: str) -> bool | None:
    """Pattern hint for providers whose model listing doesn't say (OpenAI, Gemini)."""
    patterns = _CATALOG["providers"].get(provider_id, {}).get("vision_patterns", [])
    return True if any(model_id.lower().startswith(p) or p in model_id.lower() for p in patterns) else None


def configured(session: Session, owner_id: str = OWNER_ID) -> list[str]:
    out = coach_settings.configured_providers(session, owner_id)
    if settings.ollama_enabled and coach_settings.get_coach_settings(session, owner_id)["ollama_base_url"]:
        out.append("ollama")
    return out


__all__ = ["enabled_provider_ids", "KEY_PROVIDERS", "PROVIDER_IDS", "SPECS", "NotConfigured", "build_provider", "configured", "looks_vision_capable"]
