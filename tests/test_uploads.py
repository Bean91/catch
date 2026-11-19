import pytest
from conftest import TEST_PASSWORD

from catch.core import uploads

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"x" * 64


def test_sniffing_goes_by_the_bytes_not_the_claimed_type():
    assert uploads.sniff_image(JPEG) == "image/jpeg"
    assert uploads.sniff_image(PNG) == "image/png"
    assert uploads.sniff_image(WEBP) == "image/webp"
    assert uploads.sniff_image(b"RIFF\x00\x00\x00\x00WAVEfmt ") is None  # RIFF but not WebP
    assert uploads.sniff_image(b"GIF89a") is None
    assert uploads.sniff_image(b"<html><script>alert(1)</script>") is None
    assert uploads.sniff_image(b"") is None


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/api/nutrition/photo-estimate", uploads.PHOTO_LIMIT),
        ("/api/activities/12/pieces/photo-estimate", uploads.PHOTO_LIMIT),
        ("/api/pieces/3/photo", uploads.PHOTO_LIMIT),
        ("/api/clubs/abc/logo", uploads.LOGO_LIMIT),
        ("/api/coach/tools/log_food", uploads.TOOL_BODY_LIMIT),
        ("/api/notes", uploads.DEFAULT_BODY_LIMIT),
    ],
)
def test_each_route_family_has_its_own_ceiling(path, expected):
    assert uploads.body_limit_for(path) == expected


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def test_an_oversized_declared_body_is_refused_before_it_is_read(client):
    _login(client)
    resp = client.post("/api/notes", content=b"x" * (uploads.DEFAULT_BODY_LIMIT + 1), headers={"content-type": "application/json"})
    assert resp.status_code == 413


def test_an_oversized_streamed_body_with_no_content_length_is_refused(client):
    _login(client)

    def chunks():
        for _ in range(3):
            yield b"x" * (uploads.DEFAULT_BODY_LIMIT // 2)

    resp = client.post("/api/notes", content=chunks(), headers={"content-type": "application/json"})
    assert resp.status_code == 413


def test_a_photo_that_is_not_an_image_is_refused_whatever_it_claims(client):
    _login(client)
    for path in ("/api/nutrition/photo-estimate",):
        resp = client.post(path, files={"photo": ("meal.jpg", b"<svg onload=alert(1)>", "image/jpeg")})
        assert resp.status_code == 422 and "isn't a JPEG" in resp.json()["detail"]


def test_a_huge_photo_is_refused_by_size(client):
    _login(client)
    big = JPEG + b"\0" * (uploads.PHOTO_LIMIT + 10)
    resp = client.post("/api/nutrition/photo-estimate", files={"photo": ("meal.jpg", big, "image/jpeg")})
    assert resp.status_code == 413


def test_normal_requests_are_unaffected(client):
    _login(client)
    assert client.get("/api/health").status_code == 200
