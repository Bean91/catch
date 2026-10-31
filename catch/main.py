from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from catch.api import (
    routes_activities,
    routes_analytics,
    routes_auth,
    routes_body,
    routes_notes,
    routes_sync,
    routes_wellness,
)
from catch.core.db import init_db
from catch.sync.scheduler import start_scheduler, stop_scheduler

_STATIC_DIR = (Path(__file__).resolve().parent / "api" / "static").resolve()


def safe_static_file(full_path: str) -> Path | None:
    """Resolves `full_path` under `_STATIC_DIR` and refuses anything that escapes it (e.g.
    `../../.env` or an encoded equivalent FastAPI has already decoded by the time this runs).
    Returns None for anything outside the dir or that isn't a file, so the caller always has
    a safe index.html fallback to reach for instead."""
    candidate = (_STATIC_DIR / full_path).resolve()
    if not candidate.is_relative_to(_STATIC_DIR):
        return None
    return candidate if candidate.is_file() else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Catch", lifespan=lifespan)

app.include_router(routes_auth.router)
app.include_router(routes_wellness.router)
app.include_router(routes_activities.router)
app.include_router(routes_body.router)
app.include_router(routes_sync.router)
app.include_router(routes_analytics.router)
app.include_router(routes_notes.router)


@app.get("/api/health")
def health():
    return {"ok": True}


# Vite builds here (vite.config.ts outDir); gitignored, absent in dev/test — the frontend
# is served by `vite` directly in dev, so a missing dir must not break pytest or `uvicorn`.
if _STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # A typo'd /api/ or /auth/ path must 404, not fall through to index.html with a 200 —
        # that would mask a broken route behind what looks like a working page load.
        if full_path.startswith("api/") or full_path.startswith("auth/"):
            raise HTTPException(status_code=404)
        safe = safe_static_file(full_path)
        if safe is not None:
            return FileResponse(safe)
        return FileResponse(_STATIC_DIR / "index.html")
