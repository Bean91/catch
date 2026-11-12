import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { approvePhase, createPhase, deletePhase, unapprovePhase, updatePhase } from "../../lib/api";
import type { PhaseInput, PhaseKind, PlanPhase } from "../../lib/types";
import { PHASE_KINDS, ZONES } from "./labels";
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

export function PhaseSheet({
  open,
  onOpenChange,
  existing,
  defaultStart,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing: PlanPhase | null;
  defaultStart: string;
}) {
  const qc = useQueryClient();
  const [kind, setKind] = useState<PhaseKind>("general_prep");
  const [name, setName] = useState("");
  const [start, setStart] = useState(defaultStart);
  const [end, setEnd] = useState(defaultStart);
  const [goals, setGoals] = useState("");
  const [minutes, setMinutes] = useState("");
  const [sessions, setSessions] = useState("");
  const [strength, setStrength] = useState("");
  const [zonePct, setZonePct] = useState<Record<string, { min?: string; max?: string }>>({});
  const [by, setBy] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmDelete(false);
    setBy(existing?.coach_approved_by ?? "");
    setNote(existing?.coach_approved_note ?? "");
    setKind(existing?.kind ?? "general_prep");
    setName(existing?.name ?? "");
    setStart(existing?.start_date ?? defaultStart);
    setEnd(existing?.end_date ?? defaultStart);
    setGoals(existing?.goals ?? "");
    setMinutes(existing?.target_minutes_per_week != null ? String(existing.target_minutes_per_week) : "");
    setSessions(existing?.target_sessions_per_week != null ? String(existing.target_sessions_per_week) : "");
    setStrength(existing?.target_strength_sessions_per_week != null ? String(existing.target_strength_sessions_per_week) : "");
    const zp: Record<string, { min?: string; max?: string }> = {};
    for (const [z, b] of Object.entries(existing?.target_zone_pct ?? {})) zp[z] = { min: b.min != null ? String(b.min) : "", max: b.max != null ? String(b.max) : "" };
    setZonePct(zp);
  }, [open, existing, defaultStart]);

  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const body = (): PhaseInput => {
    const target_zone_pct: Record<string, { min?: number; max?: number }> = {};
    for (const [z, b] of Object.entries(zonePct)) {
      const entry: { min?: number; max?: number } = {};
      if (b.min && b.min.trim() !== "") entry.min = Number(b.min);
      if (b.max && b.max.trim() !== "") entry.max = Number(b.max);
      if (Object.keys(entry).length) target_zone_pct[z] = entry;
    }
    return {
      kind, name: name.trim(), start_date: start, end_date: end, goals: goals.trim() || null,
      target_minutes_per_week: num(minutes), target_sessions_per_week: num(sessions), target_strength_sessions_per_week: num(strength),
      target_zone_pct: Object.keys(target_zone_pct).length ? target_zone_pct : null,
    };
  };

  const done = () => {
    invalidateCalendar(qc);
    onOpenChange(false);
  };
  const save = useMutation({
    mutationFn: () => (existing ? updatePhase(existing.id, body()) : createPhase(body())),
    onSuccess: done,
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({ mutationFn: () => deletePhase(existing!.id), onSuccess: done, onError: (e: Error) => setError(e.message) });
  const approve = useMutation({
    mutationFn: () => approvePhase(existing!.id, by.trim() || null, note.trim() || null),
    onSuccess: done,
    onError: (e: Error) => setError(e.message),
  });
  const unapprove = useMutation({ mutationFn: () => unapprovePhase(existing!.id), onSuccess: done, onError: (e: Error) => setError(e.message) });

  const setZone = (z: string, patch: { min?: string; max?: string }) => setZonePct((c) => ({ ...c, [z]: { ...c[z], ...patch } }));

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          data-testid="phase-sheet"
          className="fixed inset-x-0 bottom-0 z-30 max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,460px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border"
        >
          <Dialog.Title className="text-base font-semibold text-text-primary">{existing ? "Training phase" : "Add a training phase"}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            Phases set the shape of a block and its weekly targets. Nothing is generated for you.
          </Dialog.Description>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <Field label="Phase">
              <select value={kind} onChange={(e) => setKind(e.target.value as PhaseKind)} className={inputCls}>
                {PHASE_KINDS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Name">
              <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Starts">
              <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className={`${inputCls} overflow-hidden`} />
            </Field>
            <Field label="Ends">
              <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className={`${inputCls} overflow-hidden`} />
            </Field>
            <div className="col-span-2">
              <Field label="Goals">
                <textarea value={goals} onChange={(e) => setGoals(e.target.value)} rows={2} className={`${inputCls} py-2`} />
              </Field>
            </div>
            <Field label="Minutes / week">
              <input type="number" inputMode="decimal" min={0} value={minutes} onChange={(e) => setMinutes(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Sessions / week">
              <input type="number" inputMode="decimal" min={0} value={sessions} onChange={(e) => setSessions(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Strength sessions / week">
              <input type="number" inputMode="decimal" min={0} value={strength} onChange={(e) => setStrength(e.target.value)} className={inputCls} />
            </Field>
          </div>

          <fieldset className="mt-4">
            <legend className="text-sm font-medium text-text-primary">Intensity split targets (% of time, optional)</legend>
            <div className="mt-2 grid grid-cols-[3rem_1fr_1fr] items-end gap-2">
              <span />
              <span className="text-xs text-text-tertiary">At least</span>
              <span className="text-xs text-text-tertiary">At most</span>
              {ZONES.map((z) => (
                <div key={z} className="contents">
                  <span className="pb-3 text-sm text-text-secondary">{z}</span>
                  <input aria-label={`${z} at least`} type="number" min={0} max={100} value={zonePct[z]?.min ?? ""} onChange={(e) => setZone(z, { min: e.target.value })} className={inputCls} />
                  <input aria-label={`${z} at most`} type="number" min={0} max={100} value={zonePct[z]?.max ?? ""} onChange={(e) => setZone(z, { max: e.target.value })} className={inputCls} />
                </div>
              ))}
            </div>
          </fieldset>

          {existing && (
            <div className="mt-5 rounded-md border border-border p-3">
              <p className="text-sm font-medium text-text-primary">Coach approval</p>
              <p className="mt-1 text-xs text-text-tertiary">
                You record this yourself when a coach has looked at the plan. Editing the plan afterwards shows “edited since approval”.
              </p>
              {existing.coach_approved ? (
                <div className="mt-3 flex flex-col gap-2 text-sm text-text-secondary">
                  <span>
                    Approved{existing.coach_approved_by ? ` by ${existing.coach_approved_by}` : ""}
                    {existing.edited_since_approval ? " — edited since" : ""}
                  </span>
                  <div className="flex gap-2">
                    <button type="button" onClick={() => approve.mutate()} className="min-h-11 flex-1 rounded-md border border-border px-3 text-text-primary">
                      Re-approve as it is
                    </button>
                    <button type="button" onClick={() => unapprove.mutate()} className="min-h-11 rounded-md border border-border px-3">
                      Remove approval
                    </button>
                  </div>
                </div>
              ) : (
                <div className="mt-3 grid gap-2">
                  <Field label="Approved by (optional)">
                    <input value={by} onChange={(e) => setBy(e.target.value)} className={inputCls} />
                  </Field>
                  <Field label="Note (optional)">
                    <input value={note} onChange={(e) => setNote(e.target.value)} className={inputCls} />
                  </Field>
                  <button type="button" onClick={() => approve.mutate()} className="min-h-11 rounded-md border border-border px-3 text-sm text-text-primary">
                    Mark as coach-approved
                  </button>
                </div>
              )}
            </div>
          )}

          {error && (
            <p role="alert" className="mt-3 text-sm text-text-secondary">
              {error}
            </p>
          )}
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => save.mutate()} disabled={save.isPending || !name.trim()} className="min-h-11 flex-1 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-60">
              {save.isPending ? "Saving…" : existing ? "Save changes" : "Add phase"}
            </button>
            <Dialog.Close className="min-h-11 rounded-md border border-border px-4 text-sm text-text-secondary">Cancel</Dialog.Close>
            {existing && !confirmDelete && (
              <button type="button" onClick={() => setConfirmDelete(true)} className="min-h-11 rounded-md px-3 text-sm text-text-tertiary underline">
                Delete phase
              </button>
            )}
            {existing && confirmDelete && (
              <div className="flex w-full items-center gap-2 rounded-md border border-border p-2 text-sm">
                <span className="flex-1 text-text-secondary">Delete this phase? Planned sessions are kept.</span>
                <button type="button" onClick={() => remove.mutate()} className="min-h-11 rounded-md border border-border px-3 text-text-primary">
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
