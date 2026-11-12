"""Supabase Storage with a private bucket and per-user folders, against the real Storage API (session 24)."""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from tests.pg.conftest import API_URL, PUBLISHABLE, signup

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def call(method, path, user=None, data=None, headers=None, anon=False):
    h = {"apikey": PUBLISHABLE, **(headers or {})}
    if user is not None:
        h["authorization"] = f"Bearer {user.access_token}"
    req = urllib.request.Request(f"{API_URL}{path}", data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def upload(user, owner_folder, name="pic.png"):
    return call("POST", f"/storage/v1/object/piece-photos/{owner_folder}/{name}", user, PNG, {"content-type": "image/png"})


@pytest.fixture()
def pair(clean):
    a, b = signup("st-a"), signup("st-b")
    yield a, b
    for u in (a, b):
        call("DELETE", "/storage/v1/object/piece-photos", u, b'{"prefixes": ["%s/pic.png"]}' % u.id.encode(), {"content-type": "application/json"})


def test_a_user_can_store_and_read_in_their_own_folder_only(pair):
    a, b = pair
    assert upload(a, a.id)[0] == 200
    assert call("GET", f"/storage/v1/object/authenticated/piece-photos/{a.id}/pic.png", a)[0] == 200
    assert upload(b, a.id)[0] in (400, 401, 403), "Bob wrote into Alice's folder"
    status, _ = call("GET", f"/storage/v1/object/authenticated/piece-photos/{a.id}/pic.png", b)
    assert status in (400, 403, 404)


def test_the_bucket_is_not_publicly_readable(pair):
    a, _ = pair
    upload(a, a.id)
    status, _ = call("GET", f"/storage/v1/object/public/piece-photos/{a.id}/pic.png")
    assert status in (400, 404)
    status, _ = call("GET", f"/storage/v1/object/authenticated/piece-photos/{a.id}/pic.png")  # no token at all
    assert status in (400, 401, 403, 404)


def test_non_images_and_oversized_files_are_refused_by_storage_itself(pair):
    a, _ = pair
    status, _ = call("POST", f"/storage/v1/object/piece-photos/{a.id}/note.txt", a, b"hello", {"content-type": "text/plain"})
    assert status in (400, 415)
    status, _ = call("POST", f"/storage/v1/object/piece-photos/{a.id}/big.png", a, b"0" * (5 * 1024 * 1024 + 1), {"content-type": "image/png"})
    assert status in (400, 413)


def test_signed_urls_work_without_a_session_and_only_for_the_owners_objects(pair):
    a, b = pair
    upload(a, a.id)
    status, body = call("POST", f"/storage/v1/object/sign/piece-photos/{a.id}/pic.png", a, b'{"expiresIn": 60}', {"content-type": "application/json"})
    assert status == 200
    import json

    url = json.loads(body)["signedURL"]
    status, got = call("GET", f"/storage/v1{url}" if url.startswith("/") else url)
    assert status == 200 and got == PNG  # short-lived link, no token needed
    status, _ = call("POST", f"/storage/v1/object/sign/piece-photos/{a.id}/pic.png", b, b'{"expiresIn": 60}', {"content-type": "application/json"})
    assert status in (400, 403, 404), "Bob obtained a signed URL for Alice's photo"
