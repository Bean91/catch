"""What each provider is, how a user connects it and what it can honestly do (docs/provider-connections.md).

One table feeds the REST cards, the coach/MCP tools, the Settings UI and the docs, so a limitation is stated once. Nothing here
holds a credential. Garmin lives behind this interface on purpose: if Garmin's Developer Program ever fits Catch, only the Garmin
entry (and `catch/sync/garmin_client.py`) changes.
"""

from __future__ import annotations

from datetime import date

from catch.core import tenant
from catch.core.config import settings

# capability values: yes | no | unknown (the provider documents nothing either way)
GARMIN_DISCLOSURE = (
    "Catch uses Garmin's Personal API with a key you create yourself. Garmin says that API is for an individual's own data and "
    "\"is not intended for commercial applications serving multiple end users\". You are connecting your own key to your own "
    "account; check Garmin's terms before relying on it."
)

_META: dict[str, dict] = {
    "garmin": {
        "label": "Garmin",
        "official": "Garmin Connect Personal API (an official, self-service key — not the Developer Program, not an unofficial login)",
        "available": lambda: (not tenant.is_public()) or settings.garmin_byok_enabled,
        "capabilities": {
            "activities": "yes",
            "activity_fit_files": "yes",
            "daily_summaries": "yes",
            "sleep": "yes",
            "heart_rate_variability": "yes",
            "respiration": "yes",
            "spo2": "yes",
            "weight": "yes",
            "skin_temperature": "no",
            "push_or_webhooks": "no",
            "documented_rate_limits": "unknown",
            "documented_history_depth": "unknown",
        },
        "limitations": [
            "You create the key yourself in Garmin Connect (Settings → Personal API Key). Garmin shows it once; keys last 30, 90, 180 or 365 days, then you create a new one.",
            "Catch asks only for that key — never your Garmin password. Garmin's Personal API has no OAuth sign-in, so there is no 'Sign in with Garmin' button.",
            "Pull only: Garmin offers no push or webhooks on this API, so Catch checks periodically.",
            "Garmin publishes no rate limits or history depth for this API. Catch imports history in small windows and backs off when Garmin says to slow down.",
            "Skin temperature isn't in Garmin's Personal API.",
            "Catch can't revoke a key at Garmin: delete the key in Garmin Connect to end access. Disconnecting here removes Catch's copy.",
        ],
        "notes": GARMIN_DISCLOSURE,
    },
    "withings": {
        "label": "Withings",
        "official": "Withings Public API (OAuth 2)",
        "available": lambda: bool(settings.withings_client_id and settings.withings_client_secret and settings.withings_redirect_uri),
        "capabilities": {"body_composition": "yes", "weight": "yes", "push_or_webhooks": "no", "token_revocation": "yes"},
        "limitations": [
            "You authorize on Withings' own page; Catch never sees your Withings password.",
            "Withings' API allows about 120 requests a minute across the whole Catch deployment (not per user).",
            "Disconnecting ends Catch's access at Withings too, and Catch forgets its copy. What was already imported stays.",
            "Weigh-ins Withings can't attribute to you (a shared scale's unassigned ones, or the weight typed in when the Withings account was created) aren't imported.",
        ],
        "notes": "Catch reads body measurements (weight and composition) only.",
    },
    "concept2": {
        "label": "Concept2",
        "official": "Concept2 Logbook API (OAuth 2, or a personal token you generate in the Logbook)",
        "available": lambda: True,  # the pasted personal token needs no operator app; OAuth is offered when one is configured
        "capabilities": {"results": "yes", "strokes": "yes", "push_or_webhooks": "no", "documented_rate_limits": "no", "token_revocation": "no"},
        "limitations": [
            "Connect with Concept2 (you authorize on log.concept2.com) or paste a personal token from Edit Profile → Applications. Catch asks for nothing else.",
            "Catch only reads your results; it never writes to your Logbook.",
            "Concept2 documents no way for an app to revoke access. Disconnecting removes Catch's copy; remove the application in your Logbook profile to end access there.",
            "A personal token has no documented lifetime. If Concept2 rejects it, Catch will say so and ask for a new one.",
        ],
        "notes": "Concept2 says its API is not rate limited today but reserves the right to limit or remove abusive access.",
    },
    "whoop": {
        "label": "Whoop",
        "official": "WHOOP Developer API (OAuth 2)",
        "available": lambda: bool(settings.whoop_client_id and settings.whoop_client_secret and settings.whoop_redirect_uri),
        "capabilities": {"sleep": "yes", "recovery": "yes", "workouts": "yes", "push_or_webhooks": "no", "token_revocation": "yes"},
        "limitations": [
            "You authorize on Whoop's own page; Catch never sees your Whoop password.",
            "Catch's Whoop app is limited to a small number of members until Whoop approves a higher tier, so connecting can be unavailable when that limit is reached.",
            "Whoop allows 100 requests a minute and 10,000 a day for the whole app; Catch waits and retries.",
            "Only scored records are imported. Whoop's own recovery and strain scores are reference only, never inputs.",
        ],
        "notes": "Whoop's refresh tokens rotate; if one is ever refused, Catch asks you to reconnect.",
    },
}


def oauth_available(provider: str) -> bool:
    """Is the operator's OAuth app for this provider configured (Garmin has none: it is a pasted key)?"""
    from catch.sync import concept2_client, whoop_client, withings_client

    return {"withings": withings_client.configured, "whoop": whoop_client.configured, "concept2": concept2_client.oauth_configured}.get(provider, lambda: False)()


def metadata(provider: str) -> dict:
    return _META[provider]


def capability_matrix(provider: str) -> dict[str, str]:
    return dict(_META[provider]["capabilities"])


def available(provider: str) -> bool:
    return bool(_META[provider]["available"]())


def parse_expiry(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise ValueError("Enter the expiry as a date (YYYY-MM-DD).") from None
