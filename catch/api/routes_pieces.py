from __future__ import annotations

"""Session 17 (see PLAN.md — the task called itself "session 13"): add-a-piece endpoints.
Two input methods (photo, typed/pasted splits) both end at the same POST .../pieces create
call with a plain splits list — the frontend's review table is what differs, not the save
path. A piece never silently "corrects" a bad reading (task Part B.3): create/update return
`{piece: null, validation}` when a check fails, unless the caller explicitly passes
`force=true` after the athlete has seen the issues and still wants to save as-is."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session

from catch.analytics.piece import PIECE_TYPES, default_splits, parse_splits_paste
from catch.api.deps import get_db, require_auth
from catch.coach.piece_vision import PieceVisionError, estimate_piece_photo
from catch.core.models import CanonicalActivity
from catch.analytics.piece_intervals import MAX_INTERVALS, expand_repeat
from catch.sync import piece as piece_sync
from catch.sync import piece_intervals as intervals_sync

router = APIRouter(dependencies=[Depends(require_auth)])

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _require_canonical(canonical_id: int, db: Session) -> CanonicalActivity:
    canonical = db.get(CanonicalActivity, canonical_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return canonical


@router.get("/api/activities/{canonical_id}/pieces")
def list_pieces(canonical_id: int, db: Session = Depends(get_db)):
    _require_canonical(canonical_id, db)
    return {"pieces": piece_sync.list_pieces_payload(db, canonical_id)}


@router.get("/api/activities/{canonical_id}/pieces/template")
def piece_template(
    canonical_id: int,
    piece_type: str = Query(..., alias="type"),
    distance_m: float | None = None,
    duration_s: float | None = None,
    db: Session = Depends(get_db),
):
    _require_canonical(canonical_id, db)
    if piece_type not in PIECE_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of {PIECE_TYPES}")
    return {"splits": default_splits(piece_type, distance_m=distance_m, duration_s=duration_s)}


class PasteSplitsRequest(BaseModel):
    text: str


@router.post("/api/pieces/parse-paste")
def parse_paste(body: PasteSplitsRequest):
    """Task Part C.1's paste support — exposed as its own endpoint (rather than only the TS
    mirror in web/src/lib/pieceSplits.ts) so the exact same parser backs the MCP/coach path
    (free text like "my 2k was 6:32.4, splits 1:36.8, ...") and is checkable independent of
    the frontend build."""
    try:
        return {"splits": parse_splits_paste(body.text)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class PieceSplitRow(BaseModel):
    split_index: int
    distance_m: float | None = None
    split_s: float | None = None
    rate: float | None = None
    watts: float | None = None
    hr: float | None = None
    # "typed" | "derived" | "concept2" | None — without this field, Pydantic silently drops
    # it from every request body (extra keys are ignored by default), so a row's real
    # provenance never reached _mark_typed_hr/_apply_alignment: every edit re-tagged every
    # HR-bearing row "typed" from scratch, permanently freezing derived values against a
    # later re-align. A real bug an advisor review caught.
    hr_source: str | None = None


class IntervalIn(BaseModel):
    """One work interval. Bounds here are the cheap structural ones (Pydantic); cross-field
    rules (exactly the prescribed side present, split vs distance/time, max>=avg HR) live in
    catch/analytics/piece_intervals.validate_intervals and come back as soft validation."""

    # Present when editing an existing interval inside a `replace` set, so its id survives.
    id: int | None = None
    target_type: str
    work_distance_m: float | None = Field(None, ge=0)
    work_duration_s: float | None = Field(None, ge=0)
    rest_duration_s: float | None = Field(None, ge=0)
    avg_split_s: float | None = Field(None, ge=0)
    avg_watts: float | None = Field(None, ge=0)
    avg_rate: float | None = Field(None, ge=0)
    avg_hr: float | None = Field(None, ge=0)
    max_hr: float | None = Field(None, ge=0)
    calories: float | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=500)


class CreatePieceRequest(BaseModel):
    piece_type: str
    splits: list[PieceSplitRow] = []
    # Session 19: when present, this is an interval piece — splits are ignored.
    intervals: list[IntervalIn] | None = Field(None, max_length=MAX_INTERVALS)
    distance_m: float | None = None
    duration_s: float | None = None
    drag_factor: int | None = None
    source: str = "manual"
    notes: str | None = None
    force: bool = False


def _piece_response(piece, validation: dict, db: Session | None = None) -> dict:
    return {
        "piece": piece_sync.piece_payload(db, piece) if piece is not None and db is not None else (piece_sync.piece_dict(piece) if piece is not None else None),
        "validation": validation,
    }


@router.post("/api/activities/{canonical_id}/pieces")
def create_piece(canonical_id: int, body: CreatePieceRequest, db: Session = Depends(get_db)):
    _require_canonical(canonical_id, db)
    if body.piece_type not in PIECE_TYPES:
        raise HTTPException(status_code=422, detail=f"piece_type must be one of {PIECE_TYPES}")
    if body.source not in ("manual", "photo"):
        raise HTTPException(status_code=422, detail="source must be 'manual' or 'photo'")
    if body.intervals is not None:
        piece, validation = intervals_sync.create_interval_piece(
            db,
            canonical_id,
            [r.model_dump() for r in body.intervals],
            piece_type=body.piece_type,
            notes=body.notes,
            force=body.force,
        )
        return _piece_response(piece, validation, db)
    if not body.splits:
        raise HTTPException(status_code=422, detail="splits (or intervals) required")
    piece, validation = piece_sync.create_piece(
        db,
        canonical_id,
        body.piece_type,
        [r.model_dump() for r in body.splits],
        distance_m=body.distance_m,
        duration_s=body.duration_s,
        drag_factor=body.drag_factor,
        source=body.source,
        notes=body.notes,
        force=body.force,
    )
    return _piece_response(piece, validation, db)


@router.post("/api/activities/{canonical_id}/pieces/photo-estimate")
async def photo_estimate(canonical_id: int, photo: UploadFile = File(...), db: Session = Depends(get_db)):
    """Vision draft only — nothing is saved (task Part B.4's same "never silently corrects"
    principle: the athlete reviews/edits before anything is written). The photo itself is
    re-sent by the client to POST .../pieces/{id}/photo after the piece is created, rather
    than held server-side between these two calls."""
    _require_canonical(canonical_id, db)
    if photo.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail=f"photo must be one of {sorted(_ALLOWED_IMAGE_TYPES)}")
    image_bytes = await photo.read()
    try:
        return estimate_piece_photo(db, image_bytes, photo.content_type)
    except PieceVisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class UpdatePieceRequest(BaseModel):
    splits: list[PieceSplitRow] | None = None
    # The independent "total" the athlete entered or the screen showed (task Part C.1's
    # "enter the total and splits and it checks they match") — omit to keep validating
    # against the piece's existing total rather than re-deriving one from these same splits.
    distance_m: float | None = None
    duration_s: float | None = None
    notes: str | None = None
    force: bool = False


@router.patch("/api/pieces/{piece_id}")
def update_piece(piece_id: int, body: UpdatePieceRequest, db: Session = Depends(get_db)):
    existing = piece_sync.get_piece(db, piece_id)
    if existing is not None and existing.has_intervals and (body.splits is not None or body.distance_m is not None or body.duration_s is not None):
        raise HTTPException(status_code=422, detail="This piece is made of intervals — edit its intervals instead of splits or totals.")
    try:
        piece, validation = piece_sync.update_piece(
            db,
            piece_id,
            splits=[r.model_dump() for r in body.splits] if body.splits is not None else None,
            distance_m=body.distance_m,
            duration_s=body.duration_s,
            notes=body.notes,
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _piece_response(piece, validation, db)


@router.delete("/api/pieces/{piece_id}")
def delete_piece(piece_id: int, db: Session = Depends(get_db)):
    if not piece_sync.delete_piece(db, piece_id):
        raise HTTPException(status_code=404, detail="Piece not found")
    return {"deleted": True}


class AlignPieceRequest(BaseModel):
    activity_id: int | None = None
    start_s: int | None = None


@router.post("/api/pieces/{piece_id}/align")
def align_piece(piece_id: int, body: AlignPieceRequest | None = None, db: Session = Depends(get_db)):
    """No body (or neither field) re-runs the auto-suggest; both fields together is a manual
    drag on the HR graph (task Part D.1)."""
    activity_id = body.activity_id if body else None
    start_s = body.start_s if body else None
    existing = piece_sync.get_piece(db, piece_id)
    if existing is not None and existing.has_intervals:
        raise HTTPException(status_code=422, detail="An interval piece isn't one contiguous effort, so it can't be aligned to a single window.")
    try:
        piece = piece_sync.align_piece(db, piece_id, activity_id=activity_id, start_s=start_s)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return piece_sync.piece_dict(piece, has_photo=piece_sync.get_photo(db, piece_id) is not None)


@router.post("/api/pieces/{piece_id}/photo")
async def upload_photo(piece_id: int, photo: UploadFile = File(...), db: Session = Depends(get_db)):
    if piece_sync.get_piece(db, piece_id) is None:
        raise HTTPException(status_code=404, detail="Piece not found")
    if photo.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail=f"photo must be one of {sorted(_ALLOWED_IMAGE_TYPES)}")
    image_bytes = await photo.read()
    piece_sync.attach_photo(db, piece_id, image_bytes, photo.content_type)
    return {"has_photo": True}


@router.get("/api/pieces/{piece_id}/photo")
def get_photo(piece_id: int, db: Session = Depends(get_db)):
    photo = piece_sync.get_photo(db, piece_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="No photo for this piece")
    return Response(content=photo.image, media_type=photo.content_type)


@router.delete("/api/pieces/{piece_id}/photo")
def delete_photo(piece_id: int, db: Session = Depends(get_db)):
    if not piece_sync.delete_photo(db, piece_id):
        raise HTTPException(status_code=404, detail="No photo for this piece")
    return {"deleted": True}


# --- Session 19: intervals within a piece ------------------------------------------------------


def _require_piece(piece_id: int, db: Session):
    piece = piece_sync.get_piece(db, piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Piece not found")
    return piece


def _intervals_response(db: Session, piece_id: int, validation: dict, saved: bool) -> dict:
    piece = _require_piece(piece_id, db)
    return {"saved": saved, "validation": validation, "piece": piece_sync.piece_payload(db, piece)}


@router.get("/api/activities/{canonical_id}/pieces/interval-template")
def interval_template(
    canonical_id: int,
    count: int = Query(..., ge=1, le=MAX_INTERVALS),
    distance_m: float | None = Query(None, gt=0),
    duration_s: float | None = Query(None, gt=0),
    rest_s: float | None = Query(None, ge=0),
    db: Session = Depends(get_db),
):
    """"4 x 500m r1:00" -> rows. One implementation (the analytics module's expand_repeat) so the
    frontend generator, coach tool and API can't disagree."""
    _require_canonical(canonical_id, db)
    try:
        return {"intervals": expand_repeat(count, work_distance_m=distance_m, work_duration_s=duration_s, rest_duration_s=rest_s)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class FromConcept2Request(BaseModel):
    activity_id: int


@router.post("/api/activities/{canonical_id}/pieces/from-concept2")
def pieces_from_concept2(canonical_id: int, body: FromConcept2Request, db: Session = Depends(get_db)):
    _require_canonical(canonical_id, db)
    try:
        piece = intervals_sync.build_intervals_from_concept2(db, canonical_id, body.activity_id)
    except intervals_sync.NoIntervalData as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"piece": piece_sync.piece_payload(db, piece)}


@router.get("/api/pieces/{piece_id}")
def get_piece(piece_id: int, db: Session = Depends(get_db)):
    piece = _require_piece(piece_id, db)
    return piece_sync.piece_payload(db, piece, has_photo=piece_sync.get_photo(db, piece_id) is not None)


@router.get("/api/pieces/{piece_id}/intervals")
def list_intervals(piece_id: int, db: Session = Depends(get_db)):
    piece = _require_piece(piece_id, db)
    return intervals_sync.intervals_payload(db, piece)


class RepeatSpec(BaseModel):
    count: int = Field(..., ge=1, le=MAX_INTERVALS)
    work_distance_m: float | None = Field(None, gt=0)
    work_duration_s: float | None = Field(None, gt=0)
    rest_duration_s: float | None = Field(None, ge=0)


class AddIntervalsRequest(BaseModel):
    """Exactly one of: `repeat` (the 4x500m generator), `intervals` (append rows), or `replace`
    (the full ordered set — what edit mode saves)."""

    repeat: RepeatSpec | None = None
    intervals: list[IntervalIn] | None = Field(None, max_length=MAX_INTERVALS)
    replace: list[IntervalIn] | None = Field(None, max_length=MAX_INTERVALS)
    force: bool = False


@router.post("/api/pieces/{piece_id}/intervals")
def add_intervals(piece_id: int, body: AddIntervalsRequest, db: Session = Depends(get_db)):
    _require_piece(piece_id, db)
    chosen = [x for x in (body.repeat, body.intervals, body.replace) if x is not None]
    if len(chosen) != 1:
        raise HTTPException(status_code=422, detail="Give exactly one of repeat, intervals, or replace")
    try:
        if body.repeat is not None:
            r = body.repeat
            saved, validation = intervals_sync.add_repeats(
                db, piece_id, r.count, work_distance_m=r.work_distance_m, work_duration_s=r.work_duration_s, rest_duration_s=r.rest_duration_s, force=body.force
            )
        elif body.intervals is not None:
            saved, validation = intervals_sync.add_intervals(db, piece_id, [x.model_dump() for x in body.intervals], force=body.force)
        else:
            saved, validation = intervals_sync.replace_intervals(db, piece_id, [x.model_dump() for x in body.replace or []], force=body.force)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _intervals_response(db, piece_id, validation, saved)


class UpdateIntervalRequest(BaseModel):
    target_type: str | None = None
    work_distance_m: float | None = Field(None, ge=0)
    work_duration_s: float | None = Field(None, ge=0)
    rest_duration_s: float | None = Field(None, ge=0)
    avg_split_s: float | None = Field(None, ge=0)
    avg_watts: float | None = Field(None, ge=0)
    avg_rate: float | None = Field(None, ge=0)
    avg_hr: float | None = Field(None, ge=0)
    max_hr: float | None = Field(None, ge=0)
    calories: float | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=500)
    force: bool = False


@router.patch("/api/pieces/intervals/{interval_id}")
def update_interval(interval_id: int, body: UpdateIntervalRequest, db: Session = Depends(get_db)):
    # exclude_unset: an explicit null clears a field, an omitted one is left alone.
    patch = body.model_dump(exclude_unset=True, exclude={"force"})
    try:
        row, validation = intervals_sync.update_interval(db, interval_id, patch, force=body.force)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    piece_id = row.piece_id if row is not None else db.get(intervals_sync.PieceInterval, interval_id).piece_id
    return _intervals_response(db, piece_id, validation, row is not None)


@router.delete("/api/pieces/intervals/{interval_id}")
def delete_interval(interval_id: int, db: Session = Depends(get_db)):
    target = db.get(intervals_sync.PieceInterval, interval_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Interval not found")
    piece_id = target.piece_id
    intervals_sync.delete_interval(db, interval_id)
    return _intervals_response(db, piece_id, {"ok": True, "issues": []}, True)


class ReorderRequest(BaseModel):
    ids: list[int]


@router.put("/api/pieces/{piece_id}/intervals/order")
def reorder_intervals(piece_id: int, body: ReorderRequest, db: Session = Depends(get_db)):
    _require_piece(piece_id, db)
    try:
        intervals_sync.reorder_intervals(db, piece_id, body.ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _intervals_response(db, piece_id, {"ok": True, "issues": []}, True)
