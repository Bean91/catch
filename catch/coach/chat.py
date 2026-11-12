from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from sqlmodel import Session, select

import time

from catch.coach import cost, limits, memory
from catch.coach import settings as coach_settings_module
from catch.coach import tools as tools_module
from catch.coach.providers import registry
from catch.coach.providers.anthropic_provider import pick_default_sonnet
from catch.coach.providers.base import ProviderError, safe_error_event
from catch.core.models import CoachConversation, CoachMessage
from catch.core.principal import ATHLETE, OWNER_ID
from catch.core.redact import redact

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.md"
# Caps one user turn's tool-calling back-and-forth — a runaway loop (a tool the model keeps
# re-calling) must not spin forever or silently rack up API spend past the daily cap check.
_MAX_TOOL_ITERATIONS = 8


def load_system_prompt() -> str:
    return _SYSTEM_PROMPT_PATH.read_text()


def _load_history(session: Session, conversation_id: int) -> list[dict]:
    rows = session.exec(
        select(CoachMessage).where(CoachMessage.conversation_id == conversation_id).order_by(CoachMessage.id)
    ).all()
    return [{"role": r.role, "blocks": json.loads(r.blocks_json)} for r in rows]


def _save_message(
    session: Session,
    conversation_id: int,
    role: str,
    blocks: list[dict],
    provider: str | None = None,
    model: str | None = None,
    usage: dict | None = None,
    cost_usd: float | None = None,
) -> CoachMessage:
    row = CoachMessage(
        conversation_id=conversation_id,
        role=role,
        blocks_json=json.dumps(blocks),
        provider=provider,
        model=model,
        usage_json=json.dumps(usage) if usage else None,
        cost_usd=cost_usd,
    )
    session.add(row)
    conv = session.get(CoachConversation, conversation_id)
    if conv is not None:
        conv.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(row)
    return row


def _range_phrase(args: dict) -> str:
    if args.get("from") or args.get("to"):
        return f" ({args.get('from', '…')} to {args.get('to', 'now')})"
    return ""


def _tool_label(name: str, args: dict) -> str:
    """Short, human phrasing for the UI's expandable tool-call chip — illustrative templates,
    not a literal transcript of the tool name/args."""
    labels = {
        "get_today": "Read today's recovery and strain",
        "get_wellness": f"Read wellness history{_range_phrase(args)}",
        "list_workouts": "Read recent workouts",
        "get_workout": f"Read workout #{args.get('id')}",
        "get_trends": f"Read {args.get('metric', 'a')} trend{_range_phrase(args)}",
        "get_body_comp": f"Read body-composition history{_range_phrase(args)}",
        "get_load": "Read current training load",
        "predict_2k": "Predict 2k time",
        "get_zones": "Read training zones",
        "add_note": f"Save a note for {args.get('date')}",
        "rename_activity": f"Rename workout #{args.get('id')} to \"{args.get('title')}\"",
        "tag_activity": f"Tag workout #{args.get('id')}",
        "merge_activities": "Merge two workouts" if args.get("confirm") else "Preview merging two workouts",
        "remember": f"Remember a {args.get('category')} fact",
        "add_event": f"Add event: {args.get('name')}",  # retired tool; kept so old conversations still render
        "create_event": f"Add event: {args.get('name')}" if args.get("confirm") else f"Preview adding event: {args.get('name')}",
        "update_event": f"Update event #{args.get('id')}" if args.get("confirm") else f"Preview updating event #{args.get('id')}",
        "get_calendar": f"Read calendar ({args.get('from')} to {args.get('to')})",
        "get_upcoming_events": "Read upcoming events",
        "get_event": f"Read event #{args.get('id')}",
        "get_training_phase": "Read training phase",
        "create_planned_workout": "Add planned session" if args.get("confirm") else "Preview adding a planned session",
        "update_planned_workout": f"Update planned session #{args.get('id')}" if args.get("confirm") else f"Preview changing planned session #{args.get('id')}",
        "delete_planned_workout": f"Delete planned session #{args.get('id')}" if args.get("confirm") else f"Preview deleting planned session #{args.get('id')}",
        "set_goal": "Save goal",
        "forget": f"Forget {args.get('ref')}",
        "recall": "Search memory",
        "get_nutrition": f"Read nutrition history{_range_phrase(args)}",
        "log_food": f"Log {args.get('description') or args.get('barcode') or 'a food'}",
        "log_strength": "Log a set" if args.get("confirm") else "Preview a logged set",
        "get_strength": f"Read strength history{_range_phrase(args)}",
        "get_muscle_readiness": "Read muscle readiness",
        "get_tests": "Read erg tests",
        "get_test": f"Read test #{args.get('id')}",
        "make_pacing_plan": f"Build a {args.get('test_type', '')} pacing plan".strip(),
        "get_route": f"Read the GPS route of workout #{args.get('activity_id')}",
        "get_route_history": f"Read history of route #{args.get('route_id')}",
        "get_on_water_metrics": f"Read GPS metrics of workout #{args.get('activity_id')}",
        "get_workout_weather": f"Read weather for workout #{args.get('activity_id')}",
        "search_workout_library": "Search the workout library",
        "get_workout_template": f"Read workout template #{args.get('id')}",
        "create_workout_template": f"Create template: {args.get('name')}" if args.get("confirm") else f"Preview creating template: {args.get('name')}",
        "update_workout_template": f"Update template #{args.get('id')}" if args.get("confirm") else f"Preview updating template #{args.get('id')}",
        "get_technique_notes": "Read technique notes",
        "add_technique_note": "Save a technique note" if args.get("confirm") else "Preview a technique note",
        "get_coach_feedback": "Read coach feedback",
        "add_coach_feedback": "Save feedback" if args.get("confirm") else "Preview feedback",
    }
    return labels.get(name, name)


async def _resolve_provider(session: Session, owner_id: str = OWNER_ID):
    """(provider, model, prices, provider_id). Raises ProviderError (NotConfigured when the owner
    hasn't supplied a key). `prices` is None for a hosted model the user hasn't priced — its cost is
    unknown, which is different from free."""
    prefs = coach_settings_module.get_coach_settings(session, owner_id)
    provider_id = prefs["provider"]
    provider = registry.build_provider(session, owner_id, provider_id)
    model = prefs["models"].get(provider_id)
    if not model and provider_id == "anthropic":
        model = pick_default_sonnet(await provider.list_models())
        if model:
            coach_settings_module.update_coach_settings(session, {"anthropic_model": model}, owner_id)
    if not model:
        label = registry.SPECS[provider_id].label
        raise ProviderError("bad_request", f"No {label} model is selected. Pick one in Settings → AI Providers.")
    prices = {} if provider_id == "ollama" else prefs["prices"].get(model)  # local -> always $0
    return provider, model, prices, provider_id


def _switch_options(session: Session, owner_id: str, current: str) -> list[str]:
    return [p for p in registry.configured(session, owner_id) if p != current]


def _remember_status(session: Session, provider_id: str, owner_id: str, kind: str | None) -> None:
    if provider_id not in registry.KEY_PROVIDERS:
        return
    if kind is None:
        coach_settings_module.set_status(session, provider_id, "valid", None, owner_id)
    elif kind == "invalid_key":
        coach_settings_module.set_status(session, provider_id, "invalid", "rejected_by_provider", owner_id)
    elif kind in ("unavailable", "timeout"):
        coach_settings_module.set_status(session, provider_id, "unavailable", "timed_out" if kind == "timeout" else "provider_unreachable", owner_id)
    elif kind == "quota":
        coach_settings_module.set_status(session, provider_id, "unavailable", "quota_exceeded", owner_id)
    elif kind == "rate_limited":
        coach_settings_module.set_status(session, provider_id, "unavailable", "rate_limited", owner_id)


async def run_turn(session: Session, conversation_id: int, user_text: str, owner_id: str = OWNER_ID) -> AsyncIterator[dict]:
    conv = session.get(CoachConversation, conversation_id)
    if conv is None or conv.owner_id != owner_id:
        yield {"type": "error", "message": "Conversation not found."}
        return
    try:
        limits.check_message(user_text)
        limits.check_rate(owner_id, "chat")
        slot = limits.stream_slot(owner_id)
        slot.__enter__()
    except limits.LimitExceeded as exc:
        yield {"type": "rate_limited", "message": exc.message, "retry_after_s": exc.retry_after_s}
        return
    try:
        async for event in _run_turn(session, conversation_id, user_text, owner_id):
            yield event
    finally:
        slot.__exit__(None, None, None)


async def _run_turn(session: Session, conversation_id: int, user_text: str, owner_id: str) -> AsyncIterator[dict]:
    prefs = coach_settings_module.get_coach_settings(session, owner_id)
    cap = prefs["daily_cap_usd"]
    token_cap = prefs["daily_token_cap"]

    def over_cap() -> dict | None:
        if cap is not None and cost.today_spend_usd(session, owner_id=owner_id) >= cap:
            return {"type": "cap_reached", "reason": "usd", "daily_spend_usd": cost.today_spend_usd(session, owner_id=owner_id), "daily_cap_usd": cap}
        if token_cap is not None and cost.today_tokens(session, owner_id=owner_id) >= token_cap:
            return {"type": "cap_reached", "reason": "tokens", "daily_tokens": cost.today_tokens(session, owner_id=owner_id), "daily_token_cap": token_cap}
        return None

    if (event := over_cap()) is not None:
        yield event
        return

    try:
        provider, model, prices, provider_id = await _resolve_provider(session, owner_id)
    except registry.NotConfigured as exc:
        yield {"type": "ai_not_configured", "message": exc.user_message, "provider": exc.provider, "switch_to": _switch_options(session, owner_id, exc.provider)}
        return
    except ProviderError as exc:
        _remember_status(session, prefs["provider"], owner_id, exc.kind)
        yield {**safe_error_event(exc), "switch_to": _switch_options(session, owner_id, prefs["provider"])}
        return

    if provider.name == "ollama" and not await provider.health_check():
        yield {
            "type": "provider_unavailable",
            "message": "Ollama isn't reachable at the configured URL — the laptop may be asleep.",
            "can_switch_to": _switch_options(session, owner_id, "ollama"),
        }
        return

    history = _load_history(session, conversation_id)
    user_blocks = [{"type": "text", "text": user_text}]
    _save_message(session, conversation_id, "user", user_blocks)
    history.append({"role": "user", "blocks": user_blocks})

    system_blocks = [
        {"text": load_system_prompt(), "cache": True},
        {"text": memory.memory_block(session), "cache": False},
    ]

    deadline = time.monotonic() + limits.TURN_WALL_CLOCK_S
    for _ in range(_MAX_TOOL_ITERATIONS):
        if (event := over_cap()) is not None:
            yield event
            return

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        usage: dict | None = None
        stop_reason: str | None = None
        async for event in provider.stream_turn(system_blocks=system_blocks, messages=limits.trim_history(history), model=model):
            if time.monotonic() > deadline:
                yield safe_error_event(ProviderError("timeout", "This reply took too long and was stopped."))
                return
            if event["type"] == "text_delta":
                text_parts.append(event["text"])
                yield {"type": "text", "text": event["text"]}
            elif event["type"] == "tool_call":
                tool_calls.append(event)
            elif event["type"] == "usage":
                usage = event["usage"]
            elif event["type"] == "stop":
                stop_reason = event["stop_reason"]
            elif event["type"] == "error":
                _remember_status(session, provider_id, owner_id, event.get("kind"))
                yield {**event, "message": redact(event["message"]), "switch_to": _switch_options(session, owner_id, provider_id)}
                return

        assistant_blocks: list[dict] = []
        full_text = "".join(text_parts)
        if full_text:
            assistant_blocks.append({"type": "text", "text": full_text})
        for call in tool_calls:
            block = {"type": "tool_call", "id": call["id"], "name": call["name"], "input": call["input"]}
            if call.get("provider_meta"):
                block["provider_meta"] = call["provider_meta"]
            assistant_blocks.append(block)

        turn_cost = cost.estimate_cost_usd(prices, usage) if usage else None
        _save_message(
            session, conversation_id, "assistant", assistant_blocks, provider=provider.name, model=model, usage=usage, cost_usd=turn_cost
        )
        history.append({"role": "assistant", "blocks": assistant_blocks})
        _remember_status(session, provider_id, owner_id, None)

        if usage:
            yield {
                "type": "usage",
                "usage": usage,
                "cost_usd": turn_cost,
                "cost_known": turn_cost is not None,
                "daily_spend_usd": cost.today_spend_usd(session, owner_id=owner_id),
                "daily_cap_usd": cap,
            }

        if not tool_calls:
            yield {"type": "done", "stop_reason": stop_reason}
            return

        tool_result_blocks: list[dict] = []
        for call in tool_calls:
            yield {
                "type": "tool_call",
                "id": call["id"],
                "name": call["name"],
                "input": call["input"],
                "label": _tool_label(call["name"], call["input"]),
            }
            try:
                output = tools_module.call_tool(session, call["name"], call["input"], ctx={"conversation_id": conversation_id, "principal": ATHLETE, "via": "ai_coach"})
                is_error = False
            except Exception as exc:  # noqa: BLE001 — surfaced to the model as a tool error, not raised
                output = {"error": redact(str(exc))}
                is_error = True
            yield {"type": "tool_result", "id": call["id"], "output": output, "is_error": is_error}
            tool_result_blocks.append({"type": "tool_result", "id": call["id"], "output": output, "is_error": is_error})

        _save_message(session, conversation_id, "user", tool_result_blocks)
        history.append({"role": "user", "blocks": tool_result_blocks})

    yield {"type": "error", "message": "Stopped after too many tool calls in one turn."}
