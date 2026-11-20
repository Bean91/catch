"""Session 30 (docs/mobile/deep-links.md): the two association files that let the store apps claim the deployment's own https links
(universal links on iOS, verified App Links on Android). Public deployment only; each answers 404 until the operator sets the
identifiers, so a half-configured server never advertises an app it can't vouch for. Unauthenticated by design — the OS fetches
them with no credentials — and they hold nothing but public identifiers."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from catch.core import tenant
from catch.core.config import settings

router = APIRouter()

# The paths the app handles in-process (web/src/lib/native/deepLinkTargets.ts has the allow-list that actually routes them).
IOS_COMPONENTS = [
    {"/": "/workouts/*"},
    {"/": "/calendar"},
    {"/": "/calendar/events/*"},
    {"/": "/coach"},
    {"/": "/checkin"},
    {"/": "/clubs/join"},
    {"/": "/settings/connections"},
    {"/": "/", "?": {"code": "?*"}},  # a Supabase sign-up / password-reset link
]


def apple_app_site_association() -> dict:
    return {"applinks": {"details": [{"appIDs": [f"{settings.apple_team_id}.{settings.apple_bundle_id}"], "components": IOS_COMPONENTS}]}}


def asset_links() -> list[dict]:
    prints = [p.strip().upper() for p in settings.android_cert_sha256.split(",") if p.strip()]
    return [{"relation": ["delegate_permission/common.handle_all_urls"], "target": {"namespace": "android_app", "package_name": settings.android_package, "sha256_cert_fingerprints": prints}}]


@router.get("/.well-known/apple-app-site-association", include_in_schema=False)
def aasa():
    if not tenant.is_public() or not settings.apple_team_id:
        raise HTTPException(status_code=404)
    # application/json, served directly: Apple's CDN does not follow redirects for this file.
    return JSONResponse(apple_app_site_association(), headers={"Cache-Control": "public, max-age=3600"})


@router.get("/.well-known/assetlinks.json", include_in_schema=False)
def assetlinks():
    if not tenant.is_public() or not settings.android_cert_sha256.strip():
        raise HTTPException(status_code=404)
    return JSONResponse(asset_links(), headers={"Cache-Control": "public, max-age=3600"})
