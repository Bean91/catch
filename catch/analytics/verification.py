"""Session 26 (docs/leaderboards.md): what "verified" means for a rowing result. Pure, no I/O.

Verified means the SOURCE can be authenticated: the result was fetched through the athlete's own Concept2
connection, belongs to the Concept2 account that connection authenticated, and Concept2 itself flags it
verified. It is never a claim about who the athlete is or what condition they were in."""

from __future__ import annotations

import json
from typing import Any, Optional

VERIFIED = "verified"
PROVIDER_LINKED = "provider_linked"
UNVERIFIED = "unverified"
STATES = (VERIFIED, PROVIDER_LINKED, UNVERIFIED)

EXPLANATION = {
    VERIFIED: "Fetched through your own Concept2 account and flagged verified by Concept2. Catch can authenticate where "
    "this result came from; it does not confirm who rowed it or the conditions it was rowed in.",
    PROVIDER_LINKED: "Comes from a source you connected, but it does not meet every verified condition (for example "
    "Concept2 has not flagged it verified).",
    UNVERIFIED: "Typed or photographed by you. Catch has no way to authenticate it.",
}


def _raw(activity: Any) -> dict:
    blob = getattr(activity, "raw_json", None)
    if not blob:
        return {}
    try:
        data = json.loads(blob)
    except (TypeError, ValueError):
        return {}
    return data.get("data", data) if isinstance(data, dict) else {}


def concept2_meta(activity: Any) -> dict:
    """The Concept2 fields verification needs. The promoted columns win; rows synced before they existed fall back to
    the stored raw payload, so no backfill job is needed."""
    raw = _raw(activity)
    user_id = getattr(activity, "c2_user_id", None)
    if user_id is None and raw.get("user_id") is not None:
        user_id = str(raw["user_id"])
    verified = getattr(activity, "c2_verified", None)
    if verified is None and isinstance(raw.get("verified"), bool):
        verified = raw["verified"]
    weight_class = getattr(activity, "c2_weight_class", None) or raw.get("weight_class")
    return {
        "user_id": str(user_id) if user_id is not None else None,
        "verified": verified,
        "weight_class": weight_class if weight_class in ("H", "L") else None,
        "date_utc": raw.get("date_utc"),
        "date": raw.get("date"),
        "timezone": raw.get("timezone"),
        "result_id": raw.get("id"),
    }


def classify(
    *,
    source_kind: str,
    connected_account_id: Optional[str],
    result_user_id: Optional[str],
    provider_verified: Optional[bool],
    piece_source: Optional[str] = None,
) -> str:
    """`source_kind` is "concept2_result" or "piece". A piece is never verified: it keeps its own typed distance and
    Concept2's flag covers a whole result, not a window inside one."""
    if source_kind == "piece":
        return PROVIDER_LINKED if piece_source == "concept2" else UNVERIFIED
    if source_kind != "concept2_result":
        return UNVERIFIED
    if connected_account_id is None:
        return UNVERIFIED
    if provider_verified is True and result_user_id is not None and result_user_id == connected_account_id:
        return VERIFIED
    return PROVIDER_LINKED
