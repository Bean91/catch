"""Session 26 (docs/leaderboards.md): boards, eligibility, categories, ranking, validation and the ONE public
serializer. Pure, no I/O.

Every number a board ranks is an integer: tenths of a second for the fixed-distance boards (lower wins) and metres for
the fixed-time boards (higher wins), so equality — and therefore a tie — is exact and never a float comparison."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import date
from typing import Iterable, Optional

CONSENT_VERSION = 1

# Single constants a deployment can change (docs/leaderboards.md "Decisions"). Not legal advice — see the PLAN.md blockers.
MIN_PUBLISH_AGE = 13
GUARDIAN_CONSENT_BELOW = 16
ADULT_AGE = 18

BOARDS: dict[str, dict] = {
    "500m": {"kind": "distance", "target": 500, "label": "500 m"},
    "1000m": {"kind": "distance", "target": 1000, "label": "1,000 m"},
    "2000m": {"kind": "distance", "target": 2000, "label": "2,000 m"},
    "5000m": {"kind": "distance", "target": 5000, "label": "5,000 m"},
    "6000m": {"kind": "distance", "target": 6000, "label": "6,000 m"},
    "30min": {"kind": "timed", "target": 1800, "label": "30 minutes"},
    "60min": {"kind": "timed", "target": 3600, "label": "60 minutes"},
}
_RANKED_WORKOUT_TYPE = {"distance": "FixedDistanceSplits", "timed": "FixedTimeSplits"}

YOUTH_UNDER = (14, 15, 16, 17, 18, 19)
ADULT_BANDS = (("19-29", 19, 29), ("30-39", 30, 39), ("40-49", 40, 49), ("50-59", 50, 59), ("60-69", 60, 69), ("70-79", 70, 79), ("80+", 80, None))
AGE_LABELS = tuple(f"U{n}" for n in YOUTH_UNDER) + tuple(b[0] for b in ADULT_BANDS)
AGE_PROVENANCE = {"concept2_profile": "as reported to Concept2", "self_declared": "self-declared"}

WEIGHT_CLASS_LABELS = {"L": "Lightweight", "H": "Open (heavyweight)"}
PRECISIONS = ("none", "year", "month", "day")
DISPLAY_MODES = ("handle", "anonymous")
ANONYMOUS_NAME = "Anonymous rower"

VERIFICATION_LABELS = {"verified": "Verified", "provider_linked": "Provider-linked", "unverified": "Unverified"}


# ---------------------------------------------------------------- eligibility

def eligible_board(
    *,
    distance_m: float | None,
    duration_s: float | None,
    workout_type: str | None = None,
    erg_type: str | None = None,
    has_intervals: bool = False,
    is_piece: bool = False,
) -> Optional[tuple[str, int]]:
    """(board_key, ranked integer) for a result that exactly matches a board, else None. Never the 2% tolerance the test
    center uses to *suggest* a type: a 1,960 m piece is not a 2k. A Concept2 result must also be a RowErg, fixed
    distance/time, uninterrupted effort; a typed piece has no workout type to check."""
    if has_intervals or not distance_m or not duration_s or distance_m <= 0 or duration_s <= 0:
        return None
    if not is_piece and erg_type != "rower":
        return None
    for key, spec in BOARDS.items():
        want_type = _RANKED_WORKOUT_TYPE[spec["kind"]]
        if not is_piece and workout_type != want_type:
            continue
        if spec["kind"] == "distance":
            if float(distance_m) == float(spec["target"]):
                return key, int(round(duration_s * 10))
        elif abs(float(duration_s) - spec["target"]) < 0.05:
            return key, int(round(distance_m))
    return None


# ---------------------------------------------------------------- age

def age_on(dob: date, on: date) -> int:
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def adult_band_for(age: int) -> Optional[str]:
    for label, lo, hi in ADULT_BANDS:
        if age >= lo and (hi is None or age <= hi):
            return label
    return None


def split_age(age: int) -> tuple[Optional[int], Optional[str]]:
    """(age_years for the youth boards, adult band). Exactly one is set."""
    if age < ADULT_BANDS[0][1]:
        return age, None
    return None, adult_band_for(age)


def from_declared_label(label: str) -> tuple[Optional[int], Optional[str]]:
    """A self-declared band as (age_years, adult_band). "U16" means under 16, so the oldest age it could be (15) is used:
    the athlete lands in U16 and the boards above it, never in an easier band than they declared."""
    if label not in AGE_LABELS:
        raise ValueError("unknown age band")
    if label.startswith("U"):
        return int(label[1:]) - 1, None
    return None, label


def memberships(age_years: Optional[int], adult_band: Optional[str]) -> list[str]:
    """Every age board an entry appears on. Youth boards are cumulative ("under"): a 14-year-old is in U15 through U19."""
    if age_years is not None:
        return [f"U{n}" for n in YOUTH_UNDER if age_years < n]
    return [adult_band] if adult_band else []


def public_age_label(age_years: Optional[int], adult_band: Optional[str]) -> Optional[str]:
    labels = memberships(age_years, adult_band)
    return labels[0] if labels else None


def is_minor(age_years: Optional[int], source: Optional[str]) -> bool:
    if age_years is None:
        return False
    # A self-declared "U19" could be 17, so it keeps the minor protections.
    return age_years < (ADULT_AGE + 1 if source == "self_declared" else ADULT_AGE)


def age_gate(age_years: Optional[int], *, has_min_age_attestation: bool, has_guardian_attestation: bool) -> Optional[str]:
    """None when publishing may go ahead, else a short machine reason."""
    if age_years is not None and age_years < MIN_PUBLISH_AGE:
        return "below_minimum_age"
    if age_years is None and not has_min_age_attestation:
        return "age_attestation_required"
    if age_years is not None and age_years < GUARDIAN_CONSENT_BELOW and not has_guardian_attestation:
        return "guardian_consent_required"
    return None


# ---------------------------------------------------------------- dates, names, notes

def effective_precision(requested: str, minor: bool) -> str:
    if requested not in PRECISIONS:
        raise ValueError("date precision must be none, year, month or day")
    if minor and requested in ("month", "day"):
        return "year"
    return requested


def date_label(d: Optional[date], precision: str) -> Optional[str]:
    if d is None or precision == "none":
        return None
    return {"year": f"{d.year:04d}", "month": f"{d.year:04d}-{d.month:02d}", "day": d.isoformat()}[precision]


_HANDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{1,22}[A-Za-z0-9]$")
_RESERVED = {"admin", "administrator", "moderator", "mod", "catch", "concept2", "support", "official", "staff", "system", "anonymous", "anonymousrower", "null", "none"}
_URL_RE = re.compile(r"(https?:|www\.|\b[\w-]+\.(com|net|org|io|co|me|app|dev|uk|us|de|nl)\b|@\w+\.\w+)", re.I)


def validate_handle(raw: str) -> str:
    handle = " ".join((raw or "").split())
    if not _HANDLE_RE.match(handle):
        raise ValueError("handle must be 3-24 characters: letters, numbers, spaces, - or _")
    squashed = re.sub(r"[^a-z0-9]", "", handle.lower())
    if squashed in _RESERVED or squashed.startswith("catch") or "concept2" in squashed or "moderator" in squashed:
        raise ValueError("that handle is reserved")
    if _URL_RE.search(handle) or "http" in squashed or "www" in squashed:
        raise ValueError("a handle can't contain a web address")
    return handle


def validate_note(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    note = " ".join(raw.split())
    if not note:
        return None
    if len(note) > 140:
        raise ValueError("a note is at most 140 characters")
    if _URL_RE.search(note) or any(ord(c) < 32 for c in note):
        raise ValueError("a note can't contain a web address")
    return note


# ---------------------------------------------------------------- formatting

def format_tenths(tenths: int) -> str:
    minutes, rest = divmod(tenths, 600)
    seconds, t = divmod(rest, 10)
    return f"{minutes}:{seconds:02d}.{t}"


def format_value(board_key: str, value: int) -> dict:
    spec = BOARDS[board_key]
    if spec["kind"] == "distance":
        split = value / (spec["target"] / 500)
        return {"result": format_tenths(value), "split_500m": format_tenths(int(round(split)))}
    return {"result": f"{value:,} m", "split_500m": None}


# ---------------------------------------------------------------- ranking

def _sort_key(kind: str):
    sign = 1 if kind == "distance" else -1
    return lambda r: (sign * r["value"], r["tiebreak"])


def rank_entries(rows: Iterable[dict], board_key: str) -> list[dict]:
    """One best row per athlete_key, ordered best-first, with standard competition ranking (1, 2, 2, 4). Rows tied on
    the integer value share a rank; their order is the entry tiebreak hash, which carries no date or publication order."""
    kind = BOARDS[board_key]["kind"]
    key = _sort_key(kind)
    best: dict[str, dict] = {}
    for r in sorted(rows, key=key):
        best.setdefault(r["athlete_key"], r)
    ordered = sorted(best.values(), key=key)
    out, prev_value, rank = [], None, 0
    for i, r in enumerate(ordered, start=1):
        if r["value"] != prev_value:
            rank, prev_value = i, r["value"]
        out.append({**r, "rank": rank})
    return out


def rank_board(rows: Iterable[dict], board_key: str, include_unverified: bool) -> dict:
    """Verified rows are ranked among themselves. With `include_unverified`, the rest follow in their own separately
    ranked list and never displace a verified row; an athlete with a verified entry isn't repeated there."""
    rows = list(rows)
    verified = rank_entries([r for r in rows if r["verification"] == "verified"], board_key)
    out = {"ranked": verified, "unverified": []}
    if include_unverified:
        seen = {r["public_id"] for r in verified}
        rest = [r for r in rows if r["verification"] != "verified" and r["public_id"] not in seen]
        out["unverified"] = rank_entries(rest, board_key)
    return out


def athlete_key(secret: str, provider: Optional[str], provider_user_id: Optional[str], owner_id: str) -> str:
    """Keyed hash so the board can count one athlete once without storing or exposing a Concept2 user id."""
    subject = f"{provider}:{provider_user_id}" if provider and provider_user_id else f"owner:{owner_id}"
    return hmac.new(secret.encode(), subject.encode(), hashlib.sha256).hexdigest()[:32]


def tiebreak_for(entry_id: str) -> str:
    return hashlib.sha256(entry_id.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- the one public serializer

PUBLIC_ENTRY_KEYS = (
    "entry_id", "athlete_id", "name", "board_key", "board_label", "result", "split_500m", "verification",
    "verification_label", "age_label", "age_provenance", "weight_class", "date_label", "note",
)
PUBLIC_RANKED_KEYS = PUBLIC_ENTRY_KEYS + ("rank",)


def public_entry_view(entry: dict, athlete: dict, *, rank: Optional[int] = None) -> dict:
    """The only place a result becomes public JSON: the privacy preview, the stored projection, board rows and the coach
    tools all render through here, so what you preview is what is published. Takes explicit fields only."""
    board = BOARDS[entry["board_key"]]
    shown = format_value(entry["board_key"], entry["value"])
    anonymous = athlete.get("display_mode") == "anonymous" or not athlete.get("handle")
    view = {
        "entry_id": entry["entry_id"],
        "athlete_id": athlete["public_id"],
        "name": ANONYMOUS_NAME if anonymous else athlete["handle"],
        "board_key": entry["board_key"],
        "board_label": board["label"],
        "result": shown["result"],
        "split_500m": shown["split_500m"],
        "verification": entry["verification"],
        "verification_label": VERIFICATION_LABELS[entry["verification"]],
        "age_label": entry.get("age_label"),
        "age_provenance": AGE_PROVENANCE.get(entry.get("age_provenance")) if entry.get("age_label") else None,
        "weight_class": WEIGHT_CLASS_LABELS.get(entry.get("weight_class")) if entry.get("weight_class") else None,
        "date_label": entry.get("date_label"),
        "note": entry.get("note"),
    }
    if rank is not None:
        view["rank"] = rank
    return view


def preview_hash(view: dict) -> str:
    return hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
