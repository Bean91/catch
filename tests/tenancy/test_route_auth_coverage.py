"""Every route is behind an authentication dependency or is on this reviewed allowlist. A new route that forgets its
dependency fails here instead of shipping open."""

from __future__ import annotations

from fastapi.routing import APIRoute

import catch.main as main_module
from catch.api import deps, routes_internal

AUTH_CALLABLES = {
    deps.require_auth,
    deps.require_tool_auth,
    deps.require_tool_auth_allow_coach,
    routes_internal.require_tick_secret,
}

# (method, path) of routes that are intentionally reachable without a session. Each has a reason; adding one is a security review.
OPEN = {
    ("GET", "/api/health"): "liveness probe, returns nothing user-specific",
    ("POST", "/api/login"): "personal install only (404 on public): it IS the login",
    ("POST", "/api/logout"): "personal install only: clears the cookie",
    ("GET", "/{full_path:path}"): "the built SPA; returns static files only and 404s anything under api/ or auth/",
    ("GET", "/auth/{provider}/callback"): "OAuth redirect target: identity comes from the signed state cookie, never the request",
}
# Personal-install-only routes that carry their own gate (`personal_only` → 404 on a public deployment); they are not reachable there.
PERSONAL_ONLY_GATES = {"personal_only"}


def _walk(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _walk(dep)


def _calls(route: APIRoute, extra: tuple = ()) -> set:
    return set(_walk(route.dependant)) | {d.dependency for d in extra}


def all_routes(routes=None, prefix: str = "", extra: tuple = ()):
    """(path, route, include-level dependencies) for every APIRoute, looking through `include_router` — this FastAPI version keeps
    included routers as lazy `_IncludedRouter` objects rather than copying their routes into `app.routes`."""
    for r in main_module.app.routes if routes is None else routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r, extra
        elif hasattr(r, "original_router"):
            ctx = r.include_context
            yield from all_routes(r.original_router.routes, prefix + (ctx.prefix or ""), extra + tuple(ctx.dependencies or ()))


def test_every_api_route_is_authenticated_or_explicitly_open():
    offenders = []
    for path, route, extra in all_routes():
        if _calls(route, extra) & AUTH_CALLABLES:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (method, path) not in OPEN:
                offenders.append(f"{method} {path}")
    assert not offenders, "routes with no authentication dependency and no entry in OPEN:\n  " + "\n  ".join(offenders)


def test_the_open_list_has_no_stale_entries():
    present = {(m, path) for path, r, _ in all_routes() for m in r.methods}
    optional = {("GET", "/{full_path:path}")}  # only registered when the frontend has been built (absent in CI's python job)
    assert set(OPEN) - optional <= present, sorted(set(OPEN) - optional - present)


def test_moderation_routes_require_the_moderator_check_as_well():
    from catch.api import routes_moderation

    seen = 0
    for path, route, extra in all_routes():
        if path.startswith("/api/moderation"):
            seen += 1
            assert routes_moderation.require_moderator in _calls(route, extra), path
    assert seen >= 6


def test_internal_routes_are_all_behind_the_tick_secret():
    seen = 0
    for path, route, extra in all_routes():
        if path.startswith("/internal"):
            seen += 1
            assert routes_internal.require_tick_secret in _calls(route, extra), path
    assert seen == 3  # tick/{job}, db-check, config-check


def test_the_walker_actually_sees_the_whole_api():
    paths = {p for p, _, _ in all_routes()}
    assert len(paths) > 200 and "/api/account" in paths and "/api/clubs/{club_id}/logo" in paths
