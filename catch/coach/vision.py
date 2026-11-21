"""Shared plumbing for the one-shot photo features (meal estimate, PM5 piece reading): resolve the
owner's active provider, check it can read images, enforce the same caps as chat, call
`vision_structured`, and record the spend. The photo itself is never stored here."""

from __future__ import annotations

from catch.core.tenant import current_owner
from sqlmodel import Session

from catch.coach import ai_sharing
from catch.coach import cost as cost_module
from catch.coach import limits
from catch.coach import settings as coach_settings_module
from catch.coach.providers import registry
from catch.coach.providers.base import ProviderError, VisionRequest


class VisionError(RuntimeError):
    """str(exc) is always safe to show the user."""


def vision_available(session: Session, owner_id: str | None = None, prefs: dict | None = None, configured: list[str] | None = None) -> dict:
    """What the UI needs to decide whether to offer a photo button: no provider call is made. Synchronous (it only reads the
    database), so the route that serves it runs in the threadpool, never on the event loop (session 33)."""
    owner_id = owner_id or current_owner()
    prefs = prefs if prefs is not None else coach_settings_module.get_coach_settings(session, owner_id)
    provider_id = prefs["provider"]
    configured = provider_id in (configured if configured is not None else registry.configured(session, owner_id))
    model = prefs["models"].get(provider_id)
    spec = registry.SPECS[provider_id]
    available = configured and bool(model) and spec.capabilities.vision
    reason = None
    if "photos" not in ai_sharing.enabled_categories(session):
        available, reason = False, "sharing_off"  # the person hasn't agreed to send photos to their provider
    elif not configured:
        reason = "not_configured"
    elif not model:
        reason = "no_model"
    elif not spec.capabilities.vision:
        reason = "unsupported"
    return {"available": available, "provider": provider_id, "reason": reason}


def _prepare(session: Session, owner_id: str):
    """Every database read run_vision needs before the provider call, in one synchronous step that the async caller runs in the
    threadpool — never on the event loop, where waiting for a pooled connection stalls every other request (session 33)."""
    if "photos" not in ai_sharing.enabled_categories(session):
        raise VisionError("Photo reading is switched off: it sends the photo to your AI provider. Turn on \"Photos you ask the coach to read\" in Settings → Privacy → AI sharing.")
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

    # End the read transaction before the provider call (often 5–30 s): on the public build a request holds one of only three
    # pooled connections for as long as its transaction is open, and nothing here needs the database again until the usage row.
    session.commit()
    return provider, prefs, provider_id, model


async def run_vision(session: Session, kind: str, req: VisionRequest, owner_id: str | None = None) -> tuple[dict, float | None]:
    from starlette.concurrency import run_in_threadpool

    owner_id = owner_id or current_owner()
    provider, prefs, provider_id, model = await run_in_threadpool(_prepare, session, owner_id)

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
        if exc.kind == "invalid_key" and provider_id != "ollama":
            await run_in_threadpool(coach_settings_module.set_status, session, provider_id, "invalid", "rejected_by_provider", owner_id)
        raise VisionError(exc.user_message) from None

    prices = {} if provider_id == "ollama" else prefs["prices"].get(model)
    turn_cost = cost_module.estimate_cost_usd(prices, usage)
    await run_in_threadpool(cost_module.record_usage_event, session, kind, usage, turn_cost, owner_id, provider_id, model)
    return result, turn_cost
