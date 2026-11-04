from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.coach.nutrition_vision import NutritionVisionError, estimate_meal_photo
from catch.sync import nutrition

router = APIRouter(dependencies=[Depends(require_auth)])

_MEALS = {"breakfast", "lunch", "dinner", "snack", "pre_workout", "post_workout"}
# Anthropic vision accepts these; a photo this app never writes to disk only needs to pass
# straight through, so there's no server-side re-encoding step to worry about beyond this check.
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _validate_meal(meal: str) -> None:
    if meal not in _MEALS:
        raise HTTPException(status_code=422, detail=f"meal must be one of {sorted(_MEALS)}")


# --- Barcode + search ------------------------------------------------------------------


@router.get("/api/nutrition/barcode/{barcode}")
def get_barcode(barcode: str, db: Session = Depends(get_db)):
    food = nutrition.lookup_or_fetch_barcode(db, barcode)
    if food is None:
        return {"found": False, "barcode": barcode}
    return {"found": True, **nutrition.food_dict(food)}


@router.get("/api/nutrition/search")
def search_foods(q: str = Query(..., min_length=1), include_off: bool = Query(False), db: Session = Depends(get_db)):
    return {"results": nutrition.search_foods(db, q, include_off=include_off)}


class ManualFoodRequest(BaseModel):
    barcode: str | None = None
    name: str
    brand: str | None = None
    serving_size: float | None = None
    serving_unit: str | None = None
    kcal_100g: float | None = None
    protein_100g: float | None = None
    carbs_100g: float | None = None
    fat_100g: float | None = None
    fiber_100g: float | None = None
    sugar_100g: float | None = None
    sodium_100g: float | None = None


@router.post("/api/nutrition/foods")
def post_manual_food(body: ManualFoodRequest, db: Session = Depends(get_db)):
    food = nutrition.create_manual_food(db, **body.model_dump())
    return nutrition.food_dict(food)


# --- My foods / saved meals --------------------------------------------------------------


@router.get("/api/nutrition/my-foods")
def get_my_foods(db: Session = Depends(get_db)):
    return {"my_foods": nutrition.list_my_foods(db)}


@router.post("/api/nutrition/my-foods")
def post_my_food(food_id: int = Query(...), label: str | None = Query(None), db: Session = Depends(get_db)):
    row = nutrition.star_food(db, food_id, label)
    return {"id": row.id, "food_id": row.food_id, "label": row.label}


@router.delete("/api/nutrition/my-foods/{my_food_id}")
def delete_my_food(my_food_id: int, db: Session = Depends(get_db)):
    if not nutrition.unstar_food(db, my_food_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


class SavedMealRequest(BaseModel):
    name: str
    items: list[dict]  # [{"food_id", "quantity", "unit"}, ...]


@router.get("/api/nutrition/saved-meals")
def get_saved_meals(db: Session = Depends(get_db)):
    return {"saved_meals": nutrition.list_saved_meals(db)}


@router.post("/api/nutrition/saved-meals")
def post_saved_meal(body: SavedMealRequest, db: Session = Depends(get_db)):
    row = nutrition.save_meal(db, body.name, body.items)
    return {"id": row.id, "name": row.name, "items": body.items}


@router.delete("/api/nutrition/saved-meals/{saved_meal_id}")
def delete_saved_meal(saved_meal_id: int, db: Session = Depends(get_db)):
    if not nutrition.delete_saved_meal(db, saved_meal_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


class LogSavedMealRequest(BaseModel):
    ts: datetime | None = None
    meal: str


@router.post("/api/nutrition/saved-meals/{saved_meal_id}/log")
def post_log_saved_meal(saved_meal_id: int, body: LogSavedMealRequest, db: Session = Depends(get_db)):
    _validate_meal(body.meal)
    try:
        rows = nutrition.log_saved_meal(db, saved_meal_id, body.ts or datetime.now(timezone.utc), body.meal)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"logged": [r.id for r in rows]}


# --- Food logs -----------------------------------------------------------------------------


class FoodLogRequest(BaseModel):
    ts: datetime | None = None
    meal: str
    food_id: int
    quantity: float
    unit: str  # "g" | "serving"


@router.get("/api/nutrition/logs")
def get_logs(from_: date | None = Query(None, alias="from"), to: date | None = Query(None), db: Session = Depends(get_db)):
    rows = nutrition.list_food_logs(db, from_, to)
    return {"logs": [nutrition.food_log_dict(db, r) for r in rows]}


@router.post("/api/nutrition/logs")
def post_log(body: FoodLogRequest, db: Session = Depends(get_db)):
    _validate_meal(body.meal)
    try:
        row = nutrition.create_food_log(
            db, ts=body.ts or datetime.now(timezone.utc), meal=body.meal, food_id=body.food_id, quantity=body.quantity, unit=body.unit
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": row.id, "kcal": row.kcal, "protein": row.protein, "carbs": row.carbs, "fat": row.fat}


class FoodLogPatchRequest(BaseModel):
    meal: str | None = None
    quantity: float | None = None
    unit: str | None = None


@router.patch("/api/nutrition/logs/{log_id}")
def patch_log(log_id: int, body: FoodLogPatchRequest, db: Session = Depends(get_db)):
    if body.meal is not None:
        _validate_meal(body.meal)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        row = nutrition.update_food_log(db, log_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": row.id, "kcal": row.kcal, "protein": row.protein, "carbs": row.carbs, "fat": row.fat}


@router.delete("/api/nutrition/logs/{log_id}")
def delete_log(log_id: int, db: Session = Depends(get_db)):
    if not nutrition.delete_food_log(db, log_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


class CopyDayRequest(BaseModel):
    from_date: date
    to_date: date
    meal: str | None = None


@router.post("/api/nutrition/logs/copy-day")
def post_copy_day(body: CopyDayRequest, db: Session = Depends(get_db)):
    if body.meal is not None:
        _validate_meal(body.meal)
    rows = nutrition.copy_day_logs(db, body.from_date, body.to_date, body.meal)
    return {"logged": [r.id for r in rows]}


# --- Targets and summaries ---------------------------------------------------------------


class TargetsPatchRequest(BaseModel):
    protein_g_per_kg: float | None = None
    carb_g_per_kg_rest: float | None = None
    carb_g_per_kg_moderate: float | None = None
    carb_g_per_kg_double_day: float | None = None
    carb_g_per_kg_pre_race: float | None = None
    kcal_target_source: str | None = None
    manual_kcal_target: int | None = None


@router.get("/api/nutrition/targets")
def get_targets(db: Session = Depends(get_db)):
    row = nutrition.get_targets_settings(db)
    computed = nutrition.compute_targets(db)
    return {
        "settings": {
            "protein_g_per_kg": row.protein_g_per_kg,
            "carb_g_per_kg_rest": row.carb_g_per_kg_rest,
            "carb_g_per_kg_moderate": row.carb_g_per_kg_moderate,
            "carb_g_per_kg_double_day": row.carb_g_per_kg_double_day,
            "carb_g_per_kg_pre_race": row.carb_g_per_kg_pre_race,
            "kcal_target_source": row.kcal_target_source,
            "manual_kcal_target": row.manual_kcal_target,
        },
        "today": computed,
    }


@router.put("/api/nutrition/targets")
def put_targets(body: TargetsPatchRequest, db: Session = Depends(get_db)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "kcal_target_source" in patch and patch["kcal_target_source"] not in ("garmin_total", "manual"):
        raise HTTPException(status_code=422, detail="kcal_target_source must be 'garmin_total' or 'manual'")
    nutrition.update_targets_settings(db, patch)
    return {"today": nutrition.compute_targets(db)}


@router.get("/api/nutrition/summary/day")
def get_day_summary(day: date = Query(...), db: Session = Depends(get_db)):
    return nutrition.daily_summary(db, day)


@router.get("/api/nutrition/summary/week")
def get_week_summary(from_: date = Query(..., alias="from"), to: date = Query(...), db: Session = Depends(get_db)):
    return nutrition.week_summary(db, from_, to)


# --- Photo estimate (task Part B.4) -----------------------------------------------------


@router.post("/api/nutrition/photo-estimate")
async def post_photo_estimate(photo: UploadFile = File(...), db: Session = Depends(get_db)):
    if photo.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail=f"photo must be one of {sorted(_ALLOWED_IMAGE_TYPES)}")
    image_bytes = await photo.read()
    try:
        result = estimate_meal_photo(db, image_bytes, photo.content_type)
    except NutritionVisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


class PhotoEstimateItem(BaseModel):
    name: str
    quantity_description: str | None = None
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float


class PhotoEstimateSaveRequest(BaseModel):
    ts: datetime | None = None
    meal: str
    items: list[PhotoEstimateItem]


@router.post("/api/nutrition/photo-estimate/save")
def post_photo_estimate_save(body: PhotoEstimateSaveRequest, db: Session = Depends(get_db)):
    _validate_meal(body.meal)
    rows = nutrition.save_photo_estimate(
        db, items=[i.model_dump() for i in body.items], meal=body.meal, ts=body.ts or datetime.now(timezone.utc)
    )
    return {"logged": [r.id for r in rows]}
