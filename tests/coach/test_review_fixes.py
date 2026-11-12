"""Regression tests for problems found in the end-of-session advisor review."""

from __future__ import annotations

from catch.core import tenant
import asyncio
import dataclasses
import json
from datetime import date

import pytest

from catch.api.sse import stream_until_disconnected
from catch.coach import chat, limits
from catch.coach import settings as cs
from catch.coach.providers import registry
from catch.coach.providers.anthropic_provider import _to_anthropic_messages
from catch.coach.providers.base import ProviderError, normalize_tool_ids
from catch.coach.providers.gemini_provider import to_gemini_contents
from catch.coach.providers.openai_provider import to_responses_input
from catch.core import redact, secret_store
from catch.core.models import CoachConversation, DailyWellness, WellnessReading
from catch.sync import wellness_readings
from tests.coach.provider_testkit import collect

# A stored Ollama conversation: every turn's synthetic id restarted at 1, so two *different* calls
# share one id. This is what real histories already on the Pi look like.
TWO_TURNS = [
    {"role": "user", "blocks": [{"type": "text", "text": "recovery?"}]},
    {"role": "assistant", "blocks": [{"type": "tool_call", "id": "ollama_call_1", "name": "get_today", "input": {}}]},
    {"role": "user", "blocks": [{"type": "tool_result", "id": "ollama_call_1", "output": {"recovery": 71}, "is_error": False}]},
    {"role": "assistant", "blocks": [{"type": "text", "text": "71."}]},
    {"role": "user", "blocks": [{"type": "text", "text": "and the load?"}]},
    {"role": "assistant", "blocks": [{"type": "tool_call", "id": "ollama_call_1", "name": "get_load", "input": {}}]},
    {"role": "user", "blocks": [{"type": "tool_result", "id": "ollama_call_1", "output": {"acr": 1.1}, "is_error": False}]},
]


def test_normalize_gives_unique_ids_and_pairs_each_result_with_its_own_call():
    out = normalize_tool_ids(TWO_TURNS)
    calls = [b for m in out for b in m["blocks"] if b["type"] == "tool_call"]
    results = [b for m in out for b in m["blocks"] if b["type"] == "tool_result"]
    assert len({c["id"] for c in calls}) == 2
    assert [r["id"] for r in results] == [c["id"] for c in calls]
    assert TWO_TURNS[1]["blocks"][0]["id"] == "ollama_call_1"  # the stored history isn't mutated


def test_gemini_function_response_names_are_not_cross_wired():
    contents = to_gemini_contents(TWO_TURNS)
    names = [p["functionResponse"]["name"] for c in contents for p in c["parts"] if "functionResponse" in p]
    assert names == ["get_today", "get_load"]


def test_anthropic_replay_has_unique_tool_use_ids_matching_their_results():
    msgs = _to_anthropic_messages(TWO_TURNS)
    uses = [b["id"] for m in msgs for b in m["content"] if b["type"] == "tool_use"]
    results = [b["tool_use_id"] for m in msgs for b in m["content"] if b["type"] == "tool_result"]
    assert len(set(uses)) == 2 and results == uses


def test_openai_replay_has_unique_call_ids_and_each_output_follows_its_call():
    items = to_responses_input(TWO_TURNS)
    call_ids = [i["call_id"] for i in items if i.get("type") == "function_call"]
    out_ids = [i["call_id"] for i in items if i.get("type") == "function_call_output"]
    assert len(set(call_ids)) == 2 and out_ids == call_ids


def test_new_synthetic_ids_are_unique_across_provider_instances():
    from catch.coach.providers.gemini_provider import GeminiProvider
    from catch.coach.providers.ollama_provider import OllamaProvider

    ids = {OllamaProvider("http://x")._synthetic_id() for _ in range(5)} | {GeminiProvider("k")._synthetic_id() for _ in range(5)}
    assert len(ids) == 10


# -- the startup seed ------------------------------------------------------------------------


def test_seed_never_relabels_another_providers_winning_values_as_garmin(session):
    day = date(2026, 11, 10)
    session.add(DailyWellness(date=day, source="garmin", steps=9000))  # Garmin's usersummary made the row; the watch was off overnight
    session.commit()
    wellness_readings.record_reading(session, day, "whoop", "hrv_rmssd", 70.0)
    wellness_readings.record_reading(session, day, "whoop", "sleep_seconds", 27000)
    wellness_readings.resolve_days(session, [day])
    assert session.get(DailyWellness, tenant.pk(day)).hrv_rmssd == 70.0
    for _ in range(2):
        assert wellness_readings.seed_from_daily_wellness(session) == 0
    assert session.exec(__import__("sqlmodel").select(WellnessReading).where(WellnessReading.source == "garmin")).all() == []
    assert json.loads(session.get(DailyWellness, tenant.pk(day)).field_sources_json)["hrv_rmssd"] == "whoop"


def test_seed_still_covers_genuinely_legacy_rows(session):
    session.add(DailyWellness(date=date(2026, 11, 1), source="garmin", hrv_rmssd=60.0, resting_hr=50))
    session.commit()
    assert wellness_readings.seed_from_daily_wellness(session) == 1
    assert wellness_readings.seed_from_daily_wellness(session) == 0


# -- stream slots ----------------------------------------------------------------------------


def test_disconnect_mid_stream_releases_the_slot(session, monkeypatch):
    cs.set_credential(session, "openai", "sk-proj-openai-key-0000000000000001")
    cs.update_coach_settings(session, {"provider": "openai", "models": {"openai": "gpt-x"}})

    class Slow:
        name = "openai"

        async def stream_turn(self, *, system_blocks, messages, model):
            yield {"type": "text_delta", "text": "first"}
            await asyncio.sleep(30)  # the provider "thinking"
            yield {"type": "stop", "stop_reason": "end_turn"}

    async def fake_resolve(s, o="owner"):
        return Slow(), "gpt-x", None, "openai"

    monkeypatch.setattr(chat, "_resolve_provider", fake_resolve)
    conv = CoachConversation()
    session.add(conv)
    session.commit()

    async def go():
        seen = 0

        async def disconnected():
            return seen >= 1

        turn = chat.run_turn(session, conv.id, "hi")
        async for _ in stream_until_disconnected(turn, disconnected, poll_interval=0.05):
            seen += 1
        return seen

    assert asyncio.run(go()) == 1
    assert limits.active_streams("owner") == 0


def test_an_abandoned_slot_expires_instead_of_locking_the_owner_out(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(limits, "_now", lambda: clock["t"])
    holders = [limits.stream_slot("o"), limits.stream_slot("o")]
    for h in holders:
        h.__enter__()  # never exited: simulates generators that were never closed
    with pytest.raises(limits.LimitExceeded):
        limits.stream_slot("o").__enter__()
    clock["t"] += limits.TURN_WALL_CLOCK_S + 31
    with limits.stream_slot("o"):
        assert limits.active_streams("o") == 1


# -- master key changes ----------------------------------------------------------------------


def test_a_changed_master_key_gives_a_clear_reenter_message_not_a_crash(session, monkeypatch):
    cs.set_credential(session, "openai", "sk-proj-openai-key-0000000000000001")
    cs.update_coach_settings(session, {"provider": "openai", "models": {"openai": "gpt-x"}})
    monkeypatch.setattr(secret_store, "settings", dataclasses.replace(secret_store.settings, secrets_master_key="a-totally-different-master-key-0123456789"))
    conv = CoachConversation()
    session.add(conv)
    session.commit()
    events = asyncio.run(collect(chat.run_turn(session, conv.id, "hi")))
    assert events[0]["type"] == "error" and events[0]["kind"] == "invalid_key"
    assert "Re-enter it" in events[0]["message"]
    with pytest.raises(ProviderError):
        registry.build_provider(session, "owner", "openai")


# -- Ollama on a public deployment -----------------------------------------------------------


def test_ollama_can_be_switched_off_for_a_public_deployment(client, monkeypatch):
    from catch.coach import settings as settings_module
    from tests.conftest import TEST_PASSWORD

    client.post("/api/login", json={"password": TEST_PASSWORD})
    monkeypatch.setattr(registry, "settings", dataclasses.replace(registry.settings, ollama_enabled=False))
    monkeypatch.setattr(settings_module, "app_config", dataclasses.replace(settings_module.app_config, ollama_enabled=False))
    assert "ollama" not in [p["id"] for p in client.get("/api/ai/providers").json()["providers"]]
    assert client.post("/api/ai/providers/ollama/test").status_code == 404
    assert client.put("/api/coach/settings", json={"ollama_base_url": "http://169.254.169.254/"}).status_code == 422
    assert client.put("/api/coach/settings", json={"provider": "ollama"}).status_code == 422
    with pytest.raises(ProviderError):
        registry.build_provider(None, "owner", "ollama")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x", "http://user:pw@host:11434", "javascript:alert(1)", "http://"])
def test_ollama_urls_must_be_plain_http_without_credentials(session, url):
    with pytest.raises(ValueError):
        cs.update_coach_settings(session, {"ollama_base_url": url})


def test_a_normal_ollama_url_is_accepted(session):
    assert cs.update_coach_settings(session, {"ollama_base_url": "http://laptop.tailnet:11434"})["ollama_base_url"] == "http://laptop.tailnet:11434"


# -- redaction registry ----------------------------------------------------------------------


def test_the_redaction_registry_is_bounded_and_keeps_the_newest():
    for i in range(200):
        redact.register_secret(f"rotating-token-{i:04d}-xxxxxxxx")
    assert len(redact._registered) <= redact._MAX_REGISTERED
    assert redact.redact("leak rotating-token-0199-xxxxxxxx") == "leak [redacted]"
