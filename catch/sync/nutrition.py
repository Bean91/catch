from __future__ import annotations

import json
from datetime import date as date_, datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from catch.analytics.nutrition import grams_for_quantity, nutrition_targets as _nutrition_targets_fn, scale_macros_per_100g, training_tier, under_fuelling_flag
from catch.coach.memory import next_a_race
from catch.core.config import settings as app_settings
from catch.core.models import CanonicalActivity, DailyWellness, Food, FoodLog, MyFood, NutritionTarget, SavedMeal
from catch.sync import body_comp
from catch.sync.openfoodfacts_client import OpenFoodFactsClient
from catch.sync.usda_client import UsdaClient

_MACRO_FIELDS = ("kcal", "protein", "carbs", "fat", "fiber", "sugar", "sodium")


def _local_day_utc_range(day: date_) -> tuple[datetime, datetime]:
    # Same convention as catch/sync/scoring.py and catch/coach/cost.py.
    local_midnight = datetime(day.year, day.month, day.day)
    start_utc = local_midnight.astimezone(timezone.utc)
    end_utc = (local_midnight + timedelta(days=1)).astimezone(timezone.utc)
    return start_utc, end_utc


def _food_per_100g(food: Food) -> dict:
    return {
        "kcal_100g": food.kcal_100g,
        "protein_100g": food.protein_100g,
        "carbs_100g": food.carbs_100g,
        "fat_100g": food.fat_100g,
        "fiber_100g": food.fiber_100g,
        "sugar_100g": food.sugar_100g,
        "sodium_100g": food.sodium_100g,
    }


def food_dict(food: Food) -> dict:
    return {
        "id": food.id,
        "source": food.source,
        "barcode": food.barcode,
        "name": food.name,
        "brand": food.brand,
        "serving_size": food.serving_size,
        "serving_unit": food.serving_unit,
        "kcal_100g": food.kcal_100g,
        "protein_100g": food.protein_100g,
        "carbs_100g": food.carbs_100g,
        "fat_100g": food.fat_100g,
        "fiber_100g": food.fiber_100g,
        "sugar_100g": food.sugar_100g,
        "sodium_100g": food.sodium_100g,
        "verified": food.verified,
    }


# --- Barcode lookup (task Part B.3) -----------------------------------------------------


def lookup_or_fetch_barcode(session: Session, barcode: str) -> Food | None:
    """Lookup order: local `foods` cache (any source, including a prior OFF/USDA hit or a
    manual entry) -> Open Food Facts -> USDA FoodData Central -> None (the caller falls back
    to a manual-entry form prefilled with the barcode). A found external result is cached
    into `foods` immediately so a repeat scan never re-hits either API."""
    existing = session.exec(select(Food).where(Food.barcode == barcode)).first()
    if existing is not None:
        return existing

    parsed = OpenFoodFactsClient().lookup_barcode(barcode)
    if parsed is None and app_settings.usda_fdc_api_key:
        parsed = UsdaClient(app_settings.usda_fdc_api_key).lookup_barcode(barcode)
    if parsed is None:
        return None

    food = Food(barcode=barcode, **parsed)
    session.add(food)
    session.commit()
    session.refresh(food)
    return food


# --- Search (task Part B.3) -------------------------------------------------------------


def _get_or_create_cached_food(session: Session, parsed: dict) -> Food:
    """Caches a USDA search hit into `foods` immediately (task's "cache every hit") so every
    search result handed to the UI already has a real id to log against — never a
    null-id placeholder the route layer would have to special-case. Dedup key is `barcode`
    when the result has one (most Branded foods); otherwise `(source, name, brand)`, since a
    repeated search for the same generic food (no barcode at all — e.g. "chicken breast")
    would otherwise insert a near-duplicate row on every search."""
    barcode = parsed.get("barcode")
    if barcode:
        existing = session.exec(select(Food).where(Food.barcode == barcode)).first()
    else:
        existing = session.exec(
            select(Food).where(Food.source == parsed["source"], Food.name == parsed["name"], Food.brand == parsed.get("brand"))
        ).first()
    if existing is not None:
        return existing
    food = Food(**parsed)
    session.add(food)
    session.commit()
    session.refresh(food)
    return food


def search_foods(session: Session, query: str, limit: int = 20) -> list[dict]:
    """Local cache first, ranked by recency/frequency of use in `food_logs` (a food never
    logged sorts after any food that has been, newest-logged-first among those); USDA
    free-text results are appended after, deduplicated against anything the local cache
    already surfaced by barcode. **Open Food Facts has no free-text search in its v2 API**
    (confirmed against its own docs — only exact-barcode lookup and a structured
    category/brand/nutrient filter search exist, neither of which fits a plain text box) —
    see docs/nutrition-endpoints.md; its contribution to this app stays barcode-scan-only."""
    like = f"%{query}%"
    local = session.exec(
        select(Food).where((Food.name.ilike(like)) | (Food.brand.ilike(like))).limit(limit * 2)
    ).all()

    log_stats: dict[int, tuple[int, datetime]] = {}
    for food in local:
        rows = session.exec(select(FoodLog.ts).where(FoodLog.food_id == food.id)).all()
        if rows:
            log_stats[food.id] = (len(rows), max(rows))

    def sort_key(food: Food):
        count, last_ts = log_stats.get(food.id, (0, None))
        return (last_ts is None, -(last_ts.timestamp() if last_ts else 0), -count)

    local_sorted = sorted(local, key=sort_key)[:limit]
    results = [food_dict(f) for f in local_sorted]

    remaining = limit - len(results)
    if remaining > 0 and app_settings.usda_fdc_api_key:
        seen_barcodes = {f["barcode"] for f in results if f["barcode"]}
        usda = UsdaClient(app_settings.usda_fdc_api_key)
        for parsed in usda.search(query, page_size=remaining * 2)[:remaining]:
            if parsed.get("barcode") and parsed["barcode"] in seen_barcodes:
                continue
            food = _get_or_create_cached_food(session, parsed)
            results.append(food_dict(food))

    return results[:limit]


# --- Manual entry / my foods / saved meals (task Part B.1) -----------------------------


def create_manual_food(session: Session, **fields) -> Food:
    food = Food(source="manual", verified=True, **fields)
    session.add(food)
    session.commit()
    session.refresh(food)
    return food


def star_food(session: Session, food_id: int, label: str | None = None) -> MyFood:
    existing = session.exec(select(MyFood).where(MyFood.food_id == food_id)).first()
    if existing:
        return existing
    row = MyFood(food_id=food_id, label=label)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def unstar_food(session: Session, my_food_id: int) -> bool:
    row = session.get(MyFood, my_food_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def list_my_foods(session: Session) -> list[dict]:
    rows = session.exec(select(MyFood).order_by(MyFood.created_at.desc())).all()
    out = []
    for row in rows:
        food = session.get(Food, row.food_id)
        if food is None:
            continue
        out.append({"my_food_id": row.id, "label": row.label, **food_dict(food)})
    return out


def save_meal(session: Session, name: str, items: list[dict]) -> SavedMeal:
    row = SavedMeal(name=name, items_json=json.dumps(items))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_saved_meals(session: Session) -> list[dict]:
    rows = session.exec(select(SavedMeal).order_by(SavedMeal.created_at.desc())).all()
    return [{"id": r.id, "name": r.name, "items": json.loads(r.items_json), "created_at": r.created_at} for r in rows]


def delete_saved_meal(session: Session, saved_meal_id: int) -> bool:
    row = session.get(SavedMeal, saved_meal_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


# --- Food logs (task Part B.1/B.7) ------------------------------------------------------


def create_food_log(
    session: Session, *, ts: datetime, meal: str, food_id: int, quantity: float, unit: str, estimated: bool = False
) -> FoodLog:
    food = session.get(Food, food_id)
    if food is None:
        raise ValueError("Food not found")
    grams = grams_for_quantity(quantity, unit, food.serving_size)
    if grams is None:
        raise ValueError(f"Can't log {food.name} by serving — no known serving size. Log by grams instead.")
    macros = scale_macros_per_100g(_food_per_100g(food), grams)
    row = FoodLog(ts=ts, meal=meal, food_id=food_id, quantity=quantity, unit=unit, estimated=estimated, **macros)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def log_saved_meal(session: Session, saved_meal_id: int, ts: datetime, meal: str) -> list[FoodLog]:
    saved = session.get(SavedMeal, saved_meal_id)
    if saved is None:
        raise ValueError("Saved meal not found")
    items = json.loads(saved.items_json)
    return [
        create_food_log(session, ts=ts, meal=meal, food_id=item["food_id"], quantity=item["quantity"], unit=item["unit"])
        for item in items
    ]


def copy_day_logs(session: Session, from_day: date_, to_day: date_) -> list[FoodLog]:
    """Task Part B.7's "copy yesterday's meal" — copies every log from `from_day` to the same
    time-of-day on `to_day`, recomputing macros fresh against each food's *current* per-100g
    data (not a byte-copy of the old row) so a since-corrected food doesn't carry a stale
    number forward."""
    start, end = _local_day_utc_range(from_day)
    rows = session.exec(select(FoodLog).where(FoodLog.ts >= start, FoodLog.ts < end).order_by(FoodLog.ts)).all()
    day_delta = to_day - from_day
    out = []
    for row in rows:
        new_ts = row.ts + timedelta(days=day_delta.days)
        out.append(create_food_log(session, ts=new_ts, meal=row.meal, food_id=row.food_id, quantity=row.quantity, unit=row.unit))
    return out


def update_food_log(session: Session, log_id: int, **fields) -> FoodLog:
    row = session.get(FoodLog, log_id)
    if row is None:
        raise ValueError("Log not found")
    if "quantity" in fields or "unit" in fields:
        food = session.get(Food, row.food_id)
        quantity = fields.get("quantity", row.quantity)
        unit = fields.get("unit", row.unit)
        grams = grams_for_quantity(quantity, unit, food.serving_size)
        if grams is None:
            raise ValueError(f"Can't log {food.name} by serving — no known serving size. Log by grams instead.")
        macros = scale_macros_per_100g(_food_per_100g(food), grams)
        fields = {**fields, **macros, "quantity": quantity, "unit": unit}
    for key, value in fields.items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_food_log(session: Session, log_id: int) -> bool:
    row = session.get(FoodLog, log_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def list_food_logs(session: Session, from_: date_ | None = None, to: date_ | None = None) -> list[FoodLog]:
    stmt = select(FoodLog).order_by(FoodLog.ts)
    if from_:
        stmt = stmt.where(FoodLog.ts >= _local_day_utc_range(from_)[0])
    if to:
        stmt = stmt.where(FoodLog.ts < _local_day_utc_range(to)[1])
    return session.exec(stmt).all()


# --- Targets and summaries (task Part B.5/B.6/B.7) --------------------------------------


def get_targets_settings(session: Session) -> NutritionTarget:
    row = session.get(NutritionTarget, 1)
    if row is None:
        row = NutritionTarget(id=1)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def update_targets_settings(session: Session, patch: dict) -> NutritionTarget:
    row = get_targets_settings(session)
    for key, value in patch.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _trailing_kcal_target(session: Session, today: date_, days: int = 7) -> float | None:
    """Task Part B.5: "kcal from Garmin total burn" — a trailing average of *completed* days
    only, never including today's own still-accumulating `total_kcal` (which at 8am is a few
    hundred kcal and would set a nonsense target)."""
    rows = session.exec(
        select(DailyWellness.total_kcal)
        .where(DailyWellness.date < today, DailyWellness.date >= today - timedelta(days=days), DailyWellness.total_kcal.is_not(None))
    ).all()
    values = [v for v in rows if v]
    return sum(values) / len(values) if values else None


def _resolved_weight_kg(session: Session) -> tuple[float | None, str | None]:
    """Latest resolved body-comp weight regardless of source — Withings OAuth may still be
    incomplete, so this never hard-requires it (unlike the task's literal "Withings weight"
    phrasing); the source is always labelled so the UI can say which scale it came from."""
    rows = body_comp.resolve_daily(session)
    for entry in reversed(rows):
        if entry.get("weight") is not None:
            return entry["weight"], entry.get("weight_source")
    return None, None


def today_training_tier(session: Session, today: date_) -> str:
    start, end = _local_day_utc_range(today)
    count = len(session.exec(select(CanonicalActivity.id).where(CanonicalActivity.start >= start, CanonicalActivity.start < end)).all())
    race = next_a_race(session, today)
    days_to_go = race["days_to_go"] if race else None
    taper = race["taper"] if race else False
    return training_tier(count, days_to_go, taper)


def compute_targets(session: Session, today: date_ | None = None) -> dict:
    today = today or date_.today()
    settings_row = get_targets_settings(session)
    settings = {
        "protein_g_per_kg": settings_row.protein_g_per_kg,
        "carb_g_per_kg_rest": settings_row.carb_g_per_kg_rest,
        "carb_g_per_kg_moderate": settings_row.carb_g_per_kg_moderate,
        "carb_g_per_kg_double_day": settings_row.carb_g_per_kg_double_day,
        "carb_g_per_kg_pre_race": settings_row.carb_g_per_kg_pre_race,
    }
    weight_kg, weight_source = _resolved_weight_kg(session)
    if settings_row.kcal_target_source == "manual":
        kcal_target = settings_row.manual_kcal_target
    else:
        kcal_target = _trailing_kcal_target(session, today)
    tier = today_training_tier(session, today)
    result = _nutrition_targets_fn(weight_kg=weight_kg, kcal_target=kcal_target, tier=tier, settings=settings)
    result["weight_source"] = weight_source
    return result


def _day_totals(session: Session, day: date_) -> dict:
    start, end = _local_day_utc_range(day)
    rows = session.exec(select(FoodLog).where(FoodLog.ts >= start, FoodLog.ts < end)).all()
    totals = {field: 0.0 for field in _MACRO_FIELDS}
    for row in rows:
        for field in _MACRO_FIELDS:
            value = getattr(row, field)
            if value is not None:
                totals[field] += value
    return {**totals, "has_log": len(rows) > 0, "logs": rows}


def daily_summary(session: Session, day: date_) -> dict:
    totals = _day_totals(session, day)
    targets = compute_targets(session, day)
    wellness = session.get(DailyWellness, day)
    expenditure = wellness.total_kcal if wellness else None
    return {
        "date": day,
        "intake": {k: totals[k] for k in _MACRO_FIELDS},
        "targets": targets,
        "expenditure_kcal": expenditure,
        "logs": [
            {
                "id": r.id,
                "ts": r.ts,
                "meal": r.meal,
                "food_id": r.food_id,
                "quantity": r.quantity,
                "unit": r.unit,
                "estimated": r.estimated,
                **{k: getattr(r, k) for k in _MACRO_FIELDS},
            }
            for r in totals["logs"]
        ],
    }


def week_summary(session: Session, from_: date_, to: date_) -> dict:
    days = []
    cursor = from_
    while cursor <= to:
        totals = _day_totals(session, cursor)
        wellness = session.get(DailyWellness, cursor)
        expenditure = wellness.total_kcal if wellness else None
        days.append(
            {
                "date": cursor,
                "intake_kcal": totals["kcal"],
                "protein": totals["protein"],
                "expenditure_kcal": expenditure,
                "has_log": totals["has_log"],
            }
        )
        cursor += timedelta(days=1)

    balances = [{"date": d["date"], "intake_kcal": d["intake_kcal"], "expenditure_kcal": d["expenditure_kcal"], "has_log": d["has_log"]} for d in days]
    return {"days": days, "under_fuelling": under_fuelling_flag(balances)}
