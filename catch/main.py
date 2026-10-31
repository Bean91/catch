from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from catch.api import routes_activities, routes_analytics, routes_auth, routes_body, routes_sync, routes_wellness
from catch.core.db import init_db
from catch.sync.scheduler import start_scheduler, stop_scheduler


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
