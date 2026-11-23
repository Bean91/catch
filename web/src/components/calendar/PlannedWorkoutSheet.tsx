import * as Dialog from "@radix-ui/react-dialog";
import { useToast } from "../ui/Toast";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createPlanned, deletePlanned, fetchLinkCandidates, fetchPlanComparison, linkPlanned, updatePlanned } from "../../lib/api";
import { formatClock, parseClock } from "../../lib/duration";
import { formatDuration } from "../../lib/format";
import { PlanComparisonView } from "./PlanComparisonView";
import { blockText } from "./BlockLine";
import { EventSelect } from "./EventSelect";
import { addDays, dayLabel } from "../../lib/dates";
import type { IntervalBlock, PlannedInput, PlannedWorkout, SessionType, ZoneLabel } from "../../lib/types";
import { SESSION_TYPES, ZONES } from "./labels";
import { SheetContent } from "../ui/Sheet";
import { buttonClass } from "../ui/Button";
import { controlSkin } from "../ui/Field";

const inputCls = `${controlSkin} min-h-11 w-full min-w-0`;
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
  for (const key of ["calendar", "plan-week", "upcoming-events", "event", "phases", "plan-comparison", "workout-plan-comparison", "link-candidates", "phase-progress", "month-summary"]) qc.invalidateQueries({ queryKey: [key] });
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
  const [eventChoice, setEventChoice] = useState<number | null>(null);
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
      setEventChoice(existing.event_id);
    } else {
      setEventChoice(eventId ?? null);
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
  }, [open, existing, defaultDate, eventId]);

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
    event_id: eventChoice,
  });

  const { toast } = useToast();
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
      toast(existing ? "Session updated" : "Session planned");
    },
    onError: (e: Error) => setError(e.message),
  });

  const remove = useMutation({
    mutationFn: () => deletePlanned(existing!.id, scope),
    onSuccess: () => {
      invalidateCalendar(qc);
      onOpenChange(false);
      toast("Session removed");
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
      {/* z-30, like CheckinSheet: a bottom-anchored sheet reaches the z-20 BottomNav. */}<SheetContent width="md" onOpenAutoFocus={(e) => e.preventDefault()} data-testid="planned-sheet">
          <Dialog.Title className="text-lg font-semibold text-text-primary">{existing ? "Planned session" : "Plan a session"}</Dialog.Title>
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
              <button type="button" disabled={moveBy.isPending} onClick={() => moveBy.mutate(-1)} className={buttonClass("secondary", "md")}>
                ← Earlier
              </button>
              <span className="text-sm text-text-secondary">{dayLabel(existing.date)}</span>
              <button type="button" disabled={moveBy.isPending} onClick={() => moveBy.mutate(1)} className={buttonClass("secondary", "md")}>
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
            {!isRest && (
              <div className="col-span-2">
                <Field label="Towards an event (optional)">
                  <EventSelect value={eventChoice} onChange={setEventChoice} className={inputCls} enabled={open} />
                </Field>
              </div>
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
                <BlockEditor key={i} index={i} b={b} bike={type === "bike"} onChange={(patch) => setBlock(i, patch)} onRemove={() => setBlocks((x) => x.filter((_, j) => j !== i))} />
              ))}
              <button type="button" onClick={() => setBlocks((b) => [...b, { reps: 1, work_min: 10 }])} className="min-h-11 self-start rounded-md border border-dashed border-border px-3 text-sm text-text-secondary">
                + Add block
              </button>
            </fieldset>
          )}

          {existing && existing.linked_canonical_id != null && <ComparisonSection plannedId={existing.id} />}
          {existing && existing.linked_canonical_id == null && existing.session_type !== "rest" && <LinkPicker plannedId={existing.id} onLinked={() => onOpenChange(false)} />}

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
            <button type="button" onClick={() => save.mutate()} disabled={save.isPending} className={buttonClass("primary", "md", "flex-1")}>
              {save.isPending ? "Saving…" : existing ? "Save changes" : "Add to plan"}
            </button>
            <Dialog.Close className={buttonClass("secondary", "md")}>Cancel</Dialog.Close>
            {existing && !confirmDelete && (
              <button type="button" onClick={() => setConfirmDelete(true)} className="min-h-11 rounded-md px-3 text-sm text-text-tertiary underline">
                Remove from plan
              </button>
            )}
            {existing && confirmDelete && (
              <div className="flex w-full items-center gap-2 rounded-md border border-border p-2 text-sm">
                <span className="flex-1 text-text-secondary">Remove {scope === "this" ? "this planned session" : "this and later sessions"}? Logged workouts aren’t affected.</span>
                <button type="button" onClick={() => remove.mutate()} disabled={remove.isPending} className={buttonClass("secondary", "md")}>
                  Remove
                </button>
              </div>
            )}
          </div>
        </SheetContent>
    </Dialog.Root>
  );
}

const KINDS: { value: NonNullable<IntervalBlock["kind"]>; label: string }[] = [
  { value: "warmup", label: "Warm-up" },
  { value: "work", label: "Work" },
  { value: "cooldown", label: "Cool-down" },
];

function numOrUndef(v: string): number | undefined {
  return v.trim() === "" ? undefined : Number(v);
}

/** One block: what is done (reps × time or distance, rest) on two short rows, and the optional targets under a disclosure. A
 * target left blank is simply not set — nothing is filled in for it. */
function BlockEditor({ index, b, bike, onChange, onRemove }: { index: number; b: IntervalBlock; bike: boolean; onChange: (p: Partial<IntervalBlock>) => void; onRemove: () => void }) {
  const [splitText, setSplitText] = useState(b.split_s != null ? formatClock(b.split_s, true) : "");
  const hasTargets = [b.split_s, b.watts, b.rate_min, b.rate_max, b.hr_min, b.hr_max].some((v) => v != null);
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-2" data-testid="block-row">
      <div className="grid grid-cols-[minmax(0,1.3fr)_3.5rem_minmax(0,1fr)_minmax(0,1fr)] items-end gap-2">
        <Field label="Part">
          <select value={b.kind ?? "work"} onChange={(e) => onChange({ kind: e.target.value === "work" ? undefined : (e.target.value as IntervalBlock["kind"]) })} className={inputCls}>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Reps">
          <input type="number" min={1} value={b.reps} onChange={(e) => onChange({ reps: Number(e.target.value) })} className={inputCls} />
        </Field>
        <Field label="Work min">
          <input type="number" min={0} value={b.work_m != null && b.work_min != null ? "" : (b.work_min ?? "")} placeholder={b.work_m != null && b.work_min != null ? `≈${b.work_min.toFixed(1)}` : undefined} onChange={(e) => onChange({ work_min: numOrUndef(e.target.value) })} className={inputCls} />
        </Field>
        <Field label="Work m">
          <input type="number" min={0} value={b.work_m ?? ""} onChange={(e) => onChange({ work_m: numOrUndef(e.target.value) })} className={inputCls} />
        </Field>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-end gap-2">
        <Field label="Rest min">
          <input type="number" min={0} value={b.rest_min ?? ""} onChange={(e) => onChange({ rest_min: numOrUndef(e.target.value) })} className={inputCls} />
        </Field>
        <Field label="Zone">
          <select value={b.zone ?? ""} onChange={(e) => onChange({ zone: (e.target.value || undefined) as ZoneLabel | undefined })} className={inputCls}>
            <option value="">–</option>
            {ZONES.map((z) => (
              <option key={z}>{z}</option>
            ))}
          </select>
        </Field>
        <button type="button" aria-label={`Remove block ${index + 1}`} onClick={onRemove} className={buttonClass("secondary", "md", "min-w-11")}>
          ×
        </button>
      </div>
      <details open={hasTargets} className="text-sm">
        <summary className="flex min-h-11 cursor-pointer items-center text-text-secondary">Targets {hasTargets ? `— ${blockText({ ...b, reps: 1, work_m: undefined, work_min: undefined, rest_min: undefined, zone: undefined, kind: undefined }, bike ? "cycling" : null).replace(/^ · /, "")}` : "(optional)"}</summary>
        <div className="grid grid-cols-2 gap-2 pt-1 sm:grid-cols-3">
          <Field label={`Split ${bike ? "/1000m" : "/500m"} (m:ss.t)`}>
            <input
              inputMode="decimal"
              value={splitText}
              placeholder="1:45.0"
              onChange={(e) => setSplitText(e.target.value)}
              onBlur={() => {
                const v = parseClock(splitText);
                onChange({ split_s: v ?? undefined });
                if (splitText.trim() && v == null) setSplitText("");
              }}
              className={inputCls}
            />
          </Field>
          <Field label="Power (W)">
            <input type="number" min={0} value={b.watts ?? ""} onChange={(e) => onChange({ watts: numOrUndef(e.target.value) })} className={inputCls} />
          </Field>
          <Field label={bike ? "Cadence from (rpm)" : "Rate from (spm)"}>
            <input type="number" min={0} value={b.rate_min ?? ""} onChange={(e) => onChange({ rate_min: numOrUndef(e.target.value) })} className={inputCls} />
          </Field>
          <Field label={bike ? "Cadence to (rpm)" : "Rate to (spm)"}>
            <input type="number" min={0} value={b.rate_max ?? ""} onChange={(e) => onChange({ rate_max: numOrUndef(e.target.value) })} className={inputCls} />
          </Field>
          <Field label="HR from (bpm)">
            <input type="number" min={0} value={b.hr_min ?? ""} onChange={(e) => onChange({ hr_min: numOrUndef(e.target.value) })} className={inputCls} />
          </Field>
          <Field label="HR to (bpm)">
            <input type="number" min={0} value={b.hr_max ?? ""} onChange={(e) => onChange({ hr_max: numOrUndef(e.target.value) })} className={inputCls} />
          </Field>
        </div>
      </details>
    </div>
  );
}

function ComparisonSection({ plannedId }: { plannedId: number }) {
  const q = useQuery({ queryKey: ["plan-comparison", plannedId], queryFn: () => fetchPlanComparison(plannedId) });
  return (
    <section className="mt-4 rounded-md border border-border p-3" aria-label="Planned and done">
      <h3 className="mb-2 text-sm font-medium text-text-primary">Planned and done</h3>
      {q.isError ? (
        <p role="alert" className="text-sm text-text-secondary">
          Couldn't load the comparison. <button type="button" onClick={() => q.refetch()} className="underline">Retry</button>
        </p>
      ) : !q.data ? (
        <p className="text-sm text-text-tertiary">Loading…</p>
      ) : (
        <PlanComparisonView data={q.data} />
      )}
    </section>
  );
}

/** When the matcher didn't suggest a workout (a different day, a different shape), the athlete links one by hand. */
function LinkPicker({ plannedId, onLinked }: { plannedId: number; onLinked: () => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["link-candidates", plannedId], queryFn: () => fetchLinkCandidates(plannedId), enabled: open });
  const link = useMutation({
    mutationFn: (canonicalId: number) => linkPlanned(plannedId, canonicalId),
    onSuccess: () => {
      invalidateCalendar(qc);
      onLinked();
    },
  });
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className={buttonClass("secondary", "md", "mt-4 self-start")} data-testid="open-link-picker">
        Link a workout…
      </button>
    );
  }
  const items = q.data?.candidates ?? [];
  return (
    <section className="mt-4 flex flex-col gap-2 rounded-md border border-border p-3" aria-label="Link a workout">
      <h3 className="text-sm font-medium text-text-primary">Link a workout</h3>
      <p className="text-xs text-text-tertiary">Workouts within three days of this plan. Linking only connects the two — neither record changes.</p>
      {q.isError && <p role="alert" className="text-sm text-text-secondary">Couldn't load workouts.</p>}
      {q.data && items.length === 0 && <p className="text-sm text-text-tertiary">No workouts within three days of this plan.</p>}
      <ul className="flex flex-col gap-1.5">
        {items.map((c) => (
          <li key={c.id} className="flex min-w-0 flex-wrap items-center gap-2 rounded-md bg-surface-2 p-2 text-sm">
            <span className="min-w-0 flex-1 wrap-anywhere text-text-primary">
              {c.title ?? "Workout"}
              <span className="ml-2 text-xs text-text-tertiary">
                {dayLabel(c.local_date)} · {formatDuration((c.duration_min ?? 0) * 60)}
                {c.days_from_plan !== 0 && ` · ${Math.abs(c.days_from_plan)} day${Math.abs(c.days_from_plan) > 1 ? "s" : ""} ${c.days_from_plan > 0 ? "after" : "before"}`}
              </span>
            </span>
            {c.linked_elsewhere ? (
              <span className="text-xs text-text-tertiary">Linked to another plan</span>
            ) : (
              <button type="button" disabled={link.isPending} onClick={() => link.mutate(c.id)} className={buttonClass("primary", "sm")}>
                Link
              </button>
            )}
          </li>
        ))}
      </ul>
      {link.isError && <p role="alert" className="text-sm text-text-secondary">{(link.error as Error).message}</p>}
    </section>
  );
}
