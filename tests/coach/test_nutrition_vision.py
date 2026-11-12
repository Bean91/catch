from __future__ import annotations

import asyncio
import sys
import types

import pytest

from catch.coach import settings as coach_settings_module
from catch.coach.nutrition_vision import NutritionVisionError, estimate_meal_photo


def _seed_key_and_model(session, *, model="claude-opus-5-5", daily_cap_usd=None, prices=None):
    coach_settings_module.set_credential(session, "anthropic", "sk-test-key")
    coach_settings_module.update_coach_settings(
        session,
        {"anthropic_model": model, "daily_cap_usd": daily_cap_usd, "prices": {model: prices} if prices else {}},
    )


def _install_fake_anthropic(monkeypatch, *, tool_input=None, no_tool_call=False, raise_api_error=False):
    fake_module = types.ModuleType("anthropic")
    capture: list[dict] = []

    class APIError(Exception):
        pass

    class FakeMessages:
        async def create(self, **kwargs):
            capture.append(kwargs)
            if raise_api_error:
                raise APIError("boom")
            usage = types.SimpleNamespace(input_tokens=1200, output_tokens=150, cache_creation_input_tokens=0, cache_read_input_tokens=0)
            if no_tool_call:
                content = [types.SimpleNamespace(type="text", text="I can't help with that.")]
            else:
                content = [
                    types.SimpleNamespace(
                        type="tool_use",
                        name="record_meal_estimate",
                        input=tool_input
                        or {
                            "items": [
                                {"name": "Grilled chicken breast", "quantity_description": "150g", "kcal": 250, "protein_g": 46, "carbs_g": 0, "fat_g": 6},
                            ],
                            "notes": "Estimate — sauce/oil not visible.",
                        },
                    )
                ]
            return types.SimpleNamespace(content=content, usage=usage)

    class FakeClient:
        def __init__(self, api_key=None, **kwargs):
            self.messages = FakeMessages()

    fake_module.AsyncAnthropic = FakeClient
    fake_module.APIError = APIError
    fake_module.AuthenticationError = type('AuthenticationError', (APIError,), {})
    fake_module.APIConnectionError = type('APIConnectionError', (APIError,), {})
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    return capture


def test_estimate_meal_photo_returns_items_and_notes(session, monkeypatch):
    _seed_key_and_model(session, prices={"input": 4.0, "output": 20.0})
    capture = _install_fake_anthropic(monkeypatch)

    result = asyncio.run(estimate_meal_photo(session, image_bytes=b"fake-jpeg-bytes", media_type="image/jpeg"))

    assert result["items"][0]["name"] == "Grilled chicken breast"
    assert result["notes"] == "Estimate — sauce/oil not visible."
    assert result["cost_usd"] == pytest.approx((1200 * 4.0 + 150 * 20.0) / 1_000_000)

    # Never a forced tool_choice (newer models 400 on that) and the image is sent as base64,
    # never written anywhere.
    sent = capture[0]
    assert sent["tool_choice"] == {"type": "auto"}
    image_block = sent["messages"][0]["content"][0]
    assert image_block["type"] == "image"
    assert image_block["source"]["media_type"] == "image/jpeg"


def test_estimate_meal_photo_records_cost_against_the_shared_daily_cap(session, monkeypatch):
    from catch.coach import cost as cost_module

    _seed_key_and_model(session, prices={"input": 4.0, "output": 20.0})
    _install_fake_anthropic(monkeypatch)

    asyncio.run(estimate_meal_photo(session, image_bytes=b"x", media_type="image/jpeg"))

    assert cost_module.today_spend_usd(session) > 0


def test_estimate_meal_photo_raises_when_cap_already_reached(session, monkeypatch):
    from catch.coach import cost as cost_module

    _seed_key_and_model(session, daily_cap_usd=1.0)
    cost_module.record_usage_event(session, "nutrition_photo_estimate", {}, 1.0)
    _install_fake_anthropic(monkeypatch)

    with pytest.raises(NutritionVisionError, match="cap"):
        asyncio.run(estimate_meal_photo(session, image_bytes=b"x", media_type="image/jpeg"))


def test_estimate_meal_photo_raises_without_a_configured_key(session, monkeypatch):
    coach_settings_module.update_coach_settings(session, {"anthropic_model": "claude-opus-5-5"})
    _install_fake_anthropic(monkeypatch)

    with pytest.raises(NutritionVisionError, match="Anthropic key"):
        asyncio.run(estimate_meal_photo(session, image_bytes=b"x", media_type="image/jpeg"))


def test_estimate_meal_photo_raises_when_model_never_calls_the_tool(session, monkeypatch):
    _seed_key_and_model(session)
    _install_fake_anthropic(monkeypatch, no_tool_call=True)

    with pytest.raises(NutritionVisionError, match="structured result"):
        asyncio.run(estimate_meal_photo(session, image_bytes=b"x", media_type="image/jpeg"))


def test_estimate_meal_photo_wraps_api_errors(session, monkeypatch):
    _seed_key_and_model(session)
    _install_fake_anthropic(monkeypatch, raise_api_error=True)

    with pytest.raises(NutritionVisionError, match="rejected|unavailable|couldn.t process"):
        asyncio.run(estimate_meal_photo(session, image_bytes=b"x", media_type="image/jpeg"))
