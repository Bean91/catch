from __future__ import annotations

import base64

from sqlmodel import Session

from catch.coach import cost as cost_module
from catch.coach import settings as coach_settings_module

_MAX_TOKENS = 2048

# Structured output via a strict, auto-chosen tool rather than forced tool_choice: newer
# models (Claude Opus 5.5, Sonnet 5.5, Fable 5.1) return a 400 on tool_choice "any"/"tool",
# and this app's model is whatever the athlete configured in Settings, not a model this code
# controls (see the claude-api skill's "forced tool use removed" note). An explicit system
# instruction plus `strict: true` gets the same reliably-structured result without depending
# on a feature some configured models reject outright.
_TOOL = {
    "name": "record_meal_estimate",
    "description": "Record an itemized macro estimate for the food visible in the photo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "quantity_description": {"type": "string", "description": "e.g. '1 cup', '150g', '1 medium banana'"},
                        "kcal": {"type": "number"},
                        "protein_g": {"type": "number"},
                        "carbs_g": {"type": "number"},
                        "fat_g": {"type": "number"},
                    },
                    "required": ["name", "quantity_description", "kcal", "protein_g", "carbs_g", "fat_g"],
                    "additionalProperties": False,
                },
            },
            "notes": {"type": "string", "description": "Caveats about the estimate's accuracy — always mention this is an estimate."},
        },
        "required": ["items", "notes"],
        "additionalProperties": False,
    },
    "strict": True,
}

_SYSTEM_PROMPT = (
    "You are estimating the macro content of a meal from a photo for a rowing athlete's nutrition log. Always "
    "call record_meal_estimate with your best itemized guess — one entry per distinct food item you can "
    "identify, with a plausible quantity and its kcal/protein/carbs/fat. Never respond with plain text instead "
    "of calling the tool. Be honest in `notes` about what's uncertain (hidden ingredients, oil/sauce you can't "
    "see, portion size from a single angle) — this is always shown to the athlete labelled as an estimate they "
    "can edit, never treated as exact."
)


class NutritionVisionError(RuntimeError):
    pass


def estimate_meal_photo(session: Session, image_bytes: bytes, media_type: str) -> dict:
    """Task Part B.4. One-shot vision call against the athlete's own configured Anthropic
    key/model — never a hardcoded model, since this app is bring-your-own-key and the
    photo-estimate should cost (and behave) like the model the athlete actually chose.
    Raises `NutritionVisionError` for every failure mode (no key, cap reached, API error, the
    model not calling the tool) so the route layer turns each into a clear 4xx rather than a
    500 a photo-taking UI can't do anything useful with. The photo itself is never written to
    disk or logged — only its bytes pass through this call."""
    prefs = coach_settings_module.get_coach_settings(session)
    api_key = coach_settings_module.get_decrypted_credential(session, "anthropic")
    if not api_key:
        raise NutritionVisionError("No Anthropic API key configured — add one in Settings to use photo estimates.")
    model = prefs["anthropic_model"]
    if not model:
        raise NutritionVisionError("No Anthropic model selected — pick one in Settings.")

    cap = prefs["daily_cap_usd"]
    if cap is not None and cost_module.today_spend_usd(session) >= cap:
        raise NutritionVisionError("Today's coach spend cap has been reached — photo estimates share the same cap.")

    # Lazy import: the Pi pays the anthropic SDK's import cost only when the coach (or this
    # feature) is actually used, not on every process start (CLAUDE.md's Pi-memory rule).
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    image_b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL],
            tool_choice={"type": "auto"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                        {"type": "text", "text": "Estimate the macros for this meal."},
                    ],
                }
            ],
        )
    except anthropic.APIError as exc:
        raise NutritionVisionError(f"Anthropic API error: {exc}") from exc

    usage = {
        "input_tokens": response.usage.input_tokens or 0,
        "output_tokens": response.usage.output_tokens or 0,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    prices = prefs["prices"].get(model, {})
    turn_cost = cost_module.estimate_cost_usd(prices, usage)
    cost_module.record_usage_event(session, "nutrition_photo_estimate", usage, turn_cost)

    tool_block = next((b for b in response.content if b.type == "tool_use" and b.name == "record_meal_estimate"), None)
    if tool_block is None:
        raise NutritionVisionError("The model didn't return a structured estimate — try again or enter the meal manually.")

    result = tool_block.input
    return {"items": result.get("items", []), "notes": result.get("notes", ""), "cost_usd": turn_cost}
