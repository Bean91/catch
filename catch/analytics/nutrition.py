from __future__ import annotations

# Session 13 (see PLAN.md Part B): pure nutrition math — no I/O, no DB models. The DB-facing
# half (reading Food/FoodLog/NutritionTarget, gathering the inputs below from real data) lives
# in catch/sync/nutrition.py.

_MACRO_KEYS = ("kcal", "protein", "carbs", "fat", "fiber", "sugar", "sodium")


def grams_for_quantity(quantity: float, unit: str, serving_size: float | None) -> float | None:
    """`unit` is "g" (quantity is already grams) or "serving" (quantity x the food's own
    `serving_size`, itself in grams — or treated as such for a liquid food whose
    `serving_unit` is "ml"; this app, like most trackers, approximates 1ml ~= 1g for liquids
    rather than modelling density). Returns None when a serving size is needed but unknown,
    so the caller can refuse to log rather than silently log zero."""
    if quantity <= 0:
        return None
    if unit == "g":
        return quantity
    if unit == "serving":
        return quantity * serving_size if serving_size else None
    return None


def scale_macros_per_100g(per_100g: dict, grams: float) -> dict:
    """`per_100g`: a Food row's own kcal_100g/protein_100g/.../sodium_100g values (any may be
    None — a field OFF/USDA didn't report). Scales each to the actual grams logged."""
    factor = grams / 100.0
    return {key: (per_100g.get(f"{key}_100g") * factor if per_100g.get(f"{key}_100g") is not None else None) for key in _MACRO_KEYS}


def training_tier(activities_today_count: int, days_to_a_race: int | None, taper: bool) -> str:
    """Task Part B.5's "planned/actual training load" has no direct source except the day's
    actual logged activities (there's no training-plan feature in this app) plus A-race
    proximity (`events`, via `catch.coach.memory.next_a_race` — the same taper/days-to-go the
    Today screen and coach memory already use). "pre_race": inside the final 3 days before an
    A-priority race — the window athletes/coaches commonly carb-load in, narrower than the
    whole 14-day taper window (which is lower *volume*, not yet peak carb need).
    "double_day": 2+ canonical activities logged that day. "moderate": exactly 1. "rest": 0."""
    if taper and days_to_a_race is not None and days_to_a_race <= 3:
        return "pre_race"
    if activities_today_count >= 2:
        return "double_day"
    if activities_today_count == 1:
        return "moderate"
    return "rest"


def nutrition_targets(*, weight_kg: float | None, kcal_target: float | None, tier: str, settings: dict) -> dict:
    """`settings`: a `NutritionTarget` row's fields (protein_g_per_kg, carb_g_per_kg_<tier>).
    Fat is deliberately not its own g/kg knob — it's the kcal remainder after protein and
    carbs are met, which is how most sports-nutrition guidance frames it (set protein and
    carbs to need, let fat fill the rest of the energy budget) rather than a third
    independently-tunable target that could conflict with `kcal_target`."""
    if weight_kg is None:
        return {
            "protein_g": None,
            "carb_g": None,
            "fat_g": None,
            "kcal_target": kcal_target,
            "tier": tier,
            "explanation": "No weight on record yet — log one on the Body page to get protein/carb targets.",
        }
    protein_per_kg = settings["protein_g_per_kg"]
    carb_per_kg = settings[f"carb_g_per_kg_{tier}"]
    protein_g = protein_per_kg * weight_kg
    carb_g = carb_per_kg * weight_kg
    fat_g = None
    explanation = (
        f"Protein {protein_per_kg:g} g/kg x {weight_kg:.1f} kg = {protein_g:.0f} g. "
        f"Carbs {carb_per_kg:g} g/kg ({tier.replace('_', ' ')}) x {weight_kg:.1f} kg = {carb_g:.0f} g."
    )
    if kcal_target:
        protein_kcal = protein_g * 4
        carb_kcal = carb_g * 4
        fat_kcal = max(0.0, kcal_target - protein_kcal - carb_kcal)
        fat_g = fat_kcal / 9
        explanation += f" Fat is the kcal remainder: ({kcal_target:.0f} - {protein_kcal:.0f} - {carb_kcal:.0f}) / 9 = {fat_g:.0f} g."
    else:
        explanation += " No kcal target yet (no recent Garmin total-burn data), so no fat target either."
    return {"protein_g": protein_g, "carb_g": carb_g, "fat_g": fat_g, "kcal_target": kcal_target, "tier": tier, "explanation": explanation}


def under_fuelling_flag(daily_balances: list[dict], *, min_logged_days: int = 3, deficit_threshold_pct: float = 0.25) -> dict:
    """`daily_balances`: trailing window, oldest first, each `{"date", "intake_kcal",
    "expenditure_kcal", "has_log"}`. Only days with `has_log=True` *and* a real expenditure
    figure count — an unlogged day is unknown, never treated as a zero-intake deficit day
    (task's explicit "no streaks, no shaming" ask would be badly undercut by flagging a day
    the athlete simply didn't open the app). Flags only when the most recent
    `min_logged_days` *logged* days each ran at least `deficit_threshold_pct` below
    expenditure — several days running, not a single rough day."""
    logged = [d for d in daily_balances if d.get("has_log") and d.get("expenditure_kcal")]
    if len(logged) < min_logged_days:
        return {"flag": False, "logged_days": len(logged), "explanation": "Not enough logged days yet to assess fuelling."}
    recent = logged[-min_logged_days:]
    deficit_pcts = [(d["expenditure_kcal"] - d["intake_kcal"]) / d["expenditure_kcal"] for d in recent]
    flagged = all(pct >= deficit_threshold_pct for pct in deficit_pcts)
    avg_deficit_kcal = sum(d["expenditure_kcal"] - d["intake_kcal"] for d in recent) / len(recent)
    return {
        "flag": flagged,
        "logged_days": len(logged),
        "avg_deficit_kcal": avg_deficit_kcal,
        "explanation": (
            f"The last {len(recent)} logged days each ran {deficit_threshold_pct:.0%}+ below expenditure "
            f"(avg {avg_deficit_kcal:.0f} kcal/day short) — worth a look at fuelling, not a reason to worry alone."
            if flagged
            else "Intake has kept pace with expenditure over the last logged days."
        ),
    }
