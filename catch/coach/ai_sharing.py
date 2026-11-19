"""What this person has agreed to send to their AI provider (session 28; docs/ai-data-sharing.md).

Catch never calls an AI provider on its own — only when the person chats, uses a photo feature, or connects an MCP client — and
always with *their* key. This module is the one place that decides what the model is allowed to see on those paths:

* No consent, no AI. Until the person has read the disclosure and acknowledged it (`consented_at` set for the current
  `CONSENT_VERSION`), chat and the photo features refuse, and no tool result is handed to a model.
* Every category starts OFF. A category switched off means its tool results are replaced by a fixed "sharing disabled" answer, its
  sections are left out of the system prompt's memory block, and (for photos) the image is never sent.
* The rule is enforced here, in the service layer, on the shared tool path (`call_tool`), the chat loop and the vision path —
  not in the prompt, so a model cannot argue its way past it.
* A person who says they are under 19 (the existing optional band — no date of birth is collected) can't switch the health
  categories on without ticking that a parent or guardian knows."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session

from catch.core.models import AiSharingSettings

CONSENT_VERSION = 1

CATEGORIES: dict[str, dict] = {
    "wellness": {"label": "Recovery, sleep and body data", "health": True, "description": "HRV, resting heart rate, sleep, recovery, strain, illness early-warning, body composition, load and trends."},
    "workouts": {"label": "Workouts and training", "health": True, "description": "Your workouts (including titles and any notes imported from Garmin, Concept2 or Whoop), zones, erg tests and pieces, strength sets, GPS-derived summaries (never raw coordinates) and weather, and the training-intelligence readouts."},
    "nutrition": {"label": "Nutrition", "health": True, "description": "Foods you logged, calories and macros, targets."},
    "notes_checkins": {"label": "Notes and check-ins", "health": True, "description": "Your workout notes and RPE, and today's check-in sliders and niggle."},
    "memory": {"label": "Coach memory", "health": True, "description": "The goals, injuries, schedule and preferences the coach remembers about you."},
    "calendar_library": {"label": "Calendar, plans and library", "health": False, "description": "Events and races, planned sessions, training phases, workout templates, technique notes and coach feedback."},
    "photos": {"label": "Photos you ask the coach to read", "health": True, "description": "A meal photo or a PM5 screen photo, sent once to your provider to be read and not stored by Catch."},
}
HEALTH = {k for k, v in CATEGORIES.items() if v["health"]}
YOUTH_BANDS = {"u19", "u18", "u17", "u16", "u15", "u14"}
ALL_BANDS = {"adult", *YOUTH_BANDS}

# Every tool -> the category whose data it returns. None = it returns nothing about the person's own health, training or notes
# (connection status, other people's public leaderboard/club information): always available. tests/coach/test_ai_sharing.py fails
# when a tool is missing from this table.
TOOL_CATEGORY: dict[str, str | None] = {
    # wellness
    "get_today": "wellness", "get_wellness": "wellness", "get_trends": "wellness", "get_body_comp": "wellness", "get_load": "wellness",
    "get_recommendations": "wellness", "rate_recommendation": "wellness", "get_muscle_readiness": "wellness",
    # workouts
    "list_workouts": "workouts", "get_workout": "workouts", "get_zones": "workouts", "predict_2k": "workouts", "get_tests": "workouts",
    "get_test": "workouts", "make_pacing_plan": "workouts", "add_piece": "workouts", "merge_activities": "workouts",
    "rename_activity": "workouts", "tag_activity": "workouts", "get_strength": "workouts", "log_strength": "workouts",
    "get_route": "workouts", "get_route_history": "workouts", "get_on_water_metrics": "workouts", "get_workout_weather": "workouts",
    "get_interval_comparisons": "workouts", "get_training_profile": "workouts", "get_performance_trends": "workouts",
    "get_training_distribution": "workouts", "get_training_consistency": "workouts", "get_training_insights": "workouts",
    "get_verified_results": "workouts",
    # nutrition
    "get_nutrition": "nutrition", "log_food": "nutrition",
    # notes
    "add_note": "notes_checkins",
    # memory
    "remember": "memory", "recall": "memory", "forget": "memory", "set_goal": "memory",
    # calendar, plans, library, coaching
    "get_calendar": "calendar_library", "get_upcoming_events": "calendar_library", "get_event": "calendar_library",
    "get_training_phase": "calendar_library", "create_event": "calendar_library", "update_event": "calendar_library",
    "create_planned_workout": "calendar_library", "update_planned_workout": "calendar_library", "delete_planned_workout": "calendar_library",
    "search_workout_library": "calendar_library", "get_workout_template": "calendar_library", "create_workout_template": "calendar_library",
    "update_workout_template": "calendar_library", "get_technique_notes": "calendar_library", "add_technique_note": "calendar_library",
    "get_coach_feedback": "calendar_library", "add_coach_feedback": "calendar_library",
    # nothing personal
    "get_connected_providers": None, "get_sync_status": None, "sync_provider": None, "get_leaderboards": None,
    "get_public_athlete_profile": None, "get_my_clubs": None, "get_club": None, "get_club_calendar": None,
    "get_club_challenges": None, "get_club_leaderboard": None,
}

# Which sections of the system prompt's memory block belong to which category.
MEMORY_SECTION_CATEGORY = {"memory": "memory", "events": "calendar_library", "checkin": "notes_checkins", "illness": "wellness", "recommendation": "wellness"}


def _row(session: Session) -> AiSharingSettings | None:
    from catch.core import tenant

    return session.get(AiSharingSettings, tenant.pk())


def enabled_categories(session: Session) -> set[str]:
    row = _row(session)
    if row is None or row.consented_at is None or row.consent_version < CONSENT_VERSION:
        return set()
    try:
        flags = json.loads(row.categories_json or "{}")
    except ValueError:
        return set()
    return {k for k, v in flags.items() if v is True and k in CATEGORIES}


def has_consented(session: Session) -> bool:
    row = _row(session)
    return row is not None and row.consented_at is not None and row.consent_version >= CONSENT_VERSION


def tool_decision(session: Session, name: str) -> dict | None:
    """None = allowed; otherwise the answer the model gets instead of data."""
    category = TOOL_CATEGORY.get(name)
    if category is None:
        return None
    if category in enabled_categories(session):
        return None
    label = CATEGORIES[category]["label"]
    return {
        "unavailable": True,
        "reason": "sharing_disabled",
        "category": category,
        "message": f"The athlete has not allowed '{label}' to be shared with the AI, so this can't be read. "
        "Tell them it's switched off (Settings → Privacy → AI sharing) rather than guessing, and don't ask for it again this conversation.",
    }


# Tools whose payload mixes categories: the part that belongs to another category is removed when that one is off.
_NOTE_KEYS = {"notes", "rpe", "day_note"}
_MIXED = {
    "get_today": {"notes_checkins": {"checkin"}, "calendar_library": {"upcoming_events", "next_event", "next_race"}},
    "list_workouts": {"notes_checkins": _NOTE_KEYS},
    "get_workout": {"notes_checkins": _NOTE_KEYS},
}


def _strip(value, keys: set[str]):
    if isinstance(value, dict):
        return {k: _strip(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_strip(v, keys) for v in value]
    return value


def arg_decision(session: Session, name: str, args: dict) -> dict | None:
    """Refuse by arguments: a trend over a check-in metric is notes-and-check-ins data even though get_trends is a wellness tool."""
    if name == "get_trends" and str(args.get("metric", "")).startswith("checkin_") and "notes_checkins" not in enabled_categories(session):
        return tool_decision(session, "add_note")  # same category, same message
    return None


def limit_result(session: Session, name: str, result):
    """Drop the parts of a result that belong to categories the person has not allowed."""
    rules = _MIXED.get(name)
    if not rules:
        return result
    enabled = enabled_categories(session)
    drop: set[str] = set()
    for category, keys in rules.items():
        if category not in enabled:
            drop |= keys
    return _strip(result, drop) if drop else result


def scrub_history(session: Session, history: list[dict]) -> list[dict]:
    """Earlier tool results are re-sent every turn. When a category has since been switched off (or consent withdrawn), replace what that
    category's tools returned with the same fixed notice, so turning something off really stops it reaching the provider."""
    names = {b["id"]: b["name"] for m in history for b in m.get("blocks", []) if b.get("type") == "tool_call"}
    out = []
    for m in history:
        blocks = []
        for b in m.get("blocks", []):
            if b.get("type") == "tool_result" and names.get(b.get("id")):
                refusal = tool_decision(session, names[b["id"]])
                if refusal is not None:
                    b = {**b, "output": refusal, "is_error": False}
            blocks.append(b)
        out.append({**m, "blocks": blocks})
    return out


def state(session: Session) -> dict:
    row = _row(session)
    enabled = enabled_categories(session)
    return {
        "consent_version": CONSENT_VERSION,
        "consented": has_consented(session),
        "consented_at": row.consented_at.isoformat() if row and row.consented_at else None,
        "age_band": row.age_band if row else None,
        "guardian_ack": bool(row and row.guardian_ack_at),
        "categories": [{"key": k, "label": v["label"], "description": v["description"], "health": v["health"], "enabled": k in enabled} for k, v in CATEGORIES.items()],
    }


class SharingError(ValueError):
    pass


def update(session: Session, *, acknowledge: bool, categories: dict[str, bool], age_band: str | None = None, guardian_ack: bool = False) -> dict:
    from catch.core import tenant

    unknown = set(categories) - set(CATEGORIES)
    if unknown:
        raise SharingError(f"Unknown categories: {sorted(unknown)}")
    if age_band is not None and age_band not in ALL_BANDS:
        raise SharingError("Unknown age band.")
    row = _row(session) or AiSharingSettings(owner_id=tenant.current_owner())
    consented = row.consented_at is not None and row.consent_version >= CONSENT_VERSION
    if not consented and not acknowledge:
        raise SharingError("Read and acknowledge what is shared before turning anything on.")
    band = age_band if age_band is not None else row.age_band
    ack = guardian_ack or row.guardian_ack_at is not None
    try:
        flags = json.loads(row.categories_json or "{}")
    except ValueError:
        flags = {}
    wanted = {**flags, **{k: bool(v) for k, v in categories.items()}}
    if band in YOUTH_BANDS and not ack and any(wanted.get(k) for k in HEALTH):
        raise SharingError("Because you said you're under 19, a parent or guardian needs to know before health data is shared with an AI. Tick the box to confirm.")
    now = datetime.now(timezone.utc)
    row.categories_json = json.dumps({k: wanted.get(k, False) for k in CATEGORIES})
    row.age_band = band
    if guardian_ack and row.guardian_ack_at is None:
        row.guardian_ack_at = now
    if acknowledge and not consented:
        row.consented_at, row.consent_version = now, CONSENT_VERSION
    row.updated_at = now
    session.add(row)
    session.commit()
    return state(session)


def revoke(session: Session) -> dict:
    """Withdraw consent entirely: every category off, and the AI refuses until the person agrees again."""
    row = _row(session)
    if row is not None:
        row.consented_at, row.categories_json, row.updated_at = None, "{}", datetime.now(timezone.utc)
        session.add(row)
        session.commit()
    return state(session)
