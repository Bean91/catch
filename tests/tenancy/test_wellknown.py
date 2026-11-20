"""Session 30: association files for universal/app links."""

from __future__ import annotations

from catch.api import routes_wellknown
from catch.core import config


def _set(**kw):
    prev = {k: getattr(config.settings, k) for k in kw}
    for k, v in kw.items():
        object.__setattr__(config.settings, k, v)
    return prev


def test_aasa_names_the_app_and_only_the_paths_it_handles(pub_client):
    prev = _set(apple_team_id="ABCDE12345", apple_bundle_id="com.openoted.catch")
    try:
        r = pub_client.get("/.well-known/apple-app-site-association")
    finally:
        _set(**prev)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    d = r.json()["applinks"]["details"][0]
    assert d["appIDs"] == ["ABCDE12345.com.openoted.catch"]
    paths = [c["/"] for c in d["components"]]
    assert "/workouts/*" in paths and "/checkin" in paths and "/clubs/join" in paths
    assert not any(p.startswith(("/api", "/internal", "/settings/moderation", "/oauth")) for p in paths)  # nothing sensitive is claimed


def test_aasa_is_a_404_until_the_operator_sets_the_team_id(pub_client):
    prev = _set(apple_team_id="")
    try:
        assert pub_client.get("/.well-known/apple-app-site-association").status_code == 404
    finally:
        _set(**prev)


def test_assetlinks_lists_the_signing_fingerprints(pub_client):
    prev = _set(android_cert_sha256="aa:bb:cc, DD:EE:FF", android_package="com.openoted.catch")
    try:
        r = pub_client.get("/.well-known/assetlinks.json")
    finally:
        _set(**prev)
    t = r.json()[0]["target"]
    assert r.status_code == 200 and t["package_name"] == "com.openoted.catch" and t["sha256_cert_fingerprints"] == ["AA:BB:CC", "DD:EE:FF"]
    assert r.json()[0]["relation"] == ["delegate_permission/common.handle_all_urls"]


def test_assetlinks_404_when_unset(pub_client):
    prev = _set(android_cert_sha256="")
    try:
        assert pub_client.get("/.well-known/assetlinks.json").status_code == 404
    finally:
        _set(**prev)


def test_neither_file_exists_on_a_personal_deployment(client):
    assert client.get("/.well-known/apple-app-site-association").status_code == 404
    assert client.get("/.well-known/assetlinks.json").status_code == 404
    assert routes_wellknown.router is not None
