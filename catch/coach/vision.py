"""Shared plumbing for the one-shot photo features (meal estimate, PM5 piece reading): resolve the
owner's active provider, check it can read images, enforce the same caps as chat, call
`vision_structured`, and record the spend. The photo itself is never stored here."""

from __future__ import annotations

from sqlmodel import Session

from catch.coach import cost as cost_module
from catch.coach import limits
from catch.coach import settings as coach_settings_module
from catch.coach.providers import registry
from catch.coach.providers.base import ProviderError, VisionRequest
from catch.core.principal import OWNER_ID


class VisionError(RuntimeError):
    """str(exc) is always safe to show the user."""


async def vision_available(session: Session, owner_id: str = OWNER_ID) -> dict:
    """What the UI needs to decide whether to offer a photo button: no provider call is made."""
    prefs = coach_settings_module.get_coach_settings(session, owner_id)
    provider_id = prefs["provider"]
    configured = provider_id in registry.configured(session, owner_id)
    model = prefs["models"].get(provider_id)
    spec = registry.SPECS[provider_id]
    available = configured and bool(model) and spec.capabilities.vision
    reason = None
    if not configured:
        reason = "not_configured"
    elif not model:
        reason = "no_model"
    elif not spec.capabilities.vision:
        reason = "unsupported"
    return {"available": available, "provider": provider_id, "reason": reason}


async def run_vision(session: Session, kind: str, req: VisionRequest, owner_id: str = OWNER_ID) -> tuple[dict, float | None]:
    try:
        limits.check_rate(owner_id, "vision")
    except limits.LimitExceeded as exc:
        raise VisionError(exc.message) from None
    prefs = coach_settings_module.get_coach_settings(session, owner_id)
    provider_id = prefs["provider"]
    try:
        provider = registry.build_provider(session, owner_id, provider_id)
    except ProviderError as exc:
        raise VisionError(exc.user_message) from None
    label = registry.SPECS[provider_id].label
    if not provider.capabilities.vision:
        raise VisionError(f"{label} can't read photos. Switch to a provider that can in Settings → AI Providers.")
    model = prefs["models"].get(provider_id)
    if not model:
        raise VisionError(f"No {label} model is selected. Pick one in Settings → AI Providers.")

    if prefs["daily_cap_usd"] is not None and cost_module.today_spend_usd(session, owner_id=owner_id) >= prefs["daily_cap_usd"]:
        raise VisionError("Today's AI spend cap has been reached — photo features share the same cap.")
    if prefs["daily_token_cap"] is not None and cost_module.today_tokens(session, owner_id=owner_id) >= prefs["daily_token_cap"]:
        raise VisionError("Today's AI token cap has been reached — photo features share the same cap.")

    if provider_id == "ollama":
        # Ollama reports vision per model; hosted providers either report it in their model
        # listing (Anthropic) or surface a clear API error when a model can't take images.
        models = await provider.list_models()
        match = next((m for m in models if m["id"] == model), None)
        if match is not None and match.get("vision") is False:
            raise VisionError(f"The Ollama model '{model}' can't read photos. Pick a vision-capable model in Settings → AI Providers.")

    try:
        result, usage = await provider.vision_structured(model, req)
    except ProviderError as exc:
        coach_settings_module.set_status(session, provider_id, "invalid", "rejected_by_provider", owner_id) if exc.kind == "invalid_key" and provider_id != "ollama" else None
        raise VisionError(exc.user_message) from None

    prices = {} if provider_id == "ollama" else prefs["prices"].get(model)
    turn_cost = cost_module.estimate_cost_usd(prices, usage)
    cost_module.record_usage_event(session, kind, usage, turn_cost, owner_id, provider_id, model)
    return result, turn_cost
