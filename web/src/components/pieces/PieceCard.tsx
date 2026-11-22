import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, deletePiece, deletePiecePhoto, fetchPiecePhotoUrl, replaceIntervals, updatePiece, uploadPiecePhoto } from "../../lib/api";
import { formatDistance, formatDuration, formatSplit, splitUnitLabel } from "../../lib/format";
import { resizeImage } from "../../lib/image";
import { PIECE_MODALITIES, modalityLabel, rateUnit, type PieceModality } from "../../lib/pieceSplits";
import type { IntervalValidationIssue, Piece, PieceInterval, ZoneName } from "../../lib/types";
import { zoneColor, ZONE_NAMES } from "../../lib/zoneColors";
import { IntervalEditor } from "./IntervalEditor";
import { MassPower } from "./MassPower";
import { PieceIntervalTable } from "./PieceIntervalTable";
import { StackedBar } from "../charts/StackedBar";
import { SplitsReviewTable } from "./SplitsReviewTable";

/** One piece's summary on workout detail — task Part A.2/B.4 ("keep the photo attached ...
 * so I can check it later; delete option"). Editing re-runs the same validation the create
 * flow does, highlighting issues rather than silently accepting a bad edit. */
function PiecePhoto({ pieceId }: { pieceId: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    let made: string | null = null;
    fetchPiecePhotoUrl(pieceId).then((u) => {
      if (!live) {
        if (u) URL.revokeObjectURL(u);
        return;
      }
      made = u;
      setUrl(u);
      setFailed(u === null);
    });
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [pieceId]);
  if (failed) return <p className="text-xs text-text-secondary">The photo couldn't be loaded.</p>;
  if (!url) return <div className="h-24 w-full animate-pulse rounded-md border border-border bg-surface" aria-hidden />;
  return <img src={url} alt="PM5 screen" className="max-h-72 w-full rounded-md border border-border object-contain" />;
}

export function PieceCard({ piece, canonicalId }: { piece: Piece; canonicalId: number }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [splits, setSplits] = useState(piece.splits);
  const [validation, setValidation] = useState<{ ok: boolean; issues: { split_index: number | null; field: string; message: string }[] } | null>(null);
  const [showPhoto, setShowPhoto] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState<PieceInterval[]>(piece.intervals);
  const [ivIssues, setIvIssues] = useState<IntervalValidationIssue[] | null>(null);
  const [modality, setModality] = useState<PieceModality>(piece.modality ?? "rowing_erg");
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [photoVersion, setPhotoVersion] = useState(0);
  const photoInputRef = useRef<HTMLInputElement>(null);
  const unit = splitUnitLabel(piece.split_unit_m);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["pieces", canonicalId] });
    queryClient.invalidateQueries({ queryKey: ["workout", canonicalId] });
    queryClient.invalidateQueries({ queryKey: ["activity-samples", canonicalId] });
    queryClient.invalidateQueries({ queryKey: ["piece-test-detail", piece.id] });
    queryClient.invalidateQueries({ queryKey: ["interval-comparisons"] });
    queryClient.invalidateQueries({ queryKey: ["tests"] });
    queryClient.invalidateQueries({ queryKey: ["pbs"] });
  };

  const saveIntervals = async (force: boolean) => {
    setBusy(true);
    try {
      const result = await replaceIntervals(piece.id, rows, force);
      setIvIssues(result.validation.issues);
      if (result.saved) {
        setEditing(false);
        invalidate();
      }
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async (force: boolean) => {
    setBusy(true);
    try {
      const result = await updatePiece(piece.id, { splits, force, ...(modality !== piece.modality ? { modality } : {}) });
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
    setPhotoError(null);
    try {
      await deletePiecePhoto(piece.id);
      setShowPhoto(false);
      invalidate();
    } catch (e) {
      setPhotoError(e instanceof ApiError ? e.message : "Couldn't remove the photo — try again.");
    } finally {
      setBusy(false);
    }
  };

  // Session 33: add or replace the photo of a piece that already exists (there was no way to before).
  const choosePhoto = async (file: File) => {
    setBusy(true);
    setPhotoError(null);
    try {
      await uploadPiecePhoto(piece.id, await resizeImage(file));
      setPhotoVersion((v) => v + 1);
      setShowPhoto(true);
      invalidate();
    } catch (e) {
      setPhotoError(e instanceof ApiError ? e.message : "Couldn't save the photo — the piece is unchanged. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <span className="text-sm font-medium text-text-primary">{piece.has_intervals ? (piece.interval_signature ?? "Intervals") : piece.piece_type}</span>
          {piece.modality === "bike" && <span className="ml-2 rounded border border-border px-1.5 py-0.5 text-[11px] text-text-secondary">Bike</span>}
          <span className="ml-2 font-mono-nums text-xs text-text-tertiary">
            {formatDistance(piece.distance_m)} / {formatDuration(piece.duration_s)}
            {piece.has_intervals && " work"}
          </span>
        </div>
        {!piece.has_intervals && (
          <Link to={`/tests/piece/${piece.id}`} className="text-xs text-accent hover:underline">
            Pacing →
          </Link>
        )}
      </div>

      {!editing && piece.has_intervals ? (
        <>
          <div className="mt-3">
            <PieceIntervalTable intervals={piece.intervals} summary={piece.interval_summary} splitUnitM={piece.split_unit_m} modality={piece.modality} />
          </div>
          {piece.source === "concept2" && <p className="mt-2 text-xs text-text-tertiary">Imported from the Concept2 result's own interval data.</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                setRows(piece.intervals);
                setIvIssues(null);
                setEditing(true);
              }}
              className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary"
            >
              Edit intervals
            </button>
            <button type="button" disabled={busy} onClick={remove} className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary hover:border-band-red/40 hover:text-band-red-text disabled:opacity-50">
              Delete piece
            </button>
          </div>
        </>
      ) : editing && piece.has_intervals ? (
        <div className="mt-3 flex flex-col gap-3">
          <IntervalEditor rows={rows} onChange={setRows} canonicalId={canonicalId} issues={ivIssues ?? []} modality={piece.modality} />
          <div className="flex gap-2">
            <button type="button" onClick={() => setEditing(false)} className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary">
              Cancel
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => saveIntervals(ivIssues != null && ivIssues.length > 0)}
              className="min-h-9 flex-1 rounded-md border border-accent bg-accent px-3 text-xs font-medium text-accent-contrast disabled:opacity-50"
            >
              {ivIssues && ivIssues.length > 0 ? "Save anyway" : "Save"}
            </button>
          </div>
        </div>
      ) : !editing ? (
        <>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
            <div>
              <div className="text-text-tertiary">Avg split {unit}</div>
              <div className="font-mono-nums text-text-primary">{formatSplit(piece.avg_split_s)}</div>
            </div>
            <div>
              <div className="text-text-tertiary">{piece.modality === "bike" ? "Avg cadence" : "Avg rate"} ({rateUnit(piece.modality)})</div>
              <div className="font-mono-nums text-text-primary">{piece.avg_rate != null ? Math.round(piece.avg_rate) : "—"}</div>
            </div>
            <div>
              <div className="text-text-tertiary">Avg watts</div>
              <div className="font-mono-nums text-text-primary">{piece.avg_watts != null ? Math.round(piece.avg_watts) : "—"}</div>
            </div>
          </div>
          {piece.avg_watts_basis && (
            <p className="mt-1 text-center text-xs text-text-tertiary" data-testid="piece-watts-basis">
              {piece.avg_watts_basis === "pace" ? "Watts calculated from the average split." : piece.modality === "bike" ? "Watts as entered — a bike's power is never calculated from pace." : "Watts as entered."}
            </p>
          )}
          {!piece.has_intervals && (
            <div className="mt-2">
              <MassPower watts={piece.avg_watts} mass={piece} modality={piece.modality} compact />
            </div>
          )}
          {piece.source === "concept2" && <p className="mt-2 text-xs text-text-tertiary">Backed by real Concept2 stroke data.</p>}

          {/* Task Part D.2: per-split HR, time in zone, and post-piece recovery — not just
           * the three averages above. SplitsReviewTable's own readOnly mode already renders
           * each row's HR column, so it's reused here rather than duplicated. */}
          <div className="mt-3">
            <SplitsReviewTable splits={piece.splits} validation={null} readOnly modality={piece.modality} />
          </div>

          {piece.time_in_zone && Object.values(piece.time_in_zone).some((s) => s > 0) && (
            <div className="mt-3">
              <div className="text-xs text-text-tertiary">Time in zone</div>
              <StackedBar
                className="mt-1"
                legend
                segments={ZONE_NAMES.map((zone) => ({ key: zone, label: zone, value: piece.time_in_zone?.[zone] ?? 0, color: zoneColor(zone as ZoneName), detail: formatDuration(piece.time_in_zone?.[zone] ?? 0) }))}
              />
            </div>
          )}

          {piece.hr_recovery_bpm != null && (
            <p className="mt-2 text-xs text-text-tertiary">
              HR recovery after piece <span className="font-mono-nums text-text-primary">{Math.round(piece.hr_recovery_bpm)}</span> bpm
            </p>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => {
                // Re-seed from the current piece every time edit mode opens — otherwise a
                // discarded Cancel (or a re-align that refreshed derived HR since this
                // component last mounted) left stale local state that a later Save would
                // silently persist. The same bug AddPieceDialog's reopen effect already fixed.
                setSplits(piece.splits);
                setModality(piece.modality ?? "rowing_erg");
                setValidation(null);
                setEditing(true);
              }}
              className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary"
            >
              Edit splits
            </button>
            {piece.has_photo && (
              <button type="button" onClick={() => setShowPhoto((v) => !v)} className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary">
                {showPhoto ? "Hide photo" : "View photo"}
              </button>
            )}
            <button type="button" disabled={busy} onClick={() => photoInputRef.current?.click()} className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary disabled:opacity-50">
              {piece.has_photo ? "Replace photo" : "Add photo"}
            </button>
            <input
              ref={photoInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              aria-label={piece.has_photo ? "Replace photo" : "Add photo"}
              data-testid={`piece-photo-input-${piece.id}`}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void choosePhoto(file);
                e.target.value = "";
              }}
            />
            <button type="button" disabled={busy} onClick={remove} className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary hover:border-band-red/40 hover:text-band-red-text disabled:opacity-50">
              Delete piece
            </button>
          </div>
          {photoError && (
            <p role="alert" className="mt-2 text-xs text-band-red-text">
              {photoError}
            </p>
          )}
          {showPhoto && piece.has_photo && (
            <div className="mt-3">
              <PiecePhoto key={photoVersion} pieceId={piece.id} />
              <button type="button" disabled={busy} onClick={removePhoto} className="mt-2 min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary disabled:opacity-50">
                Remove photo
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="mt-3 flex flex-col gap-3">
          <div role="radiogroup" aria-label="Machine" className="grid grid-cols-2 gap-2">
            {PIECE_MODALITIES.map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={modality === m}
                onClick={() => setModality(m)}
                className={`min-h-9 rounded-md border text-xs font-medium ${modality === m ? "border-accent bg-accent/10 text-text-primary" : "border-border text-text-secondary"}`}
              >
                <span aria-hidden="true">{modality === m ? "● " : "○ "}</span>
                {modalityLabel(m)}
              </button>
            ))}
          </div>
          <SplitsReviewTable splits={splits} validation={validation} onChange={setSplits} modality={modality} />
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
