from __future__ import annotations

import asyncio
import sys
import types

import pytest

from catch.coach import settings as coach_settings_module
from catch.coach.piece_vision import PieceVisionError, estimate_piece_photo

# The task's own worked example (session 17 Part B.3), reused as the vision fixture too.
_TASK_2K_SPLITS = [
    {"distance_m": 500, "time": "1:36.8", "rate": 32, "watts": None, "hr": None},
    {"distance_m": 1000, "time": "1:38.9", "rate": 30, "watts": None, "hr": None},
    {"distance_m": 1500, "time": "1:39.0", "rate": 31, "watts": None, "hr": None},
    {"distance_m": 2000, "time": "1:37.7", "rate": 32, "watts": None, "hr": None},
]


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
                        name="record_piece_reading",
                        input=tool_input
                        or {
                            "total_time": "6:32.4",
                            "total_distance_m": 2000,
                            "avg_split": "1:38.1",
                            "avg_rate": 31,
                            "avg_watts": None,
                            "drag_factor": 120,
                            "splits": _TASK_2K_SPLITS,
                            "notes": "",
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


def test_estimate_piece_photo_parses_time_strings_server_side(session, monkeypatch):
    _seed_key_and_model(session, prices={"input": 4.0, "output": 20.0})
    capture = _install_fake_anthropic(monkeypatch)

    result = asyncio.run(estimate_piece_photo(session, image_bytes=b"fake-jpeg-bytes", media_type="image/jpeg"))

    assert result["duration_s"] == pytest.approx(392.4)
    assert result["distance_m"] == 2000
    assert result["drag_factor"] == 120
    assert [s["split_s"] for s in result["splits"]] == pytest.approx([96.8, 98.9, 99.0, 97.7])
    assert result["cost_usd"] == pytest.approx((1200 * 4.0 + 150 * 20.0) / 1_000_000)
    assert result["validation"]["ok"]

    sent = capture[0]
    assert sent["tool_choice"] == {"type": "auto"}
    image_block = sent["messages"][0]["content"][0]
    assert image_block["type"] == "image"
    assert image_block["source"]["media_type"] == "image/jpeg"


def test_estimate_piece_photo_cumulates_a_per_split_distance_column(session, monkeypatch):
    """A screen that shows each split's own 500m distance repeated (500, 500, 500, 500)
    rather than cumulative (500, 1000, 1500, 2000) — the raw column is still correct, just a
    different real PM5 display mode than the task's own example assumed."""
    _seed_key_and_model(session)
    repeated = {
        "total_time": "6:32.4",
        "total_distance_m": 2000,
        "avg_split": None,
        "avg_rate": None,
        "avg_watts": None,
        "drag_factor": None,
        "splits": [{**s, "distance_m": 500} for s in _TASK_2K_SPLITS],
        "notes": "",
    }
    _install_fake_anthropic(monkeypatch, tool_input=repeated)

    result = asyncio.run(estimate_piece_photo(session, image_bytes=b"x", media_type="image/jpeg"))
    assert [s["distance_m"] for s in result["splits"]] == [500.0, 1000.0, 1500.0, 2000.0]
    assert result["validation"]["ok"]


def test_estimate_piece_photo_differences_a_cumulative_time_column(session, monkeypatch):
    """A screen showing cumulative elapsed time per split (1:36.8, 3:15.7, 5:14.7, 6:32.4)
    instead of each split's own duration — recognized because it's increasing and its last
    value matches the piece's own total."""
    _seed_key_and_model(session)
    cumulative = {
        "total_time": "6:32.4",
        "total_distance_m": 2000,
        "avg_split": None,
        "avg_rate": None,
        "avg_watts": None,
        "drag_factor": None,
        "splits": [
            {"distance_m": 500, "time": "1:36.8", "rate": 32, "watts": None, "hr": None},
            {"distance_m": 1000, "time": "3:15.7", "rate": 30, "watts": None, "hr": None},
            {"distance_m": 1500, "time": "4:54.7", "rate": 31, "watts": None, "hr": None},
            {"distance_m": 2000, "time": "6:32.4", "rate": 32, "watts": None, "hr": None},
        ],
        "notes": "",
    }
    _install_fake_anthropic(monkeypatch, tool_input=cumulative)

    result = asyncio.run(estimate_piece_photo(session, image_bytes=b"x", media_type="image/jpeg"))
    assert [s["split_s"] for s in result["splits"]] == pytest.approx([96.8, 98.9, 99.0, 97.7])
    assert result["validation"]["ok"]


def test_estimate_piece_photo_flags_issues_in_the_validation_field(session, monkeypatch):
    _seed_key_and_model(session)
    bad = {
        "total_time": "6:32.4",
        "total_distance_m": 2000,
        "avg_split": None,
        "avg_rate": None,
        "avg_watts": None,
        "drag_factor": None,
        "splits": [{**s, "rate": 95} for s in _TASK_2K_SPLITS],
        "notes": "",
    }
    _install_fake_anthropic(monkeypatch, tool_input=bad)

    result = asyncio.run(estimate_piece_photo(session, image_bytes=b"x", media_type="image/jpeg"))
    assert not result["validation"]["ok"]
    assert any(i["field"] == "rate" for i in result["validation"]["issues"])


def test_estimate_piece_photo_flags_an_unparseable_time_instead_of_guessing(session, monkeypatch):
    _seed_key_and_model(session)
    bad = {
        "total_time": "garbled",
        "total_distance_m": 2000,
        "avg_split": None,
        "avg_rate": None,
        "avg_watts": None,
        "drag_factor": None,
        "splits": [],
        "notes": "",
    }
    _install_fake_anthropic(monkeypatch, tool_input=bad)

    result = asyncio.run(estimate_piece_photo(session, image_bytes=b"x", media_type="image/jpeg"))
    assert result["duration_s"] is None
    assert "total time" in result["notes"]


def test_estimate_piece_photo_records_cost_against_the_shared_daily_cap(session, monkeypatch):
    from catch.coach import cost as cost_module

    _seed_key_and_model(session, prices={"input": 4.0, "output": 20.0})
    _install_fake_anthropic(monkeypatch)

    asyncio.run(estimate_piece_photo(session, image_bytes=b"x", media_type="image/jpeg"))

    assert cost_module.today_spend_usd(session) > 0


def test_estimate_piece_photo_raises_when_cap_already_reached(session, monkeypatch):
    from catch.coach import cost as cost_module

    _seed_key_and_model(session, daily_cap_usd=1.0)
    cost_module.record_usage_event(session, "piece_photo_estimate", {}, 1.0)
    _install_fake_anthropic(monkeypatch)

    with pytest.raises(PieceVisionError, match="cap"):
        asyncio.run(estimate_piece_photo(session, image_bytes=b"x", media_type="image/jpeg"))


def test_estimate_piece_photo_raises_without_a_configured_key(session, monkeypatch):
    coach_settings_module.update_coach_settings(session, {"anthropic_model": "claude-opus-5-5"})
    _install_fake_anthropic(monkeypatch)

    with pytest.raises(PieceVisionError, match="Anthropic key"):
        asyncio.run(estimate_piece_photo(session, image_bytes=b"x", media_type="image/jpeg"))


def test_estimate_piece_photo_raises_when_model_never_calls_the_tool(session, monkeypatch):
    _seed_key_and_model(session)
    _install_fake_anthropic(monkeypatch, no_tool_call=True)

    with pytest.raises(PieceVisionError, match="structured result"):
        asyncio.run(estimate_piece_photo(session, image_bytes=b"x", media_type="image/jpeg"))


def test_estimate_piece_photo_wraps_api_errors(session, monkeypatch):
    _seed_key_and_model(session)
    _install_fake_anthropic(monkeypatch, raise_api_error=True)

    with pytest.raises(PieceVisionError, match="rejected|unavailable|couldn.t process"):
        asyncio.run(estimate_piece_photo(session, image_bytes=b"x", media_type="image/jpeg"))
