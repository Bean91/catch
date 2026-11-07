import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError, createPiece, estimatePiecePhoto, fetchCoachSettings, fetchPieceTemplate, fetchWorkouts, uploadPiecePhoto } from "../../lib/api";
import { resizeImage } from "../../lib/image";
import { parseSplitsPaste, validateSplits } from "../../lib/pieceSplits";
import { ERG_TEST_TYPES, type ErgTestType, type PieceSplitRow, type PieceValidation, type WorkoutListItem } from "../../lib/types";
import { formatDuration, formatShortDate } from "../../lib/format";
import { SplitsReviewTable } from "./SplitsReviewTable";
import { TimeInput } from "./TimeInput";

type Step = "pick-activity" | "choose-method" | "typed" | "photo" | "review" | "saving" | "saved";

/** Task Part A.2: "Add piece" button on any activity's detail page and in the test center,
 * with two input methods (photo, typed/pasted splits), both ending in the same editable
 * review table. `canonicalId` is omitted only from the test-center entry point, which shows
 * an activity picker first (the workout-detail entry point already knows it). */
export function AddPieceDialog({ open, onClose, canonicalId: fixedCanonicalId, onSaved }: { open: boolean; onClose: () => void; canonicalId?: number; onSaved: () => void }) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [canonicalId, setCanonicalId] = useState<number | null>(fixedCanonicalId ?? null);
  const [step, setStep] = useState<Step>(fixedCanonicalId ? "choose-method" : "pick-activity");
  const [pieceType, setPieceType] = useState<ErgTestType>("2000m");
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

  const coachSettings = useQuery({ queryKey: ["coach-settings"], queryFn: fetchCoachSettings, enabled: open });
  const photoAvailable = coachSettings.data?.anthropic_key.configured ?? false;
  const activitiesQuery = useQuery({ queryKey: ["workouts", "piece-picker"], queryFn: () => fetchWorkouts({}), enabled: open && step === "pick-activity" });

  const reset = () => {
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
    setStep("choose-method");
  };

  const startTyped = async () => {
    setSource("manual");
    setStep("typed");
    const template = await fetchPieceTemplate(canonicalId!, pieceType);
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

  const onPhotoPicked = async (file: File) => {
    setError(null);
    setStep("photo");
    try {
      const resized = await resizeImage(file);
      setPendingPhoto(resized);
      const result = await estimatePiecePhoto(canonicalId!, resized);
      setSplits(result.splits);
      setDistanceM(result.distance_m);
      setDurationS(result.duration_s);
      setVisionNotes(result.notes);
      setValidation(result.validation);
      setSource("photo");
      setStep("review");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't read that photo — try again or enter the splits manually.");
      setStep("choose-method");
    }
  };

  const goToReview = () => {
    setValidation(validateSplits(splits, distanceM, durationS));
    setStep("review");
  };

  const save = async (force: boolean) => {
    if (canonicalId == null) return;
    setStep("saving");
    setError(null);
    try {
      const result = await createPiece(canonicalId, {
        piece_type: pieceType,
        splits,
        distance_m: distanceM,
        duration_s: durationS,
        source,
        force,
      });
      setValidation(result.validation);
      if (!result.piece) {
        setStep("review"); // issues present, not forced — let the athlete fix or force-save
        return;
      }
      if (source === "photo" && pendingPhoto) {
        await uploadPiecePhoto(result.piece.id, pendingPhoto);
      }
      queryClient.invalidateQueries({ queryKey: ["pieces", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["tests"] });
      queryClient.invalidateQueries({ queryKey: ["pbs"] });
      setStep("saved");
      onSaved();
    } catch {
      setError("Couldn't save this piece — try again.");
      setStep("review");
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && close()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-30 max-h-[88vh] w-[min(94vw,560px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface p-5 shadow-xl focus:outline-none">
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
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-text-primary">Piece type</span>
                <select value={pieceType} onChange={(e) => setPieceType(e.target.value as ErgTestType)} className="min-h-11 rounded-md border border-border bg-bg px-3 text-sm text-text-primary">
                  {ERG_TEST_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>

              {error && <p className="text-sm text-band-red-text">{error}</p>}

              {photoAvailable && (
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
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

              <SplitsReviewTable splits={splits} validation={null} onChange={setSplits} />

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
              {visionNotes && <p className="rounded-md bg-surface-2 p-2 text-xs text-text-tertiary">{visionNotes}</p>}
              <SplitsReviewTable splits={splits} validation={validation} onChange={setSplits} />
              {error && <p className="text-sm text-band-red-text">{error}</p>}
              <div className="flex gap-2">
                <button type="button" onClick={() => setStep(source === "photo" ? "choose-method" : "typed")} className="min-h-11 rounded-md border border-border px-3 text-sm font-medium text-text-primary">
                  Back
                </button>
                <button
                  type="button"
                  onClick={() => save(!(validation?.ok ?? true))}
                  className="min-h-11 flex-1 rounded-md border border-accent bg-accent text-sm font-medium text-accent-contrast"
                >
                  {validation && !validation.ok ? "Save anyway" : "Save piece"}
                </button>
              </div>
            </div>
          )}

          {step === "saving" && <div className="mt-6 py-8 text-center text-sm text-text-tertiary">Saving…</div>}

          {step === "saved" && (
            <div className="mt-6 flex flex-col gap-3 py-4 text-center">
              <p className="text-sm text-text-primary">Piece saved.</p>
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
