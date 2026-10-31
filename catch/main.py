from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from catch.api import routes_activities, routes_analytics, routes_auth, routes_body, routes_sync, routes_wellness
from catch.core.db import init_db
from catch.sync.scheduler import start_scheduler, stop_scheduler

_STATIC_DIR = Path(__file__).resolve().parent / "api" / "static"


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


@app.get("/api/health")
def health():
    return {"ok": True}


# Vite builds here (vite.config.ts outDir); gitignored, absent in dev/test — the frontend
# is served by `vite` directly in dev, so a missing dir must not break pytest or `uvicorn`.
if _STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = _STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC_DIR / "index.html")
