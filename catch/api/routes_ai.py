"""Settings → AI Providers. Cookie-only (like the rest of the coach's management surface): a
device token, an MCP client and a coach token never reach these routes. No response ever
contains a key — only `configured`, the last four characters of a long key, and a status."""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, SecretStr
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from catch.api.deps import get_db, require_auth
from catch.coach import cost as cost_module
from catch.coach import limits
from catch.coach import settings as coach_settings
from catch.coach.providers import registry
from catch.coach.providers.base import KEY_PROVIDERS, ProviderError
from catch.coach.vision import vision_available
from catch.core.owner import current_owner_id

router = APIRouter(dependencies=[Depends(require_auth)])

# Session 33: a provider's model list changes rarely and each fetch is a network call (Gemini pages up to 10 times, Ollama asks
# about every model). Kept per (owner, provider) for 10 minutes in this process, dropped when that key is saved, removed or tested.
_MODELS_TTL_S = 600
_models_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_models_lock = threading.Lock()


def _forget_models(owner_id: str, provider_id: str) -> None:
    with _models_lock:
        _models_cache.pop((owner_id, provider_id), None)


def _spec_or_404(provider_id: str) -> registry.ProviderSpec:
    spec = registry.SPECS.get(provider_id) if provider_id in registry.enabled_provider_ids() else None
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown AI provider")
    return spec


def _card(db: Session, owner_id: str, spec: registry.ProviderSpec, prefs: dict) -> dict:
    if spec.needs_key:
        info = coach_settings.masked_credential_info(db, spec.id, owner_id)
        configured = info["configured"]
        status = info["status"]
    else:
        url = prefs["ollama_base_url"]
        info = {"last4": None, "status_detail": None, "status_checked_at": None}
        configured = bool(url)
        status = "configured" if configured else "not_configured"
    return {
        "id": spec.id,
        "label": spec.label,
        "needs_key": spec.needs_key,
        "key_hint": spec.key_hint,
        "docs_url": spec.docs_url,
        "capabilities": spec.capabilities.as_dict(),
        "configured": configured,
        "last4": info["last4"],
        "status": status,
        "status_detail": info["status_detail"],
        "status_checked_at": info["status_checked_at"],
        "model": prefs["models"].get(spec.id),
        "base_url": prefs["ollama_base_url"] if spec.id == "ollama" else None,
        "active": prefs["provider"] == spec.id and configured,
    }


def _cards(db: Session, owner_id: str, prefs: dict | None = None) -> dict:
    prefs = prefs if prefs is not None else coach_settings.get_coach_settings(db, owner_id)
    cards = [_card(db, owner_id, registry.SPECS[p], prefs) for p in registry.enabled_provider_ids()]
    active = next((c["id"] for c in cards if c["active"]), None)
    return {"active": active, "providers": cards}


@router.get("/api/ai/providers")
def get_providers(db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    """Stored configuration only — no key is decrypted and no provider is called (session 33). A plain `def`: it was an `async def`
    doing blocking database reads on the event loop, which on the public build's three-connection pool deadlocked the whole
    Settings page for the 30 s pool timeout (tests/test_settings_concurrency.py)."""
    prefs = coach_settings.get_coach_settings(db, owner_id)
    out = _cards(db, owner_id, prefs)
    configured = [c["id"] for c in out["providers"] if c["configured"]]
    out["vision"] = vision_available(db, owner_id, prefs=prefs, configured=configured if settings_ollama_ok(prefs) else [c for c in configured if c != "ollama"])
    return out


def settings_ollama_ok(prefs: dict) -> bool:
    from catch.core.config import settings as app_settings

    return bool(app_settings.ollama_enabled and prefs["ollama_base_url"])


class KeyBody(BaseModel):
    api_key: SecretStr


def _throttle(owner_id: str) -> None:
    try:
        limits.check_rate(owner_id, "admin")
    except limits.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message) from None


@router.put("/api/ai/providers/{provider_id}/key")
async def put_key(
    provider_id: str,
    body: KeyBody,
    validate: bool = Query(True),
    db: Session = Depends(get_db),
    owner_id: str = Depends(current_owner_id),
):
    spec = _spec_or_404(provider_id)
    if not spec.needs_key:
        raise HTTPException(status_code=422, detail=f"{spec.label} doesn't use an API key")
    raw = body.api_key.get_secret_value().strip()
    if not raw:
        raise HTTPException(status_code=422, detail="The key is empty.")
    _throttle(owner_id)

    outcome: dict | None = None
    if validate:
        # Validate the *candidate* key before it replaces anything: a typo must not destroy a
        # working key.
        from catch.coach.providers import anthropic_provider, gemini_provider, openai_provider

        candidate = {
            "anthropic": anthropic_provider.AnthropicProvider,
            "openai": openai_provider.OpenAIProvider,
            "gemini": gemini_provider.GeminiProvider,
        }[provider_id](raw)
        outcome = await candidate.validate()
        if not outcome["ok"] and outcome["kind"] == "invalid_key":
            raise HTTPException(status_code=422, detail=outcome["message"])

    def save() -> dict:
        coach_settings.set_credential(db, provider_id, raw, owner_id)
        if outcome is not None:
            if outcome["ok"]:
                coach_settings.set_status(db, provider_id, "valid", None, owner_id)
            else:
                detail = {"timeout": "timed_out", "rate_limited": "rate_limited", "quota": "quota_exceeded"}.get(outcome["kind"], "provider_unreachable")
                coach_settings.set_status(db, provider_id, "unavailable", detail, owner_id)
        return _card(db, owner_id, spec, coach_settings.get_coach_settings(db, owner_id))

    _forget_models(owner_id, provider_id)
    card = await run_in_threadpool(save)
    return {**card, "validated": bool(outcome and outcome["ok"]), "validation_message": outcome["message"] if outcome else None}


@router.delete("/api/ai/providers/{provider_id}/key")
def delete_key(provider_id: str, db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    spec = _spec_or_404(provider_id)
    if provider_id not in KEY_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"{spec.label} doesn't use an API key")
    coach_settings.delete_credential(db, provider_id, owner_id)
    _forget_models(owner_id, provider_id)
    return _cards(db, owner_id)


@router.post("/api/ai/providers/{provider_id}/test")
async def test_provider(provider_id: str, db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    spec = _spec_or_404(provider_id)
    _throttle(owner_id)
    _forget_models(owner_id, provider_id)
    try:
        provider = await run_in_threadpool(_build_and_release, db, owner_id, provider_id)
    except ProviderError as exc:
        return {"ok": False, "kind": exc.kind, "message": exc.user_message, "model_count": None}
    result = await provider.validate()
    if provider_id in KEY_PROVIDERS:
        if result["ok"]:
            status = ("valid", None)
        elif result["kind"] == "invalid_key":
            status = ("invalid", "rejected_by_provider")
        else:
            status = ("unavailable", {"timeout": "timed_out", "rate_limited": "rate_limited", "quota": "quota_exceeded"}.get(result["kind"], "provider_unreachable"))
        await run_in_threadpool(coach_settings.set_status, db, provider_id, status[0], status[1], owner_id)
    return {**result, "provider": spec.id}


def _build_and_release(db: Session, owner_id: str, provider_id: str):
    """Decrypt the key and build the provider, then end the read transaction so no pooled connection is held during the
    network call that follows. Runs in the threadpool."""
    provider = registry.build_provider(db, owner_id, provider_id)
    db.commit()
    return provider


@router.get("/api/ai/providers/{provider_id}/models")
async def provider_models(provider_id: str, db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    """The live model list, fetched only when the athlete opens the model picker (the page shows the saved model without it) and
    then served from a 10-minute cache — so opening Settings never calls a provider (session 33)."""
    _spec_or_404(provider_id)
    with _models_lock:
        hit = _models_cache.get((owner_id, provider_id))
    if hit is not None and time.monotonic() - hit[0] < _MODELS_TTL_S:
        return {"models": hit[1], "error": None, "kind": None, "cached": True}
    _throttle(owner_id)
    try:
        provider = await run_in_threadpool(_build_and_release, db, owner_id, provider_id)
        models = await provider.list_models()
    except ProviderError as exc:
        return {"models": [], "error": exc.user_message, "kind": exc.kind}
    for m in models:
        if m.get("vision") is None:
            m["vision"] = registry.looks_vision_capable(provider_id, m["id"])
    with _models_lock:
        _models_cache[(owner_id, provider_id)] = (time.monotonic(), models)
        while len(_models_cache) > 512:
            _models_cache.pop(next(iter(_models_cache)))
    return {"models": models, "error": None, "kind": None, "cached": False}


class ActiveBody(BaseModel):
    provider: str
    model: str | None = None


@router.put("/api/ai/active")
def put_active(body: ActiveBody, db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    spec = _spec_or_404(body.provider)
    if body.provider not in registry.configured(db, owner_id):
        raise HTTPException(status_code=409, detail=f"{spec.label} isn't set up yet — add its {'key' if spec.needs_key else 'URL'} first.")
    patch: dict = {"provider": body.provider}
    if body.model is not None:
        patch["models"] = {body.provider: body.model.strip() or None}
    try:
        coach_settings.update_coach_settings(db, patch, owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _cards(db, owner_id)


@router.get("/api/ai/usage")
def get_usage(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), owner_id: str = Depends(current_owner_id)):
    prefs = coach_settings.get_coach_settings(db, owner_id)
    return {
        **cost_module.usage_summary(db, owner_id, days),
        "today": {
            "spend_usd": cost_module.today_spend_usd(db, owner_id=owner_id),
            "tokens": cost_module.today_tokens(db, owner_id=owner_id),
            "cap_usd": prefs["daily_cap_usd"],
            "token_cap": prefs["daily_token_cap"],
        },
        # None of Anthropic, OpenAI or Gemini document a balance/spend endpoint for an ordinary
        # API key, so Catch never shows one. See docs/ai-providers.md.
        "provider_balance": None,
        "source": "recorded_by_catch",
    }


# --- What is shared with the AI provider (session 28; docs/ai-data-sharing.md) --------------------------------------------------


class SharingBody(BaseModel):
    acknowledge: bool = False
    categories: dict[str, bool] = {}
    age_band: str | None = None
    guardian_ack: bool = False


@router.get("/api/ai/sharing")
def get_sharing(db: Session = Depends(get_db)):
    from catch.coach import ai_sharing

    return ai_sharing.state(db)


@router.put("/api/ai/sharing")
def put_sharing(body: SharingBody, db: Session = Depends(get_db)):
    from catch.coach import ai_sharing

    try:
        return ai_sharing.update(db, acknowledge=body.acknowledge, categories=body.categories, age_band=body.age_band, guardian_ack=body.guardian_ack)
    except ai_sharing.SharingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.delete("/api/ai/sharing")
def withdraw_sharing(db: Session = Depends(get_db)):
    """Withdraw consent: every category off and the AI refuses until it is given again."""
    from catch.coach import ai_sharing

    return ai_sharing.revoke(db)
