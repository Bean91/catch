from __future__ import annotations

"""Session 17 (see PLAN.md — the task called itself "session 13"): add-a-piece endpoints.
Two input methods (photo, typed/pasted splits) both end at the same POST .../pieces create
call with a plain splits list — the frontend's review table is what differs, not the save
path. A piece never silently "corrects" a bad reading (task Part B.3): create/update return
`{piece: null, validation}` when a check fails, unless the caller explicitly passes
`force=true` after the athlete has seen the issues and still wants to save as-is."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from catch.analytics.piece import PIECE_TYPES, default_splits, parse_splits_paste
from catch.api.deps import get_db, require_auth
from catch.coach.piece_vision import PieceVisionError, estimate_piece_photo
from catch.core.models import CanonicalActivity
from catch.sync import piece as piece_sync

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


class CreatePieceRequest(BaseModel):
    piece_type: str
    splits: list[PieceSplitRow]
    distance_m: float | None = None
    duration_s: float | None = None
    drag_factor: int | None = None
    source: str = "manual"
    notes: str | None = None
    force: bool = False


def _piece_response(piece, validation: dict) -> dict:
    return {
        "piece": piece_sync.piece_dict(piece, has_photo=False) if piece is not None else None,
        "validation": validation,
    }


@router.post("/api/activities/{canonical_id}/pieces")
def create_piece(canonical_id: int, body: CreatePieceRequest, db: Session = Depends(get_db)):
    _require_canonical(canonical_id, db)
    if body.piece_type not in PIECE_TYPES:
        raise HTTPException(status_code=422, detail=f"piece_type must be one of {PIECE_TYPES}")
    if body.source not in ("manual", "photo"):
        raise HTTPException(status_code=422, detail="source must be 'manual' or 'photo'")
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
    return _piece_response(piece, validation)


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
    return _piece_response(piece, validation)


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
