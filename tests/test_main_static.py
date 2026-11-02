from __future__ import annotations

from pathlib import Path

import catch.main as main


def test_safe_static_file_rejects_traversal(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html></html>")
    secret = tmp_path / ".env"
    secret.write_text("CATCH_PASSWORD_HASH=super-secret")

    monkeypatch.setattr(main, "_STATIC_DIR", static_dir.resolve())

    assert main.safe_static_file("../.env") is None
    assert main.safe_static_file("../../.env") is None
    assert main.safe_static_file("%2e%2e/.env") is None  # literal chars, FastAPI decodes before this runs
    assert main.safe_static_file("nonexistent.js") is None


def test_safe_static_file_accepts_real_asset(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html></html>")
    (static_dir / "assets").mkdir()
    (static_dir / "assets" / "app.js").write_text("console.log('x')")

    monkeypatch.setattr(main, "_STATIC_DIR", static_dir.resolve())

    result = main.safe_static_file("assets/app.js")
    assert result == (static_dir / "assets" / "app.js").resolve()


def test_no_cache_headers_only_for_sw_index_and_version(tmp_path):
    assert main._no_cache_headers_for(tmp_path / "sw.js") == {"Cache-Control": "no-cache"}
    assert main._no_cache_headers_for(tmp_path / "index.html") == {"Cache-Control": "no-cache"}
    assert main._no_cache_headers_for(tmp_path / "version.json") == {"Cache-Control": "no-cache"}
    assert main._no_cache_headers_for(tmp_path / "assets" / "index-abc123.js") is None
