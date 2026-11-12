import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createEvent, deleteEvent, updateEvent } from "../../lib/api";
import type { EventInput, UpcomingEvent } from "../../lib/types";
import { EVENT_TYPES } from "./labels";
import { invalidateCalendar } from "./PlannedWorkoutSheet";

const inputCls = "min-h-11 w-full min-w-0 rounded-md border border-border bg-bg px-3 text-sm text-text-primary";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="text-text-secondary">{label}</span>
      {children}
    </label>
  );
}

export function EventSheet({
  open,
  onOpenChange,
  existing,
  defaultDate,
  onDeleted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing: UpcomingEvent | null;
  defaultDate: string;
  onDeleted?: () => void;
}) {
  const qc = useQueryClient();
  const [f, setF] = useState<EventInput>({ name: "", date: defaultDate, type: "race" });
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmDelete(false);
    setF(
      existing
        ? {
            name: existing.name, date: existing.date, type: existing.type, distance: existing.distance, priority: existing.priority,
            goal_time: existing.goal_time, location: existing.location, goals: existing.goals, notes: existing.notes, boat_class: existing.boat_class,
          }
        : { name: "", date: defaultDate, type: "race" },
    );
  }, [open, existing, defaultDate]);

  const set = (patch: Partial<EventInput>) => setF((c) => ({ ...c, ...patch }));
  const clean = (): EventInput => ({
    ...f,
    name: f.name.trim(),
    distance: f.distance?.trim() || null,
    goal_time: f.goal_time?.trim() || null,
    location: f.location?.trim() || null,
    goals: f.goals?.trim() || null,
    notes: f.notes?.trim() || null,
    priority: f.priority || null,
  });

  const save = useMutation({
    mutationFn: () => (existing ? updateEvent(existing.id, clean()) : createEvent(clean())),
    onSuccess: () => {
      invalidateCalendar(qc);
      qc.invalidateQueries({ queryKey: ["memory"] });
      qc.invalidateQueries({ queryKey: ["coach-memory"] });
      onOpenChange(false);
    },
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: () => deleteEvent(existing!.id),
    onSuccess: () => {
      invalidateCalendar(qc);
      qc.invalidateQueries({ queryKey: ["memory"] });
      qc.invalidateQueries({ queryKey: ["coach-memory"] });
      onOpenChange(false);
      onDeleted?.();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          data-testid="event-sheet"
          className="fixed inset-x-0 bottom-0 z-30 max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,460px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border"
        >
          <Dialog.Title className="text-base font-semibold text-text-primary">{existing ? "Edit event" : "Add an event"}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">A race, erg test, camp or selection.</Dialog.Description>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <Field label="Name">
                <input value={f.name} onChange={(e) => set({ name: e.target.value })} className={inputCls} />
              </Field>
            </div>
            <Field label="Date">
              <input type="date" value={f.date} onChange={(e) => set({ date: e.target.value })} className={`${inputCls} overflow-hidden`} />
            </Field>
            <Field label="Type">
              <select value={f.type} onChange={(e) => set({ type: e.target.value })} className={inputCls}>
                {EVENT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Importance">
              <select value={f.priority ?? ""} onChange={(e) => set({ priority: e.target.value || null })} className={inputCls}>
                <option value="">Not set</option>
                <option value="A">A race</option>
                <option value="B">B race</option>
                <option value="C">C race</option>
              </select>
            </Field>
            <Field label="Distance">
              <input value={f.distance ?? ""} onChange={(e) => set({ distance: e.target.value })} className={inputCls} placeholder="2000m" />
            </Field>
            <Field label="Goal time">
              <input value={f.goal_time ?? ""} onChange={(e) => set({ goal_time: e.target.value })} className={inputCls} placeholder="6:45.0" inputMode="text" />
            </Field>
            <Field label="Location">
              <input value={f.location ?? ""} onChange={(e) => set({ location: e.target.value })} className={inputCls} />
            </Field>
            <div className="col-span-2">
              <Field label="Goals">
                <textarea value={f.goals ?? ""} onChange={(e) => set({ goals: e.target.value })} rows={2} className={`${inputCls} py-2`} />
              </Field>
            </div>
            <div className="col-span-2">
              <Field label="Notes">
                <textarea value={f.notes ?? ""} onChange={(e) => set({ notes: e.target.value })} rows={2} className={`${inputCls} py-2`} />
              </Field>
            </div>
          </div>
          {error && (
            <p role="alert" className="mt-3 text-sm text-text-secondary">
              {error}
            </p>
          )}
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => save.mutate()} disabled={save.isPending || !f.name.trim()} className="min-h-11 flex-1 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-60">
              {save.isPending ? "Saving…" : existing ? "Save changes" : "Add event"}
            </button>
            <Dialog.Close className="min-h-11 rounded-md border border-border px-4 text-sm text-text-secondary">Cancel</Dialog.Close>
            {existing && !confirmDelete && (
              <button type="button" onClick={() => setConfirmDelete(true)} className="min-h-11 rounded-md px-3 text-sm text-text-tertiary underline">
                Delete event
              </button>
            )}
            {existing && confirmDelete && (
              <div className="flex w-full items-center gap-2 rounded-md border border-border p-2 text-sm">
                <span className="flex-1 text-text-secondary">Delete this event? Planned sessions stay; they just lose the link.</span>
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
