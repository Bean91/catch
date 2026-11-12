import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createFeedback, deleteFeedback, updateFeedback } from "../../lib/api";
import { todayISO } from "../../lib/dates";
import type { FeedbackEntry, FeedbackVisibility, FocusArea } from "../../lib/types";
import { FOCUS_AREAS } from "./labels";

const inputCls = "min-h-11 w-full min-w-0 rounded-md border border-border bg-bg px-3 text-sm text-text-primary";

export function invalidateFeedback(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["coach-feedback"] });
}

// For feedback the athlete logs themselves (what their coach said, or their own reflection). A
// coach's own entries are never editable here — the API refuses it and the card shows no Edit.
export function FeedbackSheet({ open, onOpenChange, existing }: { open: boolean; onOpenChange: (open: boolean) => void; existing: FeedbackEntry | null }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [coach, setCoach] = useState("");
  const [date, setDate] = useState(todayISO());
  const [focus, setFocus] = useState<FocusArea[]>([]);
  const [visibility, setVisibility] = useState<FeedbackVisibility>("shared");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmDelete(false);
    setText(existing?.text ?? "");
    setCoach(existing?.coach_name ?? "");
    setDate(existing?.date ?? todayISO());
    setFocus(existing?.focus_areas ?? []);
    setVisibility(existing?.visibility ?? "shared");
  }, [open, existing]);

  const save = useMutation({
    mutationFn: () =>
      existing
        ? updateFeedback(existing.id, { text: text.trim(), date, focus_areas: focus, visibility })
        : createFeedback({ text: text.trim(), date, focus_areas: focus, visibility, coach_name: coach.trim() || null }),
    onSuccess: () => {
      invalidateFeedback(qc);
      onOpenChange(false);
    },
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: () => deleteFeedback(existing!.id),
    onSuccess: () => {
      invalidateFeedback(qc);
      onOpenChange(false);
    },
    onError: (e: Error) => setError(e.message),
  });
  const toggle = (f: FocusArea) => setFocus((c) => (c.includes(f) ? c.filter((x) => x !== f) : [...c, f]));

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          data-testid="feedback-sheet"
          className="fixed inset-x-0 bottom-0 z-30 max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,460px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border"
        >
          <Dialog.Title className="text-base font-semibold text-text-primary">{existing ? "Edit your feedback entry" : "Log feedback"}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            Record feedback you received, or a reflection of your own. Entries written by your coach can't be changed here.
          </Dialog.Description>
          <div className="mt-4 grid grid-cols-2 gap-3">
            {!existing && (
              <label className="col-span-2 flex flex-col gap-1 text-sm">
                <span className="text-text-secondary">From which coach? (optional)</span>
                <input value={coach} onChange={(e) => setCoach(e.target.value)} className={inputCls} placeholder="Coach name" />
              </label>
            )}
            <label className="col-span-2 flex flex-col gap-1 text-sm">
              <span className="text-text-secondary">Date</span>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`${inputCls} overflow-hidden`} />
            </label>
            <label className="col-span-2 flex flex-col gap-1 text-sm">
              <span className="text-text-secondary">Feedback</span>
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} className={`${inputCls} py-2`} />
            </label>
            <fieldset className="col-span-2">
              <legend className="mb-1 text-sm text-text-secondary">Focus areas</legend>
              <div className="flex flex-wrap gap-2">
                {FOCUS_AREAS.map((f) => (
                  <button
                    key={f.value}
                    type="button"
                    aria-pressed={focus.includes(f.value)}
                    onClick={() => toggle(f.value)}
                    className={`min-h-11 rounded-full border px-3 text-sm ${focus.includes(f.value) ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"}`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </fieldset>
            <fieldset className="col-span-2">
              <legend className="mb-1 text-sm text-text-secondary">Who can see this</legend>
              <div role="radiogroup" aria-label="Who can see this" className="grid gap-2">
                {(
                  [
                    ["shared", "Shared with coach", "A linked coach can read it."],
                    ["private", "Private — only you", "Never sent to a coach."],
                  ] as const
                ).map(([value, label, hint]) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={visibility === value}
                    onClick={() => setVisibility(value)}
                    className={`min-h-11 rounded-md border px-3 py-2 text-left text-sm ${visibility === value ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"}`}
                  >
                    <span className="block font-medium">{label}</span>
                    <span className="block text-xs opacity-80">{hint}</span>
                  </button>
                ))}
              </div>
            </fieldset>
          </div>
          {error && (
            <p role="alert" className="mt-3 text-sm text-text-secondary">
              {error}
            </p>
          )}
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => save.mutate()} disabled={save.isPending || !text.trim()} className="min-h-11 flex-1 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-60">
              {save.isPending ? "Saving…" : existing ? "Save changes" : "Save entry"}
            </button>
            <Dialog.Close className="min-h-11 rounded-md border border-border px-4 text-sm text-text-secondary">Cancel</Dialog.Close>
            {existing && !confirmDelete && (
              <button type="button" onClick={() => setConfirmDelete(true)} className="min-h-11 rounded-md px-3 text-sm text-text-tertiary underline">
                Delete entry
              </button>
            )}
            {existing && confirmDelete && (
              <div className="flex w-full items-center gap-2 rounded-md border border-border p-2 text-sm">
                <span className="flex-1 text-text-secondary">Delete this entry? Its edit history is kept.</span>
                <button type="button" onClick={() => remove.mutate()} disabled={remove.isPending} className="min-h-11 rounded-md border border-border px-3 text-text-primary">
                  Delete
                </button>
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
