"""Session 30 (docs/mobile/): the store apps call the public API from a webview whose origin is capacitor://localhost (iOS) or
https://localhost (Android). The API authenticates with a bearer token (never a cookie), so the allowlist is exact origins and
credentials stay off."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from catch.api.native_cors import install_native_cors

ROOT = Path(__file__).resolve().parents[2]


def _app(origins=("capacitor://localhost", "https://localhost")) -> TestClient:
    app = FastAPI()

    @app.get("/api/x")
    def x():
        return {"ok": True}

    @app.post("/api/x")
    def post_x(body: dict):
        return body

    @app.get("/api/unauth")
    def unauth():
        from fastapi import HTTPException

        raise HTTPException(401, "Not authenticated")

    install_native_cors(app, list(origins))
    return TestClient(app)


def test_preflight_from_a_native_origin_is_allowed_with_the_headers_the_client_sends():
    c = _app()
    r = c.options(
        "/api/x",
        headers={"Origin": "capacitor://localhost", "Access-Control-Request-Method": "DELETE", "Access-Control-Request-Headers": "authorization,content-type"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "capacitor://localhost"
    assert "DELETE" in r.headers["access-control-allow-methods"]
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in r.headers  # bearer auth: a cookie must never ride along cross-origin
    assert r.headers.get("vary", "").lower().find("origin") >= 0


def test_actual_responses_carry_the_origin_header_even_on_errors():
    c = _app()
    for path in ("/api/x", "/api/unauth"):
        r = c.get(path, headers={"Origin": "https://localhost"})
        assert r.headers["access-control-allow-origin"] == "https://localhost", path
    r = c.post("/api/x", headers={"Origin": "https://localhost"}, content=b"not json")  # 422
    assert r.status_code == 422
    assert r.headers["access-control-allow-origin"] == "https://localhost"


def test_other_origins_get_no_cors_headers_and_a_failed_preflight():
    c = _app()
    for origin in ("https://evil.example.com", "http://localhost", "capacitor://localhost.evil.com", "null"):
        r = c.get("/api/x", headers={"Origin": origin})
        assert "access-control-allow-origin" not in r.headers, origin
        p = c.options("/api/x", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert p.status_code == 400, origin


def test_exposed_headers_let_the_app_read_retry_after_and_the_export_filename():
    r = _app().get("/api/x", headers={"Origin": "https://localhost"})
    exposed = r.headers["access-control-expose-headers"].lower()
    assert "retry-after" in exposed and "content-disposition" in exposed


def test_no_origins_configured_installs_nothing():
    c = _app(origins=())
    assert "access-control-allow-origin" not in c.get("/api/x", headers={"Origin": "https://localhost"}).headers


def _public_import(code: str) -> str:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(ROOT), "CATCH_DEPLOYMENT": "public", "SUPABASE_URL": "https://x.supabase.co", "DATABASE_URL": "postgresql://u:p@127.0.0.1:1/db", "PYTHONPATH": str(ROOT)}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-600:]
    return out.stdout.strip()


def test_the_public_app_is_wired_with_cors_outermost_and_a_personal_app_is_not():
    names = _public_import("import catch.main as m; print(','.join(mw.cls.__name__ for mw in m.app.user_middleware))").split(",")
    assert names[0] == "CORSMiddleware"  # user_middleware[0] is the outermost layer
    personal = subprocess.run(
        [sys.executable, "-c", "import catch.main as m; print([mw.cls.__name__ for mw in m.app.user_middleware])"],
        cwd=ROOT, env={"PATH": "/usr/bin:/bin", "HOME": str(ROOT), "CATCH_DEPLOYMENT": "personal", "PYTHONPATH": str(ROOT)}, capture_output=True, text=True, timeout=60,
    )
    assert personal.returncode == 0, personal.stderr[-400:]
    assert "CORSMiddleware" not in personal.stdout
