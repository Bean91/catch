from __future__ import annotations

from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_status_requires_auth(client):
    assert client.get("/api/status").status_code == 401


def test_status_shape_with_a_fresh_db(client):
    _login(client)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    sources = {s["source"] for s in body["sources"]}
    assert sources == {"garmin", "withings", "concept2"}
    for s in body["sources"]:
        assert s["last_success_at"] is None
        assert s["consecutive_failures"] == 0
    assert body["backup"] is None  # no backup status.json in a fresh dev DB dir
    assert body["disk_free_bytes"] > 0
    assert body["db_size_bytes"] >= 0
    assert body["uptime_seconds"] >= 0


def test_status_reflects_sync_state(client, session):
    _login(client)
    from catch.sync import state

    state.record_error(session, "garmin", "boom")
    state.record_error(session, "garmin", "boom")

    body = client.get("/api/status").json()
    garmin = next(s for s in body["sources"] if s["source"] == "garmin")
    assert garmin["consecutive_failures"] == 2
    assert garmin["last_error"] == "boom"


def test_status_reads_backup_file_when_present(client, tmp_path, monkeypatch):
    _login(client)
    import json

    import catch.api.routes_status as routes_status

    backup_file = tmp_path / "status.json"
    backup_file.write_text(json.dumps({"last_backup_at": "2026-11-06T03:30:00Z", "backup_size_bytes": 12345, "remote_ok": True}))
    monkeypatch.setattr(routes_status, "_BACKUP_STATUS_FILE", backup_file)

    body = client.get("/api/status").json()
    assert body["backup"]["backup_size_bytes"] == 12345
    assert body["backup"]["remote_ok"] is True


def test_status_includes_garmin_key_expiry_from_settings(client, session):
    _login(client)
    from catch.core.settings_store import update_settings

    update_settings(session, {"garmin_key_expires_on": "2027-01-01"})

    body = client.get("/api/status").json()
    assert body["garmin_key_expires_on"] == "2027-01-01"
