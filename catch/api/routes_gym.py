from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.sync import gym
from catch.sync.scoring import recompute_scores

router = APIRouter(dependencies=[Depends(require_auth)])


# -- exercise library -------------------------------------------------------------------------


@router.get("/api/gym/exercises")
def list_exercises(q: str | None = None, db: Session = Depends(get_db)):
    return {"exercises": gym.list_exercises(db, query=q)}


class CustomExerciseRequest(BaseModel):
    name: str
    default_equipment_type: str
    movement_pattern: str
    unilateral: bool = False
    primary_muscles: list[str] = []
    secondary_muscles: list[str] = []


@router.post("/api/gym/exercises")
def post_exercise(body: CustomExerciseRequest, db: Session = Depends(get_db)):
    return gym.create_custom_exercise(db, **body.model_dump())


class ExercisePatchRequest(BaseModel):
    name: str | None = None
    default_equipment_type: str | None = None
    movement_pattern: str | None = None
    unilateral: bool | None = None
    primary_muscles: list[str] | None = None
    secondary_muscles: list[str] | None = None


@router.patch("/api/gym/exercises/{exercise_id}")
def patch_exercise(exercise_id: int, body: ExercisePatchRequest, db: Session = Depends(get_db)):
    try:
        return gym.update_exercise(db, exercise_id, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# -- gyms / stations ----------------------------------------------------------------------


@router.get("/api/gym/gyms")
def list_gyms(db: Session = Depends(get_db)):
    return {"gyms": [{"id": g.id, "name": g.name} for g in gym.list_gyms(db)]}


class GymRequest(BaseModel):
    name: str


@router.post("/api/gym/gyms")
def post_gym(body: GymRequest, db: Session = Depends(get_db)):
    row = gym.create_gym(db, body.name)
    return {"id": row.id, "name": row.name}


@router.get("/api/gym/gyms/{gym_id}/stations")
def list_stations(gym_id: int, db: Session = Depends(get_db)):
    return {"stations": gym.list_stations(db, gym_id)}


class StationRequest(BaseModel):
    name: str
    equipment_type: str
    config: dict = {}


@router.post("/api/gym/gyms/{gym_id}/stations")
def post_station(gym_id: int, body: StationRequest, db: Session = Depends(get_db)):
    return gym.upsert_station(db, gym_id=gym_id, name=body.name, equipment_type=body.equipment_type, config=body.config)


@router.put("/api/gym/gyms/{gym_id}/stations/{station_id}")
def put_station(gym_id: int, station_id: int, body: StationRequest, db: Session = Depends(get_db)):
    return gym.upsert_station(db, gym_id=gym_id, name=body.name, equipment_type=body.equipment_type, config=body.config, station_id=station_id)


# -- logging ---------------------------------------------------------------------------------


class SetRequest(BaseModel):
    client_id: str
    exercise_id: int
    gym_station_id: int | None = None
    seq: int = 0
    superset_group: int | None = None
    set_type: str = "working"
    reps: int
    side: str | None = None
    tempo: str | None = None
    rir: float | None = None
    rpe: float | None = None
    equipment_type: str
    load_kg: float | None = None
    bar_weight_kg: float | None = None
    pulley_multiplier: float | None = None
    added_weight_kg: float | None = None
    assistance_kg: float | None = None
    band_tag: str | None = None
    notes: str | None = None
    created_at: str | None = None


class SyncSetsRequest(BaseModel):
    client_session_id: str
    sets: list[SetRequest]
    deleted_client_ids: list[str] = []


@router.post("/api/gym/sessions/sync")
def sync_session(body: SyncSetsRequest, db: Session = Depends(get_db)):
    """The one endpoint the offline queue flushes to — every set in `sets` is upserted
    idempotently (safe to resend the same payload after a dropped response), and every id in
    `deleted_client_ids` is tombstoned. Triggers a recompute so Today/Trends reflect the
    session immediately, same as every other sync path."""
    results = [gym.upsert_set(db, body.client_session_id, s.model_dump(exclude_unset=True)) for s in body.sets]
    for client_id in body.deleted_client_ids:
        gym.delete_set(db, client_id)
    if body.sets or body.deleted_client_ids:
        recompute_scores(db)
    return {"sets": results}


@router.get("/api/gym/sessions/{client_session_id}/sets")
def get_session_sets(client_session_id: str, db: Session = Depends(get_db)):
    return {"sets": gym.list_session_sets(db, client_session_id)}


@router.get("/api/gym/exercises/{exercise_id}/last")
def get_last_sets(exercise_id: int, db: Session = Depends(get_db)):
    return {"sets": gym.last_session_sets_for_exercise(db, exercise_id)}


@router.get("/api/gym/repeat-last-workout")
def get_repeat_last_workout(db: Session = Depends(get_db)):
    return {"plan": gym.repeat_last_workout(db)}


# -- templates --------------------------------------------------------------------------------


@router.get("/api/gym/templates")
def list_templates(db: Session = Depends(get_db)):
    return {"templates": gym.list_templates(db)}


class TemplateRequest(BaseModel):
    name: str
    items: list[dict]


@router.post("/api/gym/templates")
def post_template(body: TemplateRequest, db: Session = Depends(get_db)):
    return gym.save_template(db, name=body.name, items=body.items)


@router.put("/api/gym/templates/{template_id}")
def put_template(template_id: int, body: TemplateRequest, db: Session = Depends(get_db)):
    try:
        return gym.save_template(db, name=body.name, items=body.items, template_id=template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/api/gym/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    gym.delete_template(db, template_id)
    return {"deleted": True}


# -- muscle readiness + Garmin drafts -------------------------------------------------------


@router.get("/api/gym/muscle-readiness")
def get_muscle_readiness(db: Session = Depends(get_db)):
    return gym.muscle_readiness(db)


@router.post("/api/gym/activities/{activity_id}/import-garmin-drafts")
def post_import_garmin_drafts(activity_id: int, db: Session = Depends(get_db)):
    return gym.import_garmin_draft_sets(db, activity_id)


class ConfirmDraftRequest(BaseModel):
    exercise_id: int
    equipment_type: str
    load_kg: float | None = None
    bar_weight_kg: float | None = None
    pulley_multiplier: float | None = None


@router.post("/api/gym/drafts/{client_id}/confirm")
def post_confirm_draft(client_id: str, body: ConfirmDraftRequest, db: Session = Depends(get_db)):
    try:
        result = gym.confirm_draft_set(
            db,
            client_id,
            exercise_id=body.exercise_id,
            equipment_type=body.equipment_type,
            load_kg=body.load_kg,
            bar_weight_kg=body.bar_weight_kg,
            pulley_multiplier=body.pulley_multiplier,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    recompute_scores(db)
    return result
