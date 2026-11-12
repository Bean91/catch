from __future__ import annotations

import dataclasses

import pytest

from catch.core import secret_store
from catch.core.secret_store import SecretStoreError

KEY = "sk-ant-api03-THIS-IS-A-TEST-KEY-abcdef1234"


def test_round_trip():
    blob, key_id = secret_store.seal(KEY, owner_id="owner", provider="anthropic")
    assert KEY not in blob
    assert secret_store.open_sealed(blob, owner_id="owner", provider="anthropic") == KEY
    assert key_id == secret_store.current_key_id()


def test_each_seal_uses_a_fresh_nonce():
    a, _ = secret_store.seal(KEY, owner_id="owner", provider="anthropic")
    b, _ = secret_store.seal(KEY, owner_id="owner", provider="anthropic")
    assert a != b


def test_blob_cannot_be_opened_as_another_owner():
    blob, _ = secret_store.seal(KEY, owner_id="alice", provider="openai")
    with pytest.raises(SecretStoreError) as exc:
        secret_store.open_sealed(blob, owner_id="bob", provider="openai")
    assert KEY not in str(exc.value)


def test_blob_cannot_be_opened_as_another_provider():
    blob, _ = secret_store.seal(KEY, owner_id="alice", provider="openai")
    with pytest.raises(SecretStoreError):
        secret_store.open_sealed(blob, owner_id="alice", provider="gemini")


def test_tampered_blob_is_rejected():
    blob, _ = secret_store.seal(KEY, owner_id="owner", provider="openai")
    head, _, payload = blob.rpartition(".")
    flipped = payload[:-4] + ("AAAA" if payload[-4:] != "AAAA" else "BBBB")
    with pytest.raises(SecretStoreError):
        secret_store.open_sealed(f"{head}.{flipped}", owner_id="owner", provider="openai")


@pytest.mark.parametrize("junk", ["", "garbage", "v1.abc", "v9.abc.AAAA", "v1.abc.!!!"])
def test_malformed_blobs_raise_the_store_error(junk):
    with pytest.raises(SecretStoreError):
        secret_store.open_sealed(junk, owner_id="owner", provider="openai")


def test_missing_master_key_fails_closed(monkeypatch):
    monkeypatch.setattr(secret_store, "settings", dataclasses.replace(secret_store.settings, secrets_master_key="", fernet_key=""))
    with pytest.raises(SecretStoreError):
        secret_store.seal(KEY, owner_id="owner", provider="openai")


def test_pi_falls_back_to_the_fernet_key(monkeypatch):
    monkeypatch.setattr(secret_store, "settings", dataclasses.replace(secret_store.settings, secrets_master_key="", fernet_key="pi-fernet-key-placeholder"))
    blob, _ = secret_store.seal(KEY, owner_id="owner", provider="openai")
    assert secret_store.open_sealed(blob, owner_id="owner", provider="openai") == KEY


def test_rotation_reads_old_blobs_and_flags_them_for_reseal(monkeypatch):
    old_master = secret_store.settings.secrets_master_key
    blob, old_id = secret_store.seal(KEY, owner_id="owner", provider="openai")
    monkeypatch.setattr(
        secret_store,
        "settings",
        dataclasses.replace(secret_store.settings, secrets_master_key="a-brand-new-master-key-0123456789", secrets_master_key_previous=old_master),
    )
    assert secret_store.open_sealed(blob, owner_id="owner", provider="openai") == KEY
    assert secret_store.needs_reseal(old_id)
    new_blob, new_id = secret_store.seal(KEY, owner_id="owner", provider="openai")
    assert not secret_store.needs_reseal(new_id)
    assert secret_store.open_sealed(new_blob, owner_id="owner", provider="openai") == KEY


def test_unknown_master_after_rotation_without_previous_fails(monkeypatch):
    blob, _ = secret_store.seal(KEY, owner_id="owner", provider="openai")
    monkeypatch.setattr(secret_store, "settings", dataclasses.replace(secret_store.settings, secrets_master_key="a-brand-new-master-key-0123456789"))
    with pytest.raises(SecretStoreError):
        secret_store.open_sealed(blob, owner_id="owner", provider="openai")


def test_mask_never_echoes_short_secrets():
    assert secret_store.mask("short") == ""
    assert secret_store.mask("x" * 11) == ""
    assert secret_store.mask("sk-" + "x" * 20 + "abcd") == "abcd"
