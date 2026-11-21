import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useVisionAvailable } from "../../lib/useVisionAvailable";
import { ApiError, createPiece, createPieceWithPhoto, estimatePiecePhoto, fetchPieceTemplate, fetchWorkouts } from "../../lib/api";
import { resizeImage } from "../../lib/image";
import { pickNativePhoto } from "../../lib/native/camera";
import { isNative } from "../../lib/native/platform";
import { PIECE_MODALITIES, PIECE_TYPES_BY_MODALITY, modalityLabel, parseSplitsPaste, validateSplits, type PieceModality } from "../../lib/pieceSplits";
import { type ErgTestType, type IntervalValidationIssue, type PieceInterval, type PieceSplitRow, type PieceValidation, type WorkoutListItem } from "../../lib/types";
import { formatDuration, formatShortDate } from "../../lib/format";
import { IntervalEditor } from "./IntervalEditor";
import { SplitsReviewTable } from "./SplitsReviewTable";
import { TimeInput } from "./TimeInput";

type Step = "pick-activity" | "choose-method" | "typed" | "photo" | "review" | "intervals" | "saving" | "saved";

/** Task Part A.2: "Add piece" button on any activity's detail page and in the test center,
 * with two input methods (photo, typed/pasted splits), both ending in the same editable
 * review table. `canonicalId` is omitted only from the test-center entry point, which shows
 * an activity picker first (the workout-detail entry point already knows it). */
export function AddPieceDialog({
  open,
  onClose,
  canonicalId: fixedCanonicalId,
  defaultModality = "rowing_erg",
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  canonicalId?: number;
  /** Session 33: a cycling workout's piece starts as a bike piece. */
  defaultModality?: PieceModality;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [canonicalId, setCanonicalId] = useState<number | null>(fixedCanonicalId ?? null);
  const [step, setStep] = useState<Step>(fixedCanonicalId ? "choose-method" : "pick-activity");
  const [modality, setModality] = useState<PieceModality>(defaultModality);
  const [pieceType, setPieceType] = useState<ErgTestType>("2000m");
  const [dragFactor, setDragFactor] = useState<number | null>(null);
  const [avgRate, setAvgRate] = useState<number | null>(null);
  const [avgWatts, setAvgWatts] = useState<number | null>(null);
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [splits, setSplits] = useState<PieceSplitRow[]>([]);
  const [distanceM, setDistanceM] = useState<number | null>(null);
  const [durationS, setDurationS] = useState<number | null>(null);
  const [pasteText, setPasteText] = useState("");
  const [pasteError, setPasteError] = useState<string | null>(null);
  const [source, setSource] = useState<"manual" | "photo">("manual");
  const [pendingPhoto, setPendingPhoto] = useState<Blob | null>(null);
  const [visionNotes, setVisionNotes] = useState("");
  const [validation, setValidation] = useState<PieceValidation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [intervalRows, setIntervalRows] = useState<PieceInterval[]>([]);
  const [intervalIssues, setIntervalIssues] = useState<IntervalValidationIssue[]>([]);

  const photoAvailable = useVisionAvailable(open);
  const activitiesQuery = useQuery({ queryKey: ["workouts", "piece-picker"], queryFn: () => fetchWorkouts({}), enabled: open && step === "pick-activity" });

  const reset = () => {
    setModality(defaultModality);
    setDragFactor(null);
    setAvgRate(null);
    setAvgWatts(null);
    setPhotoUrl((url) => {
      if (url) URL.revokeObjectURL(url);
      return null;
    });
    setWarnings([]);
    setCanonicalId(fixedCanonicalId ?? null);
    setStep(fixedCanonicalId ? "choose-method" : "pick-activity");
    setSplits([]);
    setDistanceM(null);
    setDurationS(null);
    setPasteText("");
    setPasteError(null);
    setSource("manual");
    setPendingPhoto(null);
    setVisionNotes("");
    setValidation(null);
    setError(null);
    setIntervalRows([]);
    setIntervalIssues([]);
  };

  // Radix's Dialog.Content unmounts its own subtree when `open` goes false, but this
  // component's own state doesn't — `AddPieceDialog` itself is never unmounted by its
  // parent, so without this a second "Add piece" would reopen straight onto the previous
  // open's "Piece saved" screen (the parent closes the dialog via the `open` prop, not via
  // Radix's own onOpenChange, which is the only place `close()`/`reset()` otherwise run). A
  // real bug an advisor review caught by adding a second piece in a row.
  useEffect(() => {
    if (open) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const close = () => {
    onClose();
    reset();
  };

  const pickActivity = (w: WorkoutListItem) => {
    setCanonicalId(w.id);
    setModality(w.sport_family === "cycling" ? "bike" : "rowing_erg");
    setStep("choose-method");
  };

  const chooseModality = (m: PieceModality) => {
    setModality(m);
    if (!PIECE_TYPES_BY_MODALITY[m].includes(pieceType)) setPieceType("custom");
  };

  // The live check on review — the server re-validates on save and is the value of record.
  const liveValidation = useMemo(() => (step === "review" ? validateSplits(splits, distanceM, durationS, modality) : null), [step, splits, distanceM, durationS, modality]);
  const shownValidation = liveValidation ?? validation;

  const startTyped = async () => {
    setSource("manual");
    setStep("typed");
    const template = await fetchPieceTemplate(canonicalId!, pieceType, undefined, undefined, modality);
    setSplits(template);
    setDistanceM(null);
    setDurationS(null);
  };

  const applyPaste = () => {
    try {
      const parsed = parseSplitsPaste(pasteText);
      // Merge onto the existing template when the row count matches, so a standard piece
      // type's distances (500/1000/1500/2000m) survive a paste instead of coming back null
      // — a real bug an advisor review caught: a pasted 2k's distance_m ended up null,
      // silently dropping it out of every distance-keyed reader (PBs, predict, Part D.4's
      // absorb match). Mirrors catch/coach/tools.py's _parse_piece_free_text, which does the
      // same template-merge for the coach's add_piece free-text path.
      setSplits(parsed.length === splits.length ? splits.map((row, i) => ({ ...row, split_s: parsed[i].split_s, rate: parsed[i].rate ?? row.rate })) : parsed);
      setPasteError(null);
    } catch (e) {
      setPasteError(e instanceof Error ? e.message : "Couldn't parse that.");
    }
  };

  const choosePhoto = async () => {
    if (!isNative()) return fileInputRef.current?.click();
    try {
      const file = await pickNativePhoto();
      if (file) void onPhotoPicked(file);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't open the camera.");
    }
  };

  const onPhotoPicked = async (file: File) => {
    setError(null);
    setStep("photo");
    try {
      const resized = await resizeImage(file);
      setPendingPhoto(resized);
      setPhotoUrl((url) => {
        if (url) URL.revokeObjectURL(url);
        return URL.createObjectURL(resized);
      });
      const result = await estimatePiecePhoto(canonicalId!, resized, modality);
      setSplits(result.splits);
      setDistanceM(result.distance_m);
      setDurationS(result.duration_s);
      setAvgRate(result.avg_rate);
      setAvgWatts(result.avg_watts);
      setDragFactor(result.drag_factor);
      // The screen's totals suggest a type; the athlete confirms it on review (it used to keep whatever was picked before the photo).
      if (result.detected_piece_type && PIECE_TYPES_BY_MODALITY[modality].includes(result.detected_piece_type)) setPieceType(result.detected_piece_type);
      else if (result.distance_m || result.duration_s) setPieceType("custom");
      setVisionNotes(result.notes);
      setValidation(result.validation);
      setSource("photo");
      setStep("review");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't read that photo — try again or enter the splits manually.");
      setStep("choose-method");
    }
  };

  // The server's interval validation returns `index`, the splits one `split_index` — one
  // normalising step so the editor highlights the right row either way.
  const saveIntervals = async (force: boolean) => {
    if (canonicalId == null) return;
    setStep("saving");
    setError(null);
    try {
      const result = await createPiece(canonicalId, { piece_type: "custom", splits: [], intervals: intervalRows, force, modality });
      if (!result.piece) {
        setIntervalIssues(result.validation.issues.map((i) => ({ index: (i as { index?: number | null }).index ?? i.split_index, field: i.field, message: i.message })));
        setStep("intervals");
        return;
      }
      queryClient.invalidateQueries({ queryKey: ["pieces", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["workout", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["interval-comparisons"] });
      setStep("saved");
      onSaved();
    } catch {
      setError("Couldn't save these intervals — try again.");
      setStep("intervals");
    }
  };

  const goToReview = () => {
    setValidation(validateSplits(splits, distanceM, durationS, modality));
    setStep("review");
  };

  const save = async (force: boolean) => {
    if (canonicalId == null) return;
    setStep("saving");
    setError(null);
    const body = {
      piece_type: pieceType,
      modality,
      splits,
      distance_m: distanceM,
      duration_s: durationS,
      drag_factor: dragFactor,
      avg_rate: splits.length ? null : avgRate,
      avg_watts: splits.length ? null : avgWatts,
      source,
      force,
    };
    try {
      // One request: with a photo, the piece and the photo are saved together or not at all, so a retry can never duplicate.
      const result = source === "photo" && pendingPhoto ? await createPieceWithPhoto(canonicalId, body, pendingPhoto) : await createPiece(canonicalId, body);
      setValidation(result.validation);
      if (!result.piece) {
        setStep("review"); // issues present, not forced — let the athlete fix or force-save
        return;
      }
      setWarnings(result.validation.warnings ?? []);
      queryClient.invalidateQueries({ queryKey: ["pieces", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["workout", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["tests"] });
      queryClient.invalidateQueries({ queryKey: ["pbs"] });
      setStep("saved");
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.message} Nothing was saved.` : "Couldn't save this piece — nothing was saved. Try again.");
      setStep("review");
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && close()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-30 max-h-[88dvh] w-[min(94vw,560px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface p-5 shadow-xl focus:outline-none">
          <Dialog.Title className="text-base font-semibold text-text-primary">Add piece</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-tertiary">A segment of this activity — a 2k inside a longer row, a 30r20, or a custom piece.</Dialog.Description>

          {step === "pick-activity" && (
            <div className="mt-4 flex flex-col gap-2">
              <p className="text-sm text-text-secondary">Which workout does this piece belong to?</p>
              {activitiesQuery.isLoading && <p className="text-sm text-text-tertiary">Loading recent workouts…</p>}
              <div className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
                {activitiesQuery.data?.items.map((w) => (
                  <button
                    key={w.id}
                    type="button"
                    onClick={() => pickActivity(w)}
                    className="flex min-h-11 items-center justify-between gap-2 rounded-md border border-border p-2.5 text-left transition-colors hover:border-accent/40"
                  >
                    <span className="text-sm text-text-primary">
                      {w.title ?? w.sport_family} — {w.start ? formatShortDate(w.start) : "—"}
                    </span>
                    <span className="font-mono-nums text-xs text-text-tertiary">{formatDuration(w.duration)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {step === "choose-method" && (
            <div className="mt-4 flex flex-col gap-4">
              <ModalityPicker value={modality} onChange={chooseModality} />
              <PieceTypeSelect modality={modality} value={pieceType} onChange={setPieceType} />

              {error && <p className="text-sm text-band-red-text">{error}</p>}

              {photoAvailable && (
                <button
                  type="button"
                  onClick={choosePhoto}
                  className="min-h-24 rounded-md border border-dashed border-border text-sm text-text-tertiary transition-colors hover:border-accent hover:text-text-secondary"
                >
                  Take or choose a photo of the PM5 screen
                </button>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                capture="environment"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onPhotoPicked(file);
                  e.target.value = "";
                }}
              />

              <button type="button" onClick={startTyped} className="min-h-11 rounded-md border border-border text-sm font-medium text-text-primary transition-colors hover:border-accent">
                Type or paste splits
              </button>
              <button type="button" onClick={() => setStep("intervals")} className="min-h-11 rounded-md border border-border text-sm font-medium text-text-primary transition-colors hover:border-accent">
                Intervals (4 × 500m, 8 × 1:00 …)
              </button>
            </div>
          )}

          {step === "photo" && <div className="mt-6 py-8 text-center text-sm text-text-tertiary">Reading the photo…</div>}

          {step === "typed" && (
            <div className="mt-4 flex flex-col gap-3">
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-text-primary">Paste splits</span>
                <textarea
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  placeholder="1:36.8 32 / 1:38.9 30 / 1:39.0 31 / 1:37.7 32"
                  rows={2}
                  className="rounded-md border border-border bg-bg p-2 text-base text-text-primary"
                />
                {pasteError && <span className="text-xs text-band-red-text">{pasteError}</span>}
                <button type="button" onClick={applyPaste} className="min-h-9 self-start rounded-md border border-border px-3 text-xs font-medium text-text-primary">
                  Apply paste
                </button>
              </label>

              <SplitsReviewTable splits={splits} validation={null} onChange={setSplits} modality={modality} />

              <div className="flex gap-3 text-sm">
                <label className="flex flex-1 flex-col gap-1">
                  <span className="text-xs text-text-tertiary">Total distance (m), if different</span>
                  <input type="number" inputMode="decimal" value={distanceM ?? ""} onChange={(e) => setDistanceM(e.target.value === "" ? null : Number(e.target.value))} className="min-h-9 rounded-md border border-border bg-bg px-2 text-base font-mono-nums text-text-primary" />
                </label>
                <label className="flex flex-1 flex-col gap-1">
                  <span className="text-xs text-text-tertiary">Total time, if different</span>
                  <TimeInput valueS={durationS} onChange={setDurationS} ariaLabel="Total time, if different" />
                </label>
              </div>

              <button type="button" onClick={goToReview} className="min-h-11 rounded-md bg-accent text-sm font-medium text-accent-contrast">
                Review
              </button>
            </div>
          )}

          {step === "review" && (
            <div className="mt-4 flex flex-col gap-3">
              {source === "photo" && photoUrl && (
                <img src={photoUrl} alt="The PM5 photo this piece was read from" className="max-h-48 w-full rounded-md border border-border object-contain" data-testid="piece-photo-preview" />
              )}
              {visionNotes && <p className="rounded-md bg-surface-2 p-2 text-xs text-text-tertiary">{visionNotes}</p>}
              <p className="text-xs text-text-secondary">
                {modalityLabel(modality)} piece{source === "photo" ? " — check the type and totals read from the photo" : ""}.
              </p>
              <PieceTypeSelect modality={modality} value={pieceType} onChange={setPieceType} />
              <div className="flex gap-3 text-sm">
                <label className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-xs text-text-tertiary">Total distance (m)</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    aria-label="Total distance (m)"
                    value={distanceM ?? ""}
                    onChange={(e) => setDistanceM(e.target.value === "" ? null : Number(e.target.value))}
                    className="min-h-9 rounded-md border border-border bg-bg px-2 text-base font-mono-nums text-text-primary"
                  />
                </label>
                <label className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-xs text-text-tertiary">Total time</span>
                  <TimeInput valueS={durationS} onChange={setDurationS} ariaLabel="Total time" />
                </label>
              </div>
              <SplitsReviewTable splits={splits} validation={shownValidation} onChange={setSplits} modality={modality} />
              {error && <p className="text-sm text-band-red-text">{error}</p>}
              <div className="flex gap-2">
                <button type="button" onClick={() => setStep(source === "photo" ? "choose-method" : "typed")} className="min-h-11 rounded-md border border-border px-3 text-sm font-medium text-text-primary">
                  Back
                </button>
                <button
                  type="button"
                  disabled={splits.length === 0 && distanceM == null && durationS == null}
                  onClick={() => save(!(shownValidation?.ok ?? true))}
                  className="min-h-11 flex-1 rounded-md border border-accent bg-accent text-sm font-medium text-accent-contrast disabled:opacity-50"
                >
                  {shownValidation && !shownValidation.ok ? "Save anyway" : "Save piece"}
                </button>
              </div>
            </div>
          )}

          {step === "intervals" && canonicalId != null && (
            <div className="mt-4 flex flex-col gap-3">
              <IntervalEditor rows={intervalRows} onChange={setIntervalRows} canonicalId={canonicalId} issues={intervalIssues} modality={modality} />
              {error && <p className="text-sm text-band-red-text">{error}</p>}
              <div className="flex gap-2">
                <button type="button" onClick={() => setStep("choose-method")} className="min-h-11 rounded-md border border-border px-3 text-sm font-medium text-text-primary">
                  Back
                </button>
                <button
                  type="button"
                  disabled={intervalRows.length === 0}
                  onClick={() => saveIntervals(intervalIssues.length > 0)}
                  className="min-h-11 flex-1 rounded-md border border-accent bg-accent text-sm font-medium text-accent-contrast disabled:opacity-50"
                >
                  {intervalIssues.length > 0 ? "Save anyway" : "Save intervals"}
                </button>
              </div>
            </div>
          )}

          {step === "saving" && <div className="mt-6 py-8 text-center text-sm text-text-tertiary">Saving…</div>}

          {step === "saved" && (
            <div className="mt-6 flex flex-col gap-3 py-4 text-center">
              <p className="text-sm text-text-primary" role="status">
                Piece saved{source === "photo" && pendingPhoto ? " with its photo" : ""}.
              </p>
              {warnings.map((w) => (
                <p key={w} className="text-xs text-text-tertiary">
                  {w}
                </p>
              ))}
              <button type="button" onClick={close} className="min-h-11 rounded-md bg-accent text-sm font-medium text-accent-contrast">
                Done
              </button>
            </div>
          )}

          {step !== "saved" && (
            <Dialog.Close asChild>
              <button type="button" onClick={close} className="mt-4 min-h-11 w-full rounded-md border border-border text-sm font-medium text-text-primary transition-colors hover:border-accent">
                Cancel
              </button>
            </Dialog.Close>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ModalityPicker({ value, onChange }: { value: PieceModality; onChange: (m: PieceModality) => void }) {
  return (
    <div role="radiogroup" aria-label="Machine" className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-text-primary">Machine</span>
      <div className="grid grid-cols-2 gap-2">
        {PIECE_MODALITIES.map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={value === m}
            onClick={() => onChange(m)}
            className={`min-h-11 rounded-md border text-sm font-medium ${value === m ? "border-accent bg-accent/10 text-text-primary" : "border-border text-text-secondary hover:border-accent/40"}`}
          >
            <span aria-hidden="true">{value === m ? "● " : "○ "}</span>
            {modalityLabel(m)} <span className="text-xs text-text-tertiary">{m === "bike" ? "/1000m" : "/500m"}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function PieceTypeSelect({ modality, value, onChange }: { modality: PieceModality; value: ErgTestType; onChange: (t: ErgTestType) => void }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-text-primary">Piece type</span>
      <select value={value} onChange={(e) => onChange(e.target.value as ErgTestType)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-sm text-text-primary">
        {PIECE_TYPES_BY_MODALITY[modality].map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
    </label>
  );
}
