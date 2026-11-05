import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import {
  addMemoryEvent,
  addMemoryFact,
  addMemoryGoal,
  deleteMemoryItem,
  fetchMemory,
  updateMemoryEvent,
  updateMemoryFact,
  updateMemoryGoal,
} from "../lib/api";
import type { MemoryEvent, MemoryFact, MemoryGoal } from "../lib/types";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";

const FACT_CATEGORIES = ["injury", "schedule", "equipment", "preference", "other"] as const;
const EVENT_TYPES = ["race", "2k_test", "camp", "selection"] as const;
const PRIORITIES = ["A", "B", "C"] as const;
const GOAL_STATUSES = ["active", "done", "abandoned"] as const;

// overflow-hidden on the input/select, min-w-0 on the label: native <input type="date">
// controls on iOS Safari don't reliably clip their own rendering to a CSS width the way a
// text input does — in a grid/flex row, a label's default min-width:auto otherwise lets that
// native content push past its track and visually overlap the next field (seen live: Date
// bleeding into Type in the "Add event" row at 390px).
const inputCls = "min-h-9 w-full min-w-0 overflow-hidden rounded-md border border-border bg-surface-2 px-2 text-sm text-text-primary";
const rowCls = "grid grid-cols-2 gap-x-2 gap-y-2.5 border-b border-border py-3 last:border-0 sm:flex sm:flex-wrap sm:items-end";
const labelCls = "flex min-w-0 flex-col gap-1 text-[11px] uppercase tracking-wide text-text-tertiary";

function Field({ label, className = "", children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <label className={`${labelCls} ${className}`}>
      {label}
      {children}
    </label>
  );
}

function DeleteButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Delete"
      className="col-span-2 flex min-h-9 items-center justify-center gap-1.5 rounded-md border border-transparent text-xs text-text-tertiary hover:border-band-red/30 hover:text-band-red-text sm:col-span-1 sm:ml-auto sm:w-9"
    >
      <span aria-hidden>×</span>
      <span className="sm:hidden">Delete</span>
    </button>
  );
}

function FactRow({ fact, onUpdate, onDelete }: { fact: MemoryFact; onUpdate: (patch: Partial<MemoryFact>) => void; onDelete: () => void }) {
  // Lifted to state (not just defaultValue) so the dashed empty-state border below can react
  // live as the user clears/sets a date, same as GoalRow's targetDate.
  const [validUntil, setValidUntil] = useState(fact.valid_until ?? "");
  return (
    <div className={rowCls}>
      <Field label="Category" className="sm:w-32">
        <select defaultValue={fact.category} onChange={(e) => onUpdate({ category: e.target.value })} className={inputCls}>
          {FACT_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Fact" className="col-span-2 sm:min-w-[180px] sm:flex-1">
        <input defaultValue={fact.text} onBlur={(e) => onUpdate({ text: e.target.value })} className={inputCls} />
      </Field>
      <Field label={fact.expired ? "Valid until (expired)" : "Valid until"} className="sm:w-36">
        <input
          type="date"
          value={validUntil}
          onChange={(e) => {
            setValidUntil(e.target.value);
            onUpdate({ valid_until: e.target.value || null });
          }}
          className={`${inputCls} ${validUntil ? "" : "border-dashed"}`}
        />
      </Field>
      <DeleteButton onClick={onDelete} />
    </div>
  );
}

function EventRow({ event, onUpdate, onDelete }: { event: MemoryEvent; onUpdate: (patch: Partial<MemoryEvent>) => void; onDelete: () => void }) {
  return (
    <div className={rowCls}>
      <Field label="Name" className="col-span-2 sm:min-w-[140px] sm:flex-1">
        <input defaultValue={event.name} onBlur={(e) => onUpdate({ name: e.target.value })} className={inputCls} />
      </Field>
      <Field label="Date" className="sm:w-36">
        <input type="date" defaultValue={event.date} onChange={(e) => onUpdate({ date: e.target.value })} className={inputCls} />
      </Field>
      <Field label="Type" className="sm:w-28">
        <select defaultValue={event.type} onChange={(e) => onUpdate({ type: e.target.value })} className={inputCls}>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Priority" className="sm:w-20">
        <select defaultValue={event.priority ?? ""} onChange={(e) => onUpdate({ priority: e.target.value || null })} className={inputCls}>
          <option value="">—</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Goal time" className="sm:w-24">
        <input defaultValue={event.goal_time ?? ""} onBlur={(e) => onUpdate({ goal_time: e.target.value || null })} className={inputCls} />
      </Field>
      <Field label="Result" className="sm:w-24">
        <input defaultValue={event.result ?? ""} onBlur={(e) => onUpdate({ result: e.target.value || null })} className={inputCls} />
      </Field>
      <Field label="Days to go" className="sm:w-20">
        <span className="font-mono-nums flex min-h-9 items-center text-sm text-text-secondary">{event.days_to_go >= 0 ? `${event.days_to_go}d` : "past"}</span>
      </Field>
      <DeleteButton onClick={onDelete} />
    </div>
  );
}

function GoalRow({ goal, onUpdate, onDelete }: { goal: MemoryGoal; onUpdate: (patch: { text: string; target_date: string | null; status: MemoryGoal["status"] }) => void; onDelete: () => void }) {
  const [text, setText] = useState(goal.text);
  const [targetDate, setTargetDate] = useState(goal.target_date ?? "");
  const [status, setStatus] = useState(goal.status);
  return (
    <div className={rowCls}>
      <Field label="Goal" className="col-span-2 sm:min-w-[160px] sm:flex-1">
        <input
          defaultValue={text}
          onBlur={(e) => {
            setText(e.target.value);
            onUpdate({ text: e.target.value, target_date: targetDate || null, status });
          }}
          className={inputCls}
        />
      </Field>
      <Field label="Target date" className="sm:w-36">
        <input
          type="date"
          defaultValue={targetDate}
          onChange={(e) => {
            setTargetDate(e.target.value);
            onUpdate({ text, target_date: e.target.value || null, status });
          }}
          className={`${inputCls} ${targetDate ? "" : "border-dashed"}`}
        />
      </Field>
      <Field label="Status" className="sm:w-28">
        <select
          defaultValue={status}
          onChange={(e) => {
            const next = e.target.value as MemoryGoal["status"];
            setStatus(next);
            onUpdate({ text, target_date: targetDate || null, status: next });
          }}
          className={inputCls}
        >
          {GOAL_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </Field>
      <DeleteButton onClick={onDelete} />
    </div>
  );
}

export function MemoryPage() {
  const queryClient = useQueryClient();
  const memoryQuery = useQuery({ queryKey: ["coach-memory"], queryFn: fetchMemory });

  const [newFact, setNewFact] = useState({ category: "preference", text: "" });
  const [newEvent, setNewEvent] = useState({ name: "", date: "", type: "race", priority: "" });
  const [newGoal, setNewGoal] = useState({ text: "", target_date: "" });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["coach-memory"] });

  const addFact = useMutation({ mutationFn: () => addMemoryFact(newFact.category, newFact.text, null), onSuccess: () => { setNewFact({ category: "preference", text: "" }); invalidate(); } });
  const addEvent = useMutation({
    mutationFn: () => addMemoryEvent({ name: newEvent.name, date: newEvent.date, type: newEvent.type, distance: null, boat_class: null, priority: newEvent.priority || null, goal_time: null, result: null }),
    onSuccess: () => { setNewEvent({ name: "", date: "", type: "race", priority: "" }); invalidate(); },
  });
  const addGoal = useMutation({ mutationFn: () => addMemoryGoal(newGoal.text, newGoal.target_date || null), onSuccess: () => { setNewGoal({ text: "", target_date: "" }); invalidate(); } });

  const updateFact = useMutation({ mutationFn: ({ ref, patch }: { ref: string; patch: Partial<MemoryFact> }) => updateMemoryFact(ref, patch), onSuccess: invalidate });
  const updateEvent = useMutation({ mutationFn: ({ ref, patch }: { ref: string; patch: Partial<MemoryEvent> }) => updateMemoryEvent(ref, patch), onSuccess: invalidate });
  const updateGoal = useMutation({
    mutationFn: ({ ref, text, target_date, status }: { ref: string; text: string; target_date: string | null; status: MemoryGoal["status"] }) =>
      updateMemoryGoal(ref, text, target_date, status),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: (ref: string) => deleteMemoryItem(ref), onSuccess: invalidate });

  if (memoryQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <CardSkeleton lines={3} />
        <CardSkeleton lines={3} />
      </div>
    );
  }
  if (memoryQuery.isError || !memoryQuery.data) {
    return <ErrorState message="Couldn't load memory." onRetry={() => memoryQuery.refetch()} />;
  }
  const { facts, events, goals } = memoryQuery.data;

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <h1 className="text-lg font-semibold text-text-primary">Coach memory</h1>
      <p className="text-sm text-text-tertiary">
        Everything the coach remembers about you — it saves these on its own during a chat when you mention a race, goal,
        injury, schedule change, or preference. Edit or delete anything here.
      </p>

      <Card title="Events">
        <div className="flex flex-col">
          {events.length === 0 && <p className="py-2 text-sm text-text-tertiary">No events recorded.</p>}
          {events.map((event) => (
            <EventRow key={event.ref} event={event} onUpdate={(patch) => updateEvent.mutate({ ref: event.ref, patch })} onDelete={() => remove.mutate(event.ref)} />
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            addEvent.mutate();
          }}
          className="mt-1 grid grid-cols-2 gap-x-2 gap-y-2.5 border-t border-border pt-3 sm:flex sm:flex-wrap sm:items-end"
        >
          <Field label="Name" className="col-span-2 sm:min-w-[140px] sm:flex-1">
            <input required placeholder="e.g. Head of the Charles" value={newEvent.name} onChange={(e) => setNewEvent({ ...newEvent, name: e.target.value })} className={inputCls} />
          </Field>
          <Field label="Date" className="sm:w-36">
            {/* iOS Safari renders an empty type=date input with no "mm/dd/yyyy" placeholder
                at all (unlike desktop browsers), so it otherwise looks like dead space next
                to Type — a dashed border (same empty-state convention as EmptyState.tsx)
                signals "fillable" without risking a duplicate placeholder on browsers that
                do render their own. */}
            <input
              required
              type="date"
              value={newEvent.date}
              onChange={(e) => setNewEvent({ ...newEvent, date: e.target.value })}
              className={`${inputCls} ${newEvent.date ? "" : "border-dashed"}`}
            />
          </Field>
          <Field label="Type" className="sm:w-28">
            <select value={newEvent.type} onChange={(e) => setNewEvent({ ...newEvent, type: e.target.value })} className={inputCls}>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Priority" className="sm:w-24">
            <select value={newEvent.priority} onChange={(e) => setNewEvent({ ...newEvent, priority: e.target.value })} className={inputCls}>
              <option value="">—</option>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
          <button
            type="submit"
            disabled={addEvent.isPending}
            className="col-span-2 min-h-11 rounded-md bg-accent px-3 text-sm font-medium text-accent-contrast hover:opacity-90 disabled:opacity-50 sm:col-span-1 sm:min-h-9"
          >
            Add event
          </button>
        </form>
      </Card>

      <Card title="Goals">
        <div className="flex flex-col">
          {goals.length === 0 && <p className="py-2 text-sm text-text-tertiary">No goals recorded.</p>}
          {goals.map((goal) => (
            <GoalRow key={goal.ref} goal={goal} onUpdate={(patch) => updateGoal.mutate({ ref: goal.ref, ...patch })} onDelete={() => remove.mutate(goal.ref)} />
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            addGoal.mutate();
          }}
          className="mt-1 grid grid-cols-2 gap-x-2 gap-y-2.5 border-t border-border pt-3 sm:flex sm:flex-wrap sm:items-end"
        >
          <Field label="Goal" className="col-span-2 sm:min-w-[160px] sm:flex-1">
            <input required placeholder="e.g. Break 6:40 for 2k" value={newGoal.text} onChange={(e) => setNewGoal({ ...newGoal, text: e.target.value })} className={inputCls} />
          </Field>
          <Field label="Target date" className="sm:w-36">
            <input
              type="date"
              value={newGoal.target_date}
              onChange={(e) => setNewGoal({ ...newGoal, target_date: e.target.value })}
              className={`${inputCls} ${newGoal.target_date ? "" : "border-dashed"}`}
            />
          </Field>
          <button
            type="submit"
            disabled={addGoal.isPending}
            className="col-span-2 min-h-11 rounded-md bg-accent px-3 text-sm font-medium text-accent-contrast hover:opacity-90 disabled:opacity-50 sm:col-span-1 sm:min-h-9"
          >
            Add goal
          </button>
        </form>
      </Card>

      <Card title="Facts">
        <div className="flex flex-col">
          {facts.length === 0 && <p className="py-2 text-sm text-text-tertiary">No facts recorded.</p>}
          {facts.map((fact) => (
            <FactRow key={fact.ref} fact={fact} onUpdate={(patch) => updateFact.mutate({ ref: fact.ref, patch })} onDelete={() => remove.mutate(fact.ref)} />
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            addFact.mutate();
          }}
          className="mt-1 grid grid-cols-2 gap-x-2 gap-y-2.5 border-t border-border pt-3 sm:flex sm:flex-wrap sm:items-end"
        >
          <Field label="Category" className="sm:w-32">
            <select value={newFact.category} onChange={(e) => setNewFact({ ...newFact, category: e.target.value })} className={inputCls}>
              {FACT_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Fact" className="col-span-2 sm:min-w-[160px] sm:flex-1">
            <input required placeholder="e.g. Prefers morning sessions" value={newFact.text} onChange={(e) => setNewFact({ ...newFact, text: e.target.value })} className={inputCls} />
          </Field>
          <button
            type="submit"
            disabled={addFact.isPending}
            className="col-span-2 min-h-11 rounded-md bg-accent px-3 text-sm font-medium text-accent-contrast hover:opacity-90 disabled:opacity-50 sm:col-span-1 sm:min-h-9"
          >
            Add fact
          </button>
        </form>
      </Card>
    </div>
  );
}
