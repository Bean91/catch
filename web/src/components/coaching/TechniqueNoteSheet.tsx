import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createTechniqueNote, deleteTechniqueNote, updateTechniqueNote } from "../../lib/api";
import type { MediaRef, NoteVisibility, TechniqueCategory, TechniqueNote } from "../../lib/types";
import { NOT_MEASURED, TECHNIQUE_CATEGORIES } from "./labels";

const inputCls = "min-h-11 w-full min-w-0 rounded-md border border-border bg-bg px-3 text-sm text-text-primary";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="text-text-secondary">{label}</span>
      {children}
    </label>
  );
}

export function invalidateNotes(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["technique-notes"] });
}

export function TechniqueNoteSheet({
  open,
  onOpenChange,
  existing,
  canonicalId,
  pieces,
  defaultDate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing: TechniqueNote | null;
  canonicalId?: number | null;
  pieces?: { id: number; label: string }[];
  defaultDate?: string | null;
}) {
  const qc = useQueryClient();
  const [category, setCategory] = useState<TechniqueCategory>("catch");
  const [text, setText] = useState("");
  const [visibility, setVisibility] = useState<NoteVisibility>("private");
  const [pieceId, setPieceId] = useState<number | "">("");
  const [date, setDate] = useState("");
  const [media, setMedia] = useState<MediaRef[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmDelete(false);
    setCategory(existing?.category ?? "catch");
    setText(existing?.text ?? "");
    setVisibility(existing?.visibility ?? "private");
    setPieceId(existing?.piece?.id ?? "");
    setDate(existing?.date ?? defaultDate ?? "");
    setMedia(existing?.media ?? []);
  }, [open, existing, defaultDate]);

  const body = () => ({
    category,
    text: text.trim(),
    visibility,
    date: date || null,
    media: media.filter((m) => m.url.trim()).map((m) => ({ url: m.url.trim(), label: m.label.trim() })),
    ...(existing ? {} : { canonical_id: canonicalId ?? null }),
    ...(pieceId !== "" ? { piece_id: Number(pieceId) } : {}),
  });
  const save = useMutation({
    mutationFn: () => (existing ? updateTechniqueNote(existing.id, body()) : createTechniqueNote(body())),
    onSuccess: () => {
      invalidateNotes(qc);
      onOpenChange(false);
    },
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: () => deleteTechniqueNote(existing!.id),
    onSuccess: () => {
      invalidateNotes(qc);
      onOpenChange(false);
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          data-testid="note-sheet"
          className="fixed inset-x-0 bottom-0 z-30 max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,460px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border"
        >
          <Dialog.Title className="text-base font-semibold text-text-primary">{existing ? "Edit technique note" : "Add a technique note"}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">{NOT_MEASURED}</Dialog.Description>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <Field label="Category">
              <select value={category} onChange={(e) => setCategory(e.target.value as TechniqueCategory)} className={inputCls}>
                {TECHNIQUE_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Date (optional)">
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`${inputCls} overflow-hidden`} />
            </Field>
            {pieces && pieces.length > 0 && (
              <div className="col-span-2">
                <Field label="Piece (optional)">
                  <select value={pieceId} onChange={(e) => setPieceId(e.target.value === "" ? "" : Number(e.target.value))} className={inputCls}>
                    <option value="">The whole workout</option>
                    {pieces.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            )}
            <div className="col-span-2">
              <Field label="Your note">
                <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} className={`${inputCls} py-2`} placeholder="What you noticed, in your own words" />
              </Field>
            </div>
            <fieldset className="col-span-2">
              <legend className="mb-1 text-sm text-text-secondary">Who can see this</legend>
              <div role="radiogroup" aria-label="Who can see this" className="grid gap-2">
                {(
                  [
                    ["private", "Private — only you", "Never sent to a coach."],
                    ["coach", "Share with my coach", "A linked coach can read it."],
                  ] as const
                ).map(([value, label, hint]) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={visibility === value}
                    onClick={() => setVisibility(value)}
                    className={`min-h-11 rounded-md border px-3 py-2 text-left text-sm ${
                      visibility === value ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"
                    }`}
                  >
                    <span className="block font-medium">{label}</span>
                    <span className="block text-xs opacity-80">{hint}</span>
                  </button>
                ))}
              </div>
            </fieldset>
            <div className="col-span-2 flex flex-col gap-2">
              <span className="text-sm text-text-secondary">Links (optional)</span>
              {media.map((m, i) => (
                <div key={i} className="grid grid-cols-[1fr_auto] gap-2">
                  <input value={m.url} onChange={(e) => setMedia(media.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)))} placeholder="https://…" aria-label={`Link ${i + 1} address`} className={inputCls} inputMode="url" />
                  <button type="button" aria-label={`Remove link ${i + 1}`} onClick={() => setMedia(media.filter((_, j) => j !== i))} className="min-h-11 min-w-11 rounded-md border border-border text-text-secondary">
                    ×
                  </button>
                  <input value={m.label} onChange={(e) => setMedia(media.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} placeholder="Label" aria-label={`Link ${i + 1} label`} className={`${inputCls} col-span-2`} />
                </div>
              ))}
              {media.length < 5 && (
                <button type="button" onClick={() => setMedia([...media, { url: "", label: "" }])} className="min-h-11 self-start rounded-md border border-border px-3 text-sm text-text-secondary">
                  + Add a link
                </button>
              )}
            </div>
          </div>
          {error && (
            <p role="alert" className="mt-3 text-sm text-text-secondary">
              {error}
            </p>
          )}
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => save.mutate()} disabled={save.isPending || !text.trim()} className="min-h-11 flex-1 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-60">
              {save.isPending ? "Saving…" : existing ? "Save changes" : "Save note"}
            </button>
            <Dialog.Close className="min-h-11 rounded-md border border-border px-4 text-sm text-text-secondary">Cancel</Dialog.Close>
            {existing && !confirmDelete && (
              <button type="button" onClick={() => setConfirmDelete(true)} className="min-h-11 rounded-md px-3 text-sm text-text-tertiary underline">
                Delete note
              </button>
            )}
            {existing && confirmDelete && (
              <div className="flex w-full items-center gap-2 rounded-md border border-border p-2 text-sm">
                <span className="flex-1 text-text-secondary">Delete this note?</span>
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
