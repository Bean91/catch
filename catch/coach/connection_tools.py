from __future__ import annotations

"""Session 25 (docs/provider-connections.md): the three connection tools, merged into catch.coach.tools.TOOLS.

They read and trigger through the same service layer the Settings → Connections routes use (`catch.sync.connections`,
`catch.sync.scheduler.run_sync`), for the *calling user's own* connections only (the owner comes from the verified transport, never
from an argument). Nothing here can see, set or replace a stored key or token: the service's cards carry only a status, dates and
the fixed capability/limitation text. A sync is a write to the athlete's data, so it previews first and runs only with confirm=true."""

from sqlmodel import Session

from catch.core import principal as pr
from catch.core.principal import principal_from
from catch.sync import connections

# Deliberately small: no token expiry timestamps, no last-four characters, no account identifiers.
_CARD_KEYS = (
    "provider", "label", "connected", "status", "status_text", "auth_method", "scopes", "credential_expires_on",
    "last_success_at", "importing_history_from", "capabilities", "limitations",
)


def _gate(args: dict, preview: dict, what: str) -> dict | None:
    from catch.coach.tools import _gate as gate

    return gate(args, preview, what)


def _athlete(ctx: dict) -> None:
    p = principal_from(ctx)
    if p.role != pr.ATHLETE_ROLE:
        raise ValueError("Only the athlete's own session can use the connection tools.")


def _get_connected_providers(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    return {"providers": [{k: c[k] for k in _CARD_KEYS} for c in connections.list_cards(session)]}


def _get_sync_status(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    return {"sources": connections.sync_summary(session)}


def _sync_provider(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    provider = args.get("provider")
    if provider not in connections.PROVIDERS:
        raise ValueError(f"provider must be one of {', '.join(connections.PROVIDERS)}")
    card = connections.card(session, provider)
    if not card["connected"]:
        raise ValueError(f"{card['label']} isn't connected. The athlete connects it in Settings → Connections.")
    preview = {
        "provider": provider,
        "label": card["label"],
        "status": card["status"],
        "last_success_at": card["last_success_at"],
        "action": f"Fetch recent {card['label']} data now and update the athlete's records.",
    }
    held = _gate(args, preview, f"sync {card['label']}")
    if held:
        return held
    from catch.sync.scheduler import run_sync

    return {"saved": True, "result": run_sync(provider, manual=True)}


_PROVIDER = {"type": "string", "enum": list(connections.PROVIDERS)}

TOOLS: dict[str, dict] = {
    "get_connected_providers": {
        "fn": _get_connected_providers,
        "write": False,
        "description": "Which data sources (Garmin, Withings, Concept2, Whoop) the athlete has connected, each one's connection status, "
        "what Catch can and can't read from it, and when it last synced. Never includes anything needed to sign in to a source.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    "get_sync_status": {
        "fn": _get_sync_status,
        "write": False,
        "description": "Sync health per connected source: last attempt and success, the last error in plain words, consecutive failures, "
        "when the next scheduled attempt is allowed, and whether history is still being imported.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    "sync_provider": {
        "fn": _sync_provider,
        "write": True,
        "description": "Fetch the latest data from one connected source now. Previews first and runs only with confirm=true after the athlete agrees. "
        "It cannot connect, reconnect or disconnect a source — only the athlete can, in Settings.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"provider": _PROVIDER, "confirm": {"type": "boolean", "description": "Must be true to actually sync; omit to preview."}},
            "required": ["provider"],
        },
    },
}
