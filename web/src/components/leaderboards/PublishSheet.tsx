import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { previewLbPublication, publishLbResult } from "../../lib/api";
import { PRECISION_LABEL, VERIFICATION_MEANING } from "../../lib/leaderboards";
import type { LbDatePrecision, LbPrefs, LbPreview, LbResult, LbState } from "../../lib/types";
import { EntryRow } from "./EntryRow";
import { VerificationBadge } from "./VerificationBadge";

const inputCls = "min-h-11 w-full rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary";
type Step = "meaning" | "choices" | "preview" | "done";

/** Publishing is three steps and an explicit confirm: what verification means, what you choose to show, and a preview rendered by the
 *  server from exactly the fields that would be public. The confirm sends the preview's hash, so what you saw is what is published. */
export function PublishSheet({ result, state, open, onOpenChange }: { result: LbResult; state: LbState; open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>("meaning");
  const [precision, setPrecision] = useState<LbDatePrecision>(state.settings.date_precision);
  const [showAge, setShowAge] = useState(state.settings.show_age_band);
  const [showWeight, setShowWeight] = useState(state.settings.show_weight_class);
  const [note, setNote] = useState("");
  const [notePublic, setNotePublic] = useState(false);
  const [preview, setPreview] = useState<LbPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const prefs: LbPrefs = { date_precision: precision, show_age_band: showAge, show_weight_class: showWeight, note: note.trim() || null, note_public: notePublic };

  const makePreview = useMutation({
    mutationFn: () => previewLbPublication(result.ref, prefs),
    onSuccess: (p) => {
      setPreview(p);
      setError(null);
      setStep("preview");
    },
    onError: (e: Error) => setError(e.message),
  });
  const publish = useMutation({
    mutationFn: () => publishLbResult(result.ref, prefs, preview!.preview_hash),
    onSuccess: () => {
      setError(null);
      setStep("done");
      queryClient.invalidateQueries({ queryKey: ["lb-results"] });
      queryClient.invalidateQueries({ queryKey: ["lb-me"] });
      queryClient.invalidateQueries({ queryKey: ["lb-board"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  function close(next: boolean) {
    if (!next) {
      setStep("meaning");
      setPreview(null);
      setError(null);
      makePreview.reset();
      publish.reset();
    }
    onOpenChange(next);
  }

  return (
    <Dialog.Root open={open} onOpenChange={close}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          data-testid="publish-sheet"
          className="fixed inset-x-0 bottom-0 z-30 max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,520px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border"
        >
          <Dialog.Title className="text-base font-semibold text-text-primary">Publish {result.board_label} · {result.result}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            {step === "meaning" && "First, what this result's status means."}
            {step === "choices" && "Choose what other signed-in Catch users can see."}
            {step === "preview" && "This is exactly what will be public. Nothing else about you or your training is shared."}
            {step === "done" && "Published."}
          </Dialog.Description>

          {step === "meaning" && (
            <div className="mt-4 flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <VerificationBadge state={result.verification} />
                <span className="text-sm text-text-secondary">{result.verification === "verified" ? "Eligible to be ranked" : "Listed separately, never ranked above verified results"}</span>
              </div>
              <p data-testid="verification-meaning" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">
                {VERIFICATION_MEANING[result.verification]}
              </p>
              <p className="text-xs text-text-tertiary">“Verified” means the source can be authenticated. It is not a guarantee of identity, equipment or physical condition.</p>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => close(false)} className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-secondary">
                  Cancel
                </button>
                <button type="button" onClick={() => setStep("choices")} data-testid="publish-next" className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-white">
                  Continue
                </button>
              </div>
            </div>
          )}

          {step === "choices" && (
            <form
              className="mt-4 flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                makePreview.mutate();
              }}
            >
              <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
                How much of the date to show
                <select value={precision} onChange={(e) => setPrecision(e.target.value as LbDatePrecision)} className={inputCls} data-testid="publish-precision">
                  {state.date_precisions.map((p) => (
                    <option key={p} value={p}>
                      {PRECISION_LABEL[p]}
                    </option>
                  ))}
                </select>
                <span className="text-xs text-text-tertiary">Under 18, the date is limited to the year.</span>
              </label>
              <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
                <input type="checkbox" checked={showAge} onChange={(e) => setShowAge(e.target.checked)} className="h-5 w-5" data-testid="publish-age" /> Show my age category
              </label>
              <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
                <input type="checkbox" checked={showWeight} onChange={(e) => setShowWeight(e.target.checked)} className="h-5 w-5" data-testid="publish-weight" /> Show the weight class Concept2 recorded
              </label>
              <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
                Note (optional, up to 140 characters, no links)
                <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={140} className={inputCls} data-testid="publish-note" />
              </label>
              <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
                <input type="checkbox" checked={notePublic} onChange={(e) => setNotePublic(e.target.checked)} className="h-5 w-5" /> Make the note public
              </label>
              {error && (
                <p role="alert" data-testid="publish-error" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">
                  {error}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setStep("meaning")} className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-secondary">
                  Back
                </button>
                <button type="submit" disabled={makePreview.isPending} data-testid="publish-preview" className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50">
                  {makePreview.isPending ? "Building preview…" : "Preview"}
                </button>
              </div>
            </form>
          )}

          {step === "preview" && preview && (
            <div className="mt-4 flex flex-col gap-3">
              <ul data-testid="publish-preview-entry" className="flex flex-col gap-2">
                <EntryRow entry={preview.entry} />
              </ul>
              <ul className="list-disc pl-5 text-sm text-text-secondary">
                {preview.disclosures.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
              {error && (
                <p role="alert" data-testid="publish-error" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">
                  {error}
                </p>
              )}
              <div className="flex flex-wrap justify-end gap-2">
                <button type="button" onClick={() => setStep("choices")} className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-secondary">
                  Change choices
                </button>
                <button type="button" onClick={() => publish.mutate()} disabled={publish.isPending} data-testid="publish-confirm" className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:opacity-50">
                  {publish.isPending ? "Publishing…" : "Publish this result"}
                </button>
              </div>
            </div>
          )}

          {step === "done" && (
            <div className="mt-4 flex flex-col gap-3">
              <p role="status" data-testid="publish-done" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">
                Your result is public. You can take it down any time in Settings → Leaderboards.
              </p>
              <button type="button" onClick={() => close(false)} className="min-h-11 self-end rounded-md border border-border px-4 text-sm font-medium text-text-secondary">
                Close
              </button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
