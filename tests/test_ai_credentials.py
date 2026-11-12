from __future__ import annotations

from catch.core import tenant
import json
import logging

import pytest
from sqlmodel import select

from catch.coach import settings as cs
from catch.coach.providers import registry
from catch.core import security
from catch.core.models import AiCredential, CoachCredential
from catch.core.owner import current_owner_id
from catch.core.tenant import set_owner, use_owner
from tests.conftest import TEST_PASSWORD

KEY_A = "sk-proj-ALICE-secret-key-aaaaaaaaaaaaaaaa1111"
KEY_B = "sk-proj-BOB-secret-key-bbbbbbbbbbbbbbbbbbb2222"


def _login(client):
    assert client.post("/api/login", json={"password": TEST_PASSWORD}).status_code == 200


def test_stored_blob_is_not_plaintext_and_is_per_owner_and_provider(session):
    with use_owner("alice"):
        cs.set_credential(session, "openai", KEY_A, owner_id="alice")
        row = session.get(AiCredential, ("alice", "openai"))
        assert KEY_A not in row.key_enc and row.last4 == "1111"
        assert cs.get_decrypted_credential(session, "openai", owner_id="alice") == KEY_A


def test_one_owner_cannot_read_replace_or_delete_anothers_key(session):
    with use_owner("alice"):
        cs.set_credential(session, "openai", KEY_A, owner_id="alice")
    with use_owner("bob"):
        assert cs.get_decrypted_credential(session, "openai", owner_id="bob") is None
        assert cs.masked_credential_info(session, "openai", owner_id="bob")["configured"] is False
        assert cs.delete_credential(session, "openai", owner_id="bob") is False
        cs.set_credential(session, "openai", KEY_B, owner_id="bob")
        assert cs.get_decrypted_credential(session, "openai", owner_id="bob") == KEY_B
    with use_owner("alice"):
        assert cs.get_decrypted_credential(session, "openai", owner_id="alice") == KEY_A


def test_a_row_copied_between_owners_cannot_be_decrypted(session):
    with use_owner("alice"):
        cs.set_credential(session, "openai", KEY_A, owner_id="alice")
        stolen = session.get(AiCredential, ("alice", "openai"))
        blob, key_id = stolen.key_enc, stolen.key_id
    with use_owner("mallory"):
        session.add(AiCredential(owner_id="mallory", provider="openai", key_enc=blob, key_id=key_id))
        session.commit()
        from catch.core.secret_store import SecretStoreError

        with pytest.raises(SecretStoreError):
            cs.get_decrypted_credential(session, "openai", owner_id="mallory")


def test_replace_overwrites_and_resets_status(session):
    cs.set_credential(session, "gemini", KEY_A)
    cs.set_status(session, "gemini", "invalid", "rejected_by_provider")
    info = cs.set_credential(session, "gemini", KEY_B)
    assert info["status"] == "configured" and info["last4"] == "2222"
    assert cs.get_decrypted_credential(session, "gemini") == KEY_B


def test_delete_then_registry_says_not_configured(session):
    cs.set_credential(session, "openai", KEY_A)
    assert registry.build_provider(session, "owner", "openai").name == "openai"
    assert cs.delete_credential(session, "openai") is True
    with pytest.raises(registry.NotConfigured) as exc:
        registry.build_provider(session, "owner", "openai")
    assert "Settings → AI Providers" in str(exc.value)


def test_no_environment_fallback_key(session, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-should-never-be-used-00000000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-should-never-be-used-0000")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaEnvShouldNeverBeUsed000000000000")
    for provider in ("openai", "anthropic", "gemini"):
        with pytest.raises(registry.NotConfigured):
            registry.build_provider(session, "owner", provider)


def test_short_keys_are_never_echoed(session):
    info = cs.set_credential(session, "openai", "short-key")
    assert info["last4"] is None


def test_ollama_and_unknown_providers_take_no_key(session):
    with pytest.raises(ValueError):
        cs.set_credential(session, "ollama", KEY_A)
    with pytest.raises(ValueError):
        cs.set_credential(session, "nope", KEY_A)


# --- the Pi's legacy table ------------------------------------------------------------------


def test_legacy_key_is_adopted_without_destroying_the_old_row(session):
    session.add(CoachCredential(provider="anthropic", api_key_enc=security.encrypt(KEY_A), last4="1111"))
    session.commit()
    assert cs.get_decrypted_credential(session, "anthropic") == KEY_A
    assert session.get(AiCredential, ("owner", "anthropic")) is not None
    assert session.get(CoachCredential, tenant.pk("anthropic")) is not None  # rollback-safe


def test_replace_and_remove_also_remove_the_legacy_row(session):
    session.add(CoachCredential(provider="anthropic", api_key_enc=security.encrypt(KEY_A), last4="1111"))
    session.commit()
    cs.get_decrypted_credential(session, "anthropic")
    cs.set_credential(session, "anthropic", KEY_B)
    assert session.get(CoachCredential, tenant.pk("anthropic")) is None

    session.add(CoachCredential(provider="openai", api_key_enc=security.encrypt(KEY_A), last4="1111"))
    session.commit()
    assert cs.delete_credential(session, "openai") is True
    assert session.exec(select(CoachCredential).where(CoachCredential.provider == "openai")).first() is None
    assert cs.get_decrypted_credential(session, "openai") is None


def test_legacy_rows_are_not_handed_to_other_owners(session):
    session.add(CoachCredential(provider="anthropic", api_key_enc=security.encrypt(KEY_A), last4="1111"))
    session.commit()
    assert cs.get_decrypted_credential(session, "anthropic", owner_id="bob") is None


# --- settings are per owner too --------------------------------------------------------------


def test_coach_settings_are_per_owner(session):
    with use_owner("alice"):
        cs.update_coach_settings(session, {"provider": "openai", "models": {"openai": "gpt-x"}, "daily_cap_usd": 3.0}, owner_id="alice")
        alice = cs.get_coach_settings(session, "alice")
    with use_owner("bob"):
        cs.update_coach_settings(session, {"provider": "gemini"}, owner_id="bob")
        bob = cs.get_coach_settings(session, "bob")
    assert (alice["provider"], alice["models"], alice["daily_cap_usd"]) == ("openai", {"openai": "gpt-x"}, 3.0)
    assert (bob["provider"], bob["models"], bob["daily_cap_usd"]) == ("gemini", {}, None)
    assert cs.get_coach_settings(session)["provider"] == "anthropic"  # the Pi's own owner is untouched


def test_models_roundtrip_with_legacy_columns(session):
    cs.update_coach_settings(session, {"anthropic_model": "claude-x", "ollama_model": "llama"})
    prefs = cs.get_coach_settings(session)
    assert prefs["models"] == {"anthropic": "claude-x", "ollama": "llama"} and prefs["anthropic_model"] == "claude-x"


# --- API ------------------------------------------------------------------------------------


def _as(client, owner):
    async def _owner():
        set_owner(owner)  # an async dependency runs in the request's own task, so the context reaches the endpoint
        return owner

    client.app.dependency_overrides[current_owner_id] = _owner


@pytest.fixture(autouse=True)
def _clear_overrides(client):
    yield
    client.app.dependency_overrides.pop(current_owner_id, None)


def _stub_validate(monkeypatch, ok=True, kind=None):
    from catch.coach.providers import anthropic_provider, gemini_provider, openai_provider

    async def fake(self):
        return {"ok": ok, "kind": kind, "message": "Connected" if ok else "The provider rejected this API key.", "model_count": 3 if ok else None}

    for cls in (openai_provider.OpenAIProvider, gemini_provider.GeminiProvider, anthropic_provider.AnthropicProvider):
        monkeypatch.setattr(cls, "validate", fake)


def test_api_put_key_validates_then_stores_and_never_echoes(client, monkeypatch):
    _login(client)
    _stub_validate(monkeypatch)
    resp = client.put("/api/ai/providers/openai/key", json={"api_key": KEY_A})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] and body["last4"] == "1111" and body["status"] == "valid" and body["validated"]
    assert KEY_A not in resp.text

    listing = client.get("/api/ai/providers")
    assert KEY_A not in listing.text and "sk-proj-ALICE" not in listing.text
    openai = next(p for p in listing.json()["providers"] if p["id"] == "openai")
    assert openai["configured"] and openai["last4"] == "1111"


def test_api_rejected_key_is_not_saved_and_does_not_replace_a_working_one(client, session, monkeypatch):
    _login(client)
    _stub_validate(monkeypatch)
    client.put("/api/ai/providers/gemini/key", json={"api_key": KEY_A})
    _stub_validate(monkeypatch, ok=False, kind="invalid_key")
    resp = client.put("/api/ai/providers/gemini/key", json={"api_key": KEY_B})
    assert resp.status_code == 422 and KEY_B not in resp.text
    assert cs.get_decrypted_credential(session, "gemini") == KEY_A


def test_api_provider_unreachable_still_saves_with_unavailable_status(client, monkeypatch):
    _login(client)
    _stub_validate(monkeypatch, ok=False, kind="unavailable")
    body = client.put("/api/ai/providers/openai/key", json={"api_key": KEY_A}).json()
    assert body["configured"] and body["status"] == "unavailable" and body["validated"] is False


def test_api_validation_errors_do_not_echo_the_submitted_value(client):
    _login(client)
    resp = client.put("/api/ai/providers/openai/key", json={"api_key": {"oops": KEY_A}})
    assert resp.status_code == 422
    assert KEY_A not in resp.text and "input" not in resp.text
    resp = client.post("/api/coach/key", json={"api_key": [KEY_A]})
    assert resp.status_code == 422 and KEY_A not in resp.text


def test_api_delete_removes_key_and_deactivates_but_keeps_history(client, session, monkeypatch):
    from catch.core.models import CoachConversation, CoachMessage

    _login(client)
    _stub_validate(monkeypatch)
    client.put("/api/ai/providers/openai/key", json={"api_key": KEY_A})
    assert client.put("/api/ai/active", json={"provider": "openai", "model": "gpt-x"}).json()["active"] == "openai"
    conv = client.post("/api/coach/conversations").json()
    session.add(CoachMessage(conversation_id=conv["id"], role="user", blocks_json=json.dumps([{"type": "text", "text": "keep me"}])))
    session.commit()

    resp = client.delete("/api/ai/providers/openai/key")
    assert resp.status_code == 200 and resp.json()["active"] is None
    assert session.get(CoachConversation, conv["id"]) is not None
    assert client.get(f"/api/coach/conversations/{conv['id']}").json()["messages"][0]["blocks"][0]["text"] == "keep me"


def test_api_cannot_activate_an_unconfigured_provider(client):
    _login(client)
    resp = client.put("/api/ai/active", json={"provider": "gemini"})
    assert resp.status_code == 409 and "Gemini" in resp.json()["detail"]
    assert client.put("/api/ai/active", json={"provider": "bogus"}).status_code == 404


def test_api_two_owners_are_isolated_end_to_end(client, monkeypatch):
    _login(client)
    _stub_validate(monkeypatch)
    _as(client, "alice")
    client.put("/api/ai/providers/openai/key", json={"api_key": KEY_A})
    client.put("/api/ai/active", json={"provider": "openai", "model": "gpt-alice"})
    conv = client.post("/api/coach/conversations").json()

    _as(client, "bob")
    bob_view = client.get("/api/ai/providers").json()
    assert bob_view["active"] is None
    assert not any(p["configured"] for p in bob_view["providers"] if p["id"] == "openai")
    assert client.get(f"/api/coach/conversations/{conv['id']}").status_code == 404
    assert client.delete(f"/api/coach/conversations/{conv['id']}").status_code == 404
    assert client.get("/api/coach/conversations").json() == []
    assert client.post("/api/ai/providers/openai/test").json()["ok"] is False
    client.delete("/api/ai/providers/openai/key")  # a no-op for Bob

    _as(client, "alice")
    assert client.get("/api/ai/providers").json()["active"] == "openai"
    assert client.get(f"/api/coach/conversations/{conv['id']}").status_code == 200


def test_api_test_marks_status_and_never_leaks(client, session, monkeypatch):
    _login(client)
    _stub_validate(monkeypatch)
    client.put("/api/ai/providers/anthropic/key", json={"api_key": KEY_A})
    _stub_validate(monkeypatch, ok=False, kind="invalid_key")
    resp = client.post("/api/ai/providers/anthropic/test")
    assert resp.json()["ok"] is False and resp.json()["kind"] == "invalid_key" and KEY_A not in resp.text
    card = next(p for p in client.get("/api/ai/providers").json()["providers"] if p["id"] == "anthropic")
    assert card["status"] == "invalid" and card["status_detail"] == "rejected_by_provider"


def test_api_usage_reports_recorded_usage_and_no_fake_balance(client):
    _login(client)
    body = client.get("/api/ai/usage").json()
    assert body["provider_balance"] is None and body["source"] == "recorded_by_catch"


def test_api_ai_routes_are_cookie_only(client, session):
    from catch.api.deps import hash_token
    from catch.core.models import ApiToken

    session.add(ApiToken(name="d", token_hash=hash_token("tok-123")))
    session.commit()
    headers = {"Authorization": "Bearer tok-123"}
    assert client.get("/api/ai/providers", headers=headers).status_code == 401
    assert client.put("/api/ai/providers/openai/key", json={"api_key": KEY_A}, headers=headers).status_code == 401


def test_api_rate_limits_key_validation(client, monkeypatch):
    _login(client)
    _stub_validate(monkeypatch)
    codes = [client.post("/api/ai/providers/openai/test").status_code for _ in range(35)]
    assert 429 in codes


def test_logs_never_contain_a_stored_key_even_when_code_logs_it_by_mistake(client, session, caplog):
    from catch.core.redact import redact

    cs.set_credential(session, "openai", KEY_A)
    cs.get_decrypted_credential(session, "openai")
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("catch.somewhere").warning("provider call failed: %s", KEY_A)
        try:
            raise RuntimeError(f"upstream echoed {KEY_A}")
        except RuntimeError:
            logging.getLogger("catch.somewhere").exception("boom")
    assert KEY_A not in caplog.text and KEY_A not in "".join(r.exc_text or "" for r in caplog.records)
    assert KEY_A not in redact(f"x {KEY_A} y")
