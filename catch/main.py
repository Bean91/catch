from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from catch.api import (
    routes_account,
    routes_activities,
    routes_internal,
    routes_ai,
    routes_analytics,
    routes_auth,
    routes_body,
    routes_calendar,
    routes_coaching,
    routes_library,
    routes_checkins,
    routes_coach,
    routes_gps,
    routes_gym,
    routes_illness,
    routes_notes,
    routes_nutrition,
    routes_pieces,
    routes_push,
    routes_status,
    routes_sync,
    routes_tests,
    routes_training_intelligence,
    routes_wellness,
)
from catch.core import tenant
from catch.core.config import settings
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


def _no_cache_headers_for(target: Path) -> dict[str, str] | None:
    """sw.js, index.html, and version.json are the files a client needs a *fresh* copy of to
    ever notice a new deploy — index.html references the new build's hashed asset filenames,
    sw.js's own VERSION const is what it uses to name its caches, and version.json is what
    useServiceWorkerUpdate.ts's poll actually compares against __BUILD_ID__. Every hashed
    /assets/* file is immutable per build and fine to cache normally; these three must never be
    served stale by an intermediate cache (or iOS Safari's own aggressive caching)."""
    return {"Cache-Control": "no-cache"} if target.name in ("sw.js", "index.html", "version.json") else None


def _check_public_runtime() -> None:
    """Refuse to serve a public deployment that would make the RLS claims false: a runtime role that
    bypasses row level security (docs/public-architecture.md §6)."""
    import os

    from catch.core import db_pg
    from catch.core.db import engine

    if os.environ.get("CATCH_ALLOW_PRIVILEGED_DB") == "1":
        logging.getLogger("catch").warning("CATCH_ALLOW_PRIVILEGED_DB=1: RLS is NOT protecting this deployment's requests")
        return
    db_pg.assert_unprivileged(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if tenant.is_public():
        _check_public_runtime()
    start_scheduler()  # a no-op in a public deployment
    if settings.mcp_http_enabled:
        # Mounted sub-apps don't get their own lifespan from the parent ASGI app, so the MCP
        # session manager has to be started from Catch's own lifespan instead (verified
        # against the installed mcp SDK, which errors on any /mcp request without this).
        from catch.mcp_server.http_app import mcp_server as _mcp_server

        async with _mcp_server.session_manager.run():
            yield
    else:
        yield
    stop_scheduler()


# Nothing in this app calls logging.basicConfig()/dictConfig(), so every logger — including
# apscheduler's own "Running job..."/"executed successfully" lines — already defaults to
# Python's WARNING-level "handler of last resort" (confirmed: getEffectiveLevel() == 30 with
# zero config). Explicit here rather than relying on that default by accident: the new
# 10-minute notification-check job (session 16, see PLAN.md Part A) would otherwise be ~288
# extra INFO lines/day straight onto the Pi's SD card the moment anything upstream (a future
# dependency, a debugging session) ever does call basicConfig() and raises the root level.
logging.getLogger("apscheduler").setLevel(logging.WARNING)
from catch.core.redact import install_log_filter  # noqa: E402

install_log_filter()

app = FastAPI(title="Catch", lifespan=lifespan)

_KEY_ROUTES = ("/api/ai/", "/api/coach/key")


@app.exception_handler(RequestValidationError)
async def _validation_errors(request: Request, exc: RequestValidationError):
    """FastAPI's default 422 echoes each offending `input`. On the routes that carry a provider
    API key that would hand the submitted secret back in an error body (and into any log or proxy
    that records it), so those responses drop `input` and `ctx`."""
    if request.url.path.startswith(_KEY_ROUTES):
        errors = [{"type": e.get("type"), "loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})
    return await request_validation_exception_handler(request, exc)

@app.exception_handler(tenant.ParentNotFound)
async def _parent_not_found(request: Request, exc: tenant.ParentNotFound):
    # A foreign id is reported exactly like a missing one — never "forbidden", which would confirm it exists.
    return JSONResponse(status_code=404, content={"detail": "Not found"})


@app.exception_handler(tenant.TenantViolation)
async def _tenant_violation(request: Request, exc: tenant.TenantViolation):
    logging.getLogger("catch.tenant").error("tenant violation on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=403, content={"detail": "Forbidden"})


@app.exception_handler(tenant.NoTenantContext)
async def _no_tenant(request: Request, exc: tenant.NoTenantContext):
    return JSONResponse(status_code=401, content={"detail": "Not authenticated"})


app.include_router(routes_auth.router)
app.include_router(routes_account.router)
app.include_router(routes_internal.router)
app.include_router(routes_wellness.router)
app.include_router(routes_activities.router)
app.include_router(routes_body.router)
app.include_router(routes_sync.router)
app.include_router(routes_analytics.router)
app.include_router(routes_notes.router)
app.include_router(routes_coach.tool_router)
app.include_router(routes_coach.coach_router)
app.include_router(routes_ai.router)
app.include_router(routes_nutrition.router)
app.include_router(routes_gym.router)
app.include_router(routes_checkins.router)
app.include_router(routes_illness.router)
app.include_router(routes_tests.router)
app.include_router(routes_pieces.router)
app.include_router(routes_push.router)
app.include_router(routes_status.router)
app.include_router(routes_training_intelligence.router)
app.include_router(routes_gps.router)
app.include_router(routes_calendar.router)
app.include_router(routes_library.router)
app.include_router(routes_coaching.router)


@app.get("/api/health")
def health():
    return {"ok": True}


if settings.mcp_http_enabled:
    # Registered before the SPA catch-all below — Starlette matches mounts and routes in
    # registration order, and `/{full_path:path}` would otherwise swallow every /mcp request.
    from catch.mcp_server.http_app import mounted_mcp_app

    app.mount("/mcp", mounted_mcp_app())


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
        target = safe if safe is not None else _STATIC_DIR / "index.html"
        return FileResponse(target, headers=_no_cache_headers_for(target))
