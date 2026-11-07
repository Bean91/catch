import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { deletePiece, deletePiecePhoto, piecePhotoUrl, updatePiece } from "../../lib/api";
import { formatDistance, formatDuration, formatSplit } from "../../lib/format";
import type { Piece } from "../../lib/types";
import { SplitsReviewTable } from "./SplitsReviewTable";

/** One piece's summary on workout detail — task Part A.2/B.4 ("keep the photo attached ...
 * so I can check it later; delete option"). Editing re-runs the same validation the create
 * flow does, highlighting issues rather than silently accepting a bad edit. */
export function PieceCard({ piece, canonicalId }: { piece: Piece; canonicalId: number }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [splits, setSplits] = useState(piece.splits);
  const [validation, setValidation] = useState<{ ok: boolean; issues: { split_index: number | null; field: string; message: string }[] } | null>(null);
  const [showPhoto, setShowPhoto] = useState(false);
  const [busy, setBusy] = useState(false);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["pieces", canonicalId] });
    queryClient.invalidateQueries({ queryKey: ["workout", canonicalId] });
    queryClient.invalidateQueries({ queryKey: ["activity-samples", canonicalId] });
  };

  const saveEdit = async (force: boolean) => {
    setBusy(true);
    try {
      const result = await updatePiece(piece.id, { splits, force });
      setValidation(result.validation);
      if (result.piece) {
        setEditing(false);
        invalidate();
      }
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await deletePiece(piece.id);
      invalidate();
    } finally {
      setBusy(false);
    }
  };

  const removePhoto = async () => {
    setBusy(true);
    try {
      await deletePiecePhoto(piece.id);
      setShowPhoto(false);
      invalidate();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <span className="text-sm font-medium text-text-primary">{piece.piece_type}</span>
          <span className="ml-2 font-mono-nums text-xs text-text-tertiary">
            {formatDistance(piece.distance_m)} / {formatDuration(piece.duration_s)}
          </span>
        </div>
        <Link to={`/tests/piece/${piece.id}`} className="text-xs text-accent hover:underline">
          Pacing →
        </Link>
      </div>

      {!editing ? (
        <>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
            <div>
              <div className="text-text-tertiary">Avg split</div>
              <div className="font-mono-nums text-text-primary">{formatSplit(piece.avg_split_s)}</div>
            </div>
            <div>
              <div className="text-text-tertiary">Avg rate</div>
              <div className="font-mono-nums text-text-primary">{piece.avg_rate != null ? Math.round(piece.avg_rate) : "—"}</div>
            </div>
            <div>
              <div className="text-text-tertiary">Avg watts</div>
              <div className="font-mono-nums text-text-primary">{piece.avg_watts != null ? Math.round(piece.avg_watts) : "—"}</div>
            </div>
          </div>
          {piece.source === "concept2" && <p className="mt-2 text-xs text-text-tertiary">Backed by real Concept2 stroke data.</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => setEditing(true)} className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary">
              Edit splits
            </button>
            {piece.has_photo && (
              <button type="button" onClick={() => setShowPhoto((v) => !v)} className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary">
                {showPhoto ? "Hide photo" : "View photo"}
              </button>
            )}
            <button type="button" disabled={busy} onClick={remove} className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary hover:border-band-red/40 hover:text-band-red-text disabled:opacity-50">
              Delete piece
            </button>
          </div>
          {showPhoto && piece.has_photo && (
            <div className="mt-3">
              <img src={piecePhotoUrl(piece.id)} alt="PM5 screen" className="max-h-72 w-full rounded-md border border-border object-contain" />
              <button type="button" disabled={busy} onClick={removePhoto} className="mt-2 min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary disabled:opacity-50">
                Delete photo
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="mt-3 flex flex-col gap-3">
          <SplitsReviewTable splits={splits} validation={validation} onChange={setSplits} />
          <div className="flex gap-2">
            <button type="button" onClick={() => setEditing(false)} className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary">
              Cancel
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => saveEdit(!(validation?.ok ?? true))}
              className="min-h-9 flex-1 rounded-md border border-accent bg-accent px-3 text-xs font-medium text-accent-contrast disabled:opacity-50"
            >
              {validation && !validation.ok ? "Save anyway" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
