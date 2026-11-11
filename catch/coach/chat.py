from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from sqlmodel import Session, select

from catch.coach import cost, memory
from catch.coach import settings as coach_settings_module
from catch.coach import tools as tools_module
from catch.coach.providers.anthropic_provider import AnthropicProvider, pick_default_sonnet
from catch.coach.providers.ollama_provider import OllamaProvider
from catch.core.models import CoachConversation, CoachMessage

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
        "add_event": f"Add event: {args.get('name')}",
        "update_event": f"Update event #{args.get('id')}",
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
    }
    return labels.get(name, name)


async def _resolve_provider(session: Session) -> tuple[AnthropicProvider | OllamaProvider, str, dict]:
    prefs = coach_settings_module.get_coach_settings(session)
    if prefs["provider"] == "ollama":
        if not prefs["ollama_base_url"]:
            raise ValueError("No Ollama URL configured — set one in Settings.")
        model = prefs["ollama_model"]
        if not model:
            raise ValueError("No Ollama model selected — pick one in Settings.")
        return OllamaProvider(prefs["ollama_base_url"]), model, {}  # local -> always $0

    api_key = coach_settings_module.get_decrypted_credential(session, "anthropic")
    if not api_key:
        raise ValueError("No Anthropic API key configured — add one in Settings.")
    provider = AnthropicProvider(api_key)
    model = prefs["anthropic_model"]
    if not model:
        models = await provider.list_models()
        model = pick_default_sonnet(models)
        if not model:
            raise ValueError("Couldn't find a Sonnet model on this account — pick one manually in Settings.")
        coach_settings_module.update_coach_settings(session, {"anthropic_model": model})
    prices = prefs["prices"].get(model, {})
    return provider, model, prices


async def run_turn(session: Session, conversation_id: int, user_text: str) -> AsyncIterator[dict]:
    prefs = coach_settings_module.get_coach_settings(session)
    cap = prefs["daily_cap_usd"]
    if cap is not None and cost.today_spend_usd(session) >= cap:
        yield {"type": "cap_reached", "daily_spend_usd": cost.today_spend_usd(session), "daily_cap_usd": cap}
        return

    try:
        provider, model, prices = await _resolve_provider(session)
    except ValueError as exc:
        yield {"type": "error", "message": str(exc)}
        return

    if provider.name == "ollama" and not await provider.health_check():
        yield {
            "type": "provider_unavailable",
            "message": "Ollama isn't reachable at the configured URL — the laptop may be asleep.",
            "can_switch_to": "anthropic",
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

    for _ in range(_MAX_TOOL_ITERATIONS):
        if cap is not None and cost.today_spend_usd(session) >= cap:
            yield {"type": "cap_reached", "daily_spend_usd": cost.today_spend_usd(session), "daily_cap_usd": cap}
            return

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        usage: dict | None = None
        stop_reason: str | None = None
        async for event in provider.stream_turn(system_blocks=system_blocks, messages=history, model=model):
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
                yield event
                return

        assistant_blocks: list[dict] = []
        full_text = "".join(text_parts)
        if full_text:
            assistant_blocks.append({"type": "text", "text": full_text})
        for call in tool_calls:
            assistant_blocks.append({"type": "tool_call", "id": call["id"], "name": call["name"], "input": call["input"]})

        turn_cost = cost.estimate_cost_usd(prices, usage) if usage else None
        _save_message(
            session, conversation_id, "assistant", assistant_blocks, provider=provider.name, model=model, usage=usage, cost_usd=turn_cost
        )
        history.append({"role": "assistant", "blocks": assistant_blocks})

        if usage:
            yield {
                "type": "usage",
                "usage": usage,
                "cost_usd": turn_cost,
                "daily_spend_usd": cost.today_spend_usd(session),
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
                output = tools_module.call_tool(session, call["name"], call["input"], ctx={"conversation_id": conversation_id})
                is_error = False
            except Exception as exc:  # noqa: BLE001 — surfaced to the model as a tool error, not raised
                output = {"error": str(exc)}
                is_error = True
            yield {"type": "tool_result", "id": call["id"], "output": output, "is_error": is_error}
            tool_result_blocks.append({"type": "tool_result", "id": call["id"], "output": output, "is_error": is_error})

        _save_message(session, conversation_id, "user", tool_result_blocks)
        history.append({"role": "user", "blocks": tool_result_blocks})

    yield {"type": "error", "message": "Stopped after too many tool calls in one turn."}
