import dataclasses

import pytest
from sqlmodel import Session

from catch.core import secret_store, tenant
from catch.core.models import AiCredential, ProviderConnection
from catch.sync import connections, secret_rotation

OLD = "old-master-key-0123456789-abcdefghijklmnop"
NEW = "new-master-key-9876543210-zyxwvutsrqponmlk"


@pytest.fixture()
def masters(monkeypatch):
    def use(current, previous=""):
        monkeypatch.setattr(secret_store, "settings", dataclasses.replace(secret_store.settings, secrets_master_key=current, secrets_master_key_previous=previous))

    return use


def _seed(session, masters):
    masters(OLD)
    blob, kid = secret_store.seal("sk-ant-REAL-KEY-aaaaaaaaaaaa", owner_id="owner", provider="anthropic")
    session.add(AiCredential(owner_id="owner", provider="anthropic", key_enc=blob, key_id=kid))
    a, kid2 = connections._seal("whoop", "access", "ACCESS-TOKEN-bbbbbbbbbbbb")
    r, _ = connections._seal("whoop", "refresh", "REFRESH-TOKEN-cccccccccccc")
    session.add(ProviderConnection(owner_id="owner", provider="whoop", auth_method="oauth", status="connected", access_enc=a, refresh_enc=r, key_id=kid2))
    session.commit()
    return kid


def test_rotation_reseals_everything_and_the_old_key_can_then_be_dropped(session, masters):
    old_id = _seed(session, masters)
    masters(NEW, OLD)
    assert dict(secret_rotation.status(session)) == {old_id: 2}
    dry = secret_rotation.rotate_owner(session, dry_run=True)
    assert dry == {"resealed": 2, "already_current": 0, "failed": []}
    assert dict(secret_rotation.status(session)) == {old_id: 2}  # a dry run changes nothing
    assert secret_rotation.rotate_owner(session) == {"resealed": 2, "already_current": 0, "failed": []}
    assert set(secret_rotation.status(session)) == {secret_store.current_key_id()}
    masters(NEW, "")  # the old master is gone
    assert secret_store.open_sealed(session.get(AiCredential, ("owner", "anthropic")).key_enc, owner_id="owner", provider="anthropic") == "sk-ant-REAL-KEY-aaaaaaaaaaaa"
    conn = session.exec(__import__("sqlmodel").select(ProviderConnection)).first()
    assert connections._open(conn, "access") == "ACCESS-TOKEN-bbbbbbbbbbbb" and connections._open(conn, "refresh") == "REFRESH-TOKEN-cccccccccccc"
    assert secret_rotation.rotate_owner(session) == {"resealed": 0, "already_current": 2, "failed": []}  # idempotent


def test_a_blob_whose_master_is_missing_is_reported_and_left_untouched(session, masters):
    _seed(session, masters)
    before = session.get(AiCredential, ("owner", "anthropic")).key_enc
    masters(NEW, "")  # the old master was dropped too early
    report = secret_rotation.rotate_owner(session)
    assert report["resealed"] == 0 and sorted(report["failed"]) == ["ai:anthropic", "connection:whoop"]
    session.expire_all()
    assert session.get(AiCredential, ("owner", "anthropic")).key_enc == before
    assert "sk-ant" not in str(report)
