import * as Dialog from "@radix-ui/react-dialog";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createPlanned, deletePlanned, updatePlanned } from "../../lib/api";
import { addDays, dayLabel } from "../../lib/dates";
import type { IntervalBlock, PlannedInput, PlannedWorkout, SessionType, ZoneLabel } from "../../lib/types";
import { SESSION_TYPES, ZONES } from "./labels";

const inputCls = "min-h-11 w-full min-w-0 rounded-md border border-border bg-bg px-3 text-sm text-text-primary";
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="text-text-secondary">{label}</span>
      {children}
    </label>
  );
}

export function invalidateCalendar(qc: ReturnType<typeof useQueryClient>) {
  for (const key of ["calendar", "plan-week", "upcoming-events", "event", "phases", "plan-weeks"]) qc.invalidateQueries({ queryKey: [key] });
}

export function PlannedWorkoutSheet({
  open,
  onOpenChange,
  existing,
  defaultDate,
  eventId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing: PlannedWorkout | null;
  defaultDate: string;
  eventId?: number | null;
}) {
  const qc = useQueryClient();
  const [date, setDate] = useState(defaultDate);
  const [type, setType] = useState<SessionType>("erg");
  const [title, setTitle] = useState("");
  const [startTime, setStartTime] = useState("");
  const [duration, setDuration] = useState("");
  const [distance, setDistance] = useState("");
  const [zone, setZone] = useState<ZoneLabel | "">("");
  const [intensity, setIntensity] = useState("");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");
  const [feedback, setFeedback] = useState("");
  const [blocks, setBlocks] = useState<IntervalBlock[]>([]);
  const [repeat, setRepeat] = useState(false);
  const [weekdays, setWeekdays] = useState<number[]>([]);
  const [until, setUntil] = useState("");
  const [scope, setScope] = useState<"this" | "this_and_following">("this");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The component stays mounted between opens, so form state is reset from props each time.
  useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmDelete(false);
    setScope("this");
    setRepeat(false);
    setWeekdays([]);
    setUntil("");
    if (existing) {
      setDate(existing.date);
      setType(existing.session_type);
      setTitle(existing.title);
      setStartTime(existing.start_time ?? "");
      setDuration(existing.duration_min != null ? String(existing.duration_min) : "");
      setDistance(existing.distance_m != null ? String(existing.distance_m) : "");
      setZone(existing.target_zone ?? "");
      setIntensity(existing.intensity_note ?? "");
      setDescription(existing.description ?? "");
      setNotes(existing.notes ?? "");
      setFeedback(existing.coach_feedback ?? "");
      setBlocks(existing.structure);
    } else {
      setDate(defaultDate);
      setType("erg");
      setTitle("");
      setStartTime("");
      setDuration("");
      setDistance("");
      setZone("");
      setIntensity("");
      setDescription("");
      setNotes("");
      setFeedback("");
      setBlocks([]);
    }
  }, [open, existing, defaultDate]);

  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const body = (): PlannedInput => ({
    date,
    session_type: type,
    title: title.trim() || null,
    start_time: startTime || null,
    duration_min: num(duration),
    distance_m: num(distance),
    target_zone: zone || null,
    intensity_note: intensity.trim() || null,
    description: description.trim() || null,
    structure: blocks.length ? blocks : null,
    notes: notes.trim() || null,
    coach_feedback: feedback.trim() || null,
    event_id: existing?.event_id ?? eventId ?? null,
  });

  const save = useMutation({
    mutationFn: async () => {
      if (existing) {
        const { repeat: _r, ...patch } = body();
        void _r;
        return updatePlanned(existing.id, { ...patch, structure: blocks }, scope);
      }
      const payload = body();
      if (repeat) // Blank "until" means four weeks from the start date (not four sessions: with Mon/Wed/Fri ticked
      // that would be barely over a week).
      payload.repeat = { weekdays: weekdays.length ? weekdays : undefined, until: until || addDays(date, 27), count: null };
      return createPlanned(payload);
    },
    onSuccess: () => {
      invalidateCalendar(qc);
      onOpenChange(false);
    },
    onError: (e: Error) => setError(e.message),
  });

  const remove = useMutation({
    mutationFn: () => deletePlanned(existing!.id, scope),
    onSuccess: () => {
      invalidateCalendar(qc);
      onOpenChange(false);
    },
    onError: (e: Error) => setError(e.message),
  });

  const moveBy = useMutation({
    mutationFn: (days: number) => updatePlanned(existing!.id, { date: addDays(existing!.date, days) }, "this"),
    onSuccess: () => {
      invalidateCalendar(qc);
      onOpenChange(false);
    },
    onError: (e: Error) => setError(e.message),
  });

  const isRest = type === "rest";
  const setBlock = (i: number, patch: Partial<IntervalBlock>) => setBlocks((b) => b.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        {/* z-30, like CheckinSheet: a bottom-anchored sheet reaches the z-20 BottomNav. */}
        <Dialog.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          data-testid="planned-sheet"
          className="fixed inset-x-0 bottom-0 z-30 max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,460px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border"
        >
          <Dialog.Title className="text-base font-semibold text-text-primary">{existing ? "Planned session" : "Plan a session"}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            A plan is an intention — it never counts as training until a real workout is logged.
          </Dialog.Description>
          {existing?.template_id != null && (
            <p className="mt-1 text-sm text-text-secondary" data-testid="from-template">
              From a library template — <Link to={`/library/${existing.template_id}`} className="text-accent underline">open it</Link>. This session is a copy, so editing it won't change the template.
            </p>
          )}

          {existing && (
            <div className="mt-4 flex items-center justify-between gap-2" role="group" aria-label="Move this session">
              <button type="button" disabled={moveBy.isPending} onClick={() => moveBy.mutate(-1)} className="min-h-11 rounded-md border border-border px-3 text-sm text-text-secondary">
                ← Earlier
              </button>
              <span className="text-sm text-text-secondary">{dayLabel(existing.date)}</span>
              <button type="button" disabled={moveBy.isPending} onClick={() => moveBy.mutate(1)} className="min-h-11 rounded-md border border-border px-3 text-sm text-text-secondary">
                Later →
              </button>
            </div>
          )}

          <div className="mt-4 grid grid-cols-2 gap-3">
            <Field label="Date">
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`${inputCls} overflow-hidden`} />
            </Field>
            <Field label="Type">
              <select value={type} onChange={(e) => setType(e.target.value as SessionType)} className={inputCls}>
                {SESSION_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </Field>
            <div className="col-span-2">
              <Field label="Title (optional)">
                <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} placeholder="e.g. Steady UT2" />
              </Field>
            </div>
            {!isRest && (
              <>
                <Field label="Duration (min)">
                  <input type="number" inputMode="decimal" min={0} value={duration} onChange={(e) => setDuration(e.target.value)} className={inputCls} />
                </Field>
                <Field label="Distance (m)">
                  <input type="number" inputMode="decimal" min={0} value={distance} onChange={(e) => setDistance(e.target.value)} className={inputCls} />
                </Field>
                <Field label="Target zone">
                  <select value={zone} onChange={(e) => setZone(e.target.value as ZoneLabel | "")} className={inputCls}>
                    <option value="">None</option>
                    {ZONES.map((z) => (
                      <option key={z} value={z}>
                        {z}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Start time">
                  <input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} className={`${inputCls} overflow-hidden`} />
                </Field>
                <div className="col-span-2">
                  <Field label="Intensity note">
                    <input value={intensity} onChange={(e) => setIntensity(e.target.value)} className={inputCls} placeholder="e.g. rate 18–20, conversational" />
                  </Field>
                </div>
              </>
            )}
            <div className="col-span-2">
              <Field label="Description">
                <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className={`${inputCls} py-2`} />
              </Field>
            </div>
          </div>

          {!isRest && (
            <fieldset className="mt-4 flex flex-col gap-2">
              <legend className="text-sm font-medium text-text-primary">Structure (optional)</legend>
              {blocks.map((b, i) => (
                <div key={i} className="grid grid-cols-[3.5rem_1fr_1fr_4.5rem_auto] items-end gap-2" data-testid="block-row">
                  <Field label="Reps">
                    <input type="number" min={1} value={b.reps} onChange={(e) => setBlock(i, { reps: Number(e.target.value) })} className={inputCls} />
                  </Field>
                  <Field label="Work min">
                    <input type="number" min={0} value={b.work_min ?? ""} onChange={(e) => setBlock(i, { work_min: e.target.value === "" ? undefined : Number(e.target.value) })} className={inputCls} />
                  </Field>
                  <Field label="Rest min">
                    <input type="number" min={0} value={b.rest_min ?? ""} onChange={(e) => setBlock(i, { rest_min: e.target.value === "" ? undefined : Number(e.target.value) })} className={inputCls} />
                  </Field>
                  <Field label="Zone">
                    <select value={b.zone ?? ""} onChange={(e) => setBlock(i, { zone: (e.target.value || undefined) as ZoneLabel | undefined })} className={inputCls}>
                      <option value="">–</option>
                      {ZONES.map((z) => (
                        <option key={z}>{z}</option>
                      ))}
                    </select>
                  </Field>
                  <button type="button" aria-label={`Remove block ${i + 1}`} onClick={() => setBlocks((x) => x.filter((_, j) => j !== i))} className="min-h-11 min-w-11 rounded-md border border-border text-text-secondary">
                    ×
                  </button>
                </div>
              ))}
              <button type="button" onClick={() => setBlocks((b) => [...b, { reps: 1, work_min: 10 }])} className="min-h-11 self-start rounded-md border border-dashed border-border px-3 text-sm text-text-secondary">
                + Add block
              </button>
            </fieldset>
          )}

          {existing && (
            <div className="mt-4 grid gap-3">
              <Field label="Your notes">
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className={`${inputCls} py-2`} />
              </Field>
              <Field label="Coach feedback (a single note — the Feedback page keeps who wrote what, and its history)">
                <textarea value={feedback} onChange={(e) => setFeedback(e.target.value)} rows={2} className={`${inputCls} py-2`} />
              </Field>
            </div>
          )}

          {!existing && (
            <div className="mt-4 flex flex-col gap-2">
              <label className="flex min-h-11 items-center gap-2 text-sm text-text-primary">
                <input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} className="h-5 w-5" />
                Repeat weekly
              </label>
              {repeat && (
                <div className="flex flex-col gap-2 rounded-md border border-border p-3">
                  <div className="flex flex-wrap gap-1.5" role="group" aria-label="Repeat on">
                    {WEEKDAYS.map((w, i) => (
                      <button
                        key={w}
                        type="button"
                        aria-pressed={weekdays.includes(i)}
                        onClick={() => setWeekdays((c) => (c.includes(i) ? c.filter((x) => x !== i) : [...c, i]))}
                        className={`min-h-11 min-w-11 rounded-md border px-2 text-sm ${weekdays.includes(i) ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"}`}
                      >
                        {w}
                      </button>
                    ))}
                  </div>
                  <Field label="Until (blank = 4 weeks, max 26)">
                    <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className={`${inputCls} overflow-hidden`} />
                  </Field>
                </div>
              )}
            </div>
          )}

          {existing?.series_id && (
            <div className="mt-4 flex gap-2" role="radiogroup" aria-label="Apply to">
              {(["this", "this_and_following"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  role="radio"
                  aria-checked={scope === s}
                  onClick={() => setScope(s)}
                  className={`min-h-11 flex-1 rounded-md border text-sm ${scope === s ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"}`}
                >
                  {s === "this" ? "Just this one" : "This and following"}
                </button>
              ))}
            </div>
          )}

          {error && (
            <p role="alert" className="mt-3 text-sm text-text-secondary">
              {error}
            </p>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => save.mutate()} disabled={save.isPending} className="min-h-11 flex-1 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-60">
              {save.isPending ? "Saving…" : existing ? "Save changes" : "Add to plan"}
            </button>
            <Dialog.Close className="min-h-11 rounded-md border border-border px-4 text-sm text-text-secondary">Cancel</Dialog.Close>
            {existing && !confirmDelete && (
              <button type="button" onClick={() => setConfirmDelete(true)} className="min-h-11 rounded-md px-3 text-sm text-text-tertiary underline">
                Remove from plan
              </button>
            )}
            {existing && confirmDelete && (
              <div className="flex w-full items-center gap-2 rounded-md border border-border p-2 text-sm">
                <span className="flex-1 text-text-secondary">Remove {scope === "this" ? "this planned session" : "this and later sessions"}? Logged workouts aren’t affected.</span>
                <button type="button" onClick={() => remove.mutate()} disabled={remove.isPending} className="min-h-11 rounded-md border border-border px-3 text-text-primary">
                  Remove
                </button>
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
