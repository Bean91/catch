"""Session 30 (docs/mobile/): CORS for the store apps' webviews, public deployment only.

A Capacitor app's page origin is capacitor://localhost (iOS) or https://localhost (Android), so every API call is cross-origin.
Catch authenticates those calls with an `Authorization: Bearer` header and never a cookie, which is why credentials stay off:
a browser must not attach the web app's cookies to a request from another origin, and nothing here needs them. The allowlist
is exact origins (never `*`, never a pattern)."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware


def install_native_cors(app: FastAPI, origins: list[str]) -> None:
    """Must be added after every other middleware so it is outermost: a 413 from the body limit, a 401 or a 422 then still carry
    the CORS headers, and the app can read the status instead of seeing an opaque network error."""
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Catch-App-Version"],
        expose_headers=["Retry-After", "Content-Disposition"],
        max_age=600,
    )
