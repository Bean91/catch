from __future__ import annotations

from catch.core.tenant import current_owner
from sqlmodel import Session

from catch.coach.providers.base import VisionRequest
from catch.coach.vision import VisionError, run_vision

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


async def estimate_meal_photo(session: Session, image_bytes: bytes, media_type: str, owner_id: str | None = None) -> dict:
    """Task Part B.4. One-shot vision call through the athlete's own active provider and model —
    never a hardcoded one, since this app is bring-your-own-key and the photo-estimate should cost
    (and behave) like the model the athlete actually chose. Raises `NutritionVisionError` for every
    failure mode (no key, no vision support, cap reached, API error, no structured result) so the
    route layer turns each into a clear 4xx. The photo itself is never written to disk or logged."""
    owner_id = owner_id or current_owner()
    try:
        result, turn_cost = await run_vision(
            session,
            "nutrition_photo_estimate",
            VisionRequest(
                system=_SYSTEM_PROMPT,
                user_text="Estimate the macros for this meal.",
                image_bytes=image_bytes,
                media_type=media_type,
                tool={"name": _TOOL["name"], "description": _TOOL["description"], "input_schema": _TOOL["input_schema"]},
                max_tokens=_MAX_TOKENS,
            ),
            owner_id,
        )
    except VisionError as exc:
        raise NutritionVisionError(str(exc)) from None

    return {"items": result.get("items", []), "notes": result.get("notes", ""), "cost_usd": turn_cost}
