import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { scheduleLibraryTemplate } from "../../lib/api";
import { addDays, todayISO } from "../../lib/dates";
import type { PlannedWorkout, WorkoutTemplate } from "../../lib/types";
import { invalidateCalendar } from "../calendar/PlannedWorkoutSheet";

const inputCls = "min-h-11 w-full min-w-0 rounded-md border border-border bg-bg px-3 text-sm text-text-primary";
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function ScheduleSheet({ open, onOpenChange, template }: { open: boolean; onOpenChange: (open: boolean) => void; template: WorkoutTemplate }) {
  const qc = useQueryClient();
  const [date, setDate] = useState(addDays(todayISO(), 1));
  const [time, setTime] = useState("");
  const [repeat, setRepeat] = useState(false);
  const [weekdays, setWeekdays] = useState<number[]>([]);
  const [count, setCount] = useState("4");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<PlannedWorkout[] | null>(null);

  useEffect(() => {
    if (!open) return;
    setDate(addDays(todayISO(), 1));
    setTime("");
    setRepeat(false);
    setWeekdays([]);
    setCount("4");
    setError(null);
    setDone(null);
  }, [open]);

  const save = useMutation({
    mutationFn: () =>
      scheduleLibraryTemplate(template.id, {
        date,
        start_time: time || null,
        repeat: repeat ? { weekdays: weekdays.length ? weekdays : undefined, count: Number(count) || 4 } : undefined,
      }),
    onSuccess: (res) => {
      invalidateCalendar(qc);
      setDone(res.planned);
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          data-testid="schedule-sheet"
          className="fixed inset-x-0 bottom-0 z-30 max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,460px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border"
        >
          <Dialog.Title className="text-base font-semibold text-text-primary">Add to calendar</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            {template.name} becomes a planned session — an intention, not a workout. Changing the template later won't change sessions already planned.
          </Dialog.Description>
          {done ? (
            <div className="mt-4 flex flex-col gap-3" data-testid="schedule-done">
              <p className="text-sm text-text-primary">
                Planned {done.length} {done.length === 1 ? "session" : "sessions"}.
              </p>
              <div className="flex gap-2">
                <Link to={`/calendar?view=week&date=${done[0].date}`} className="flex min-h-11 flex-1 items-center justify-center rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast">
                  View in calendar
                </Link>
                <Dialog.Close className="min-h-11 rounded-md border border-border px-4 text-sm text-text-secondary">Done</Dialog.Close>
              </div>
            </div>
          ) : (
            <>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <label className="flex min-w-0 flex-col gap-1 text-sm">
                  <span className="text-text-secondary">Date</span>
                  <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`${inputCls} overflow-hidden`} />
                </label>
                <label className="flex min-w-0 flex-col gap-1 text-sm">
                  <span className="text-text-secondary">Start time (optional)</span>
                  <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={`${inputCls} overflow-hidden`} />
                </label>
                <div className="col-span-2">
                  <button type="button" aria-pressed={repeat} onClick={() => setRepeat((v) => !v)} className={`min-h-11 rounded-md border px-3 text-sm ${repeat ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"}`}>
                    Repeat weekly
                  </button>
                </div>
                {repeat && (
                  <>
                    <fieldset className="col-span-2">
                      <legend className="mb-1 text-sm text-text-secondary">On these days (blank = the same weekday)</legend>
                      <div className="flex flex-wrap gap-1.5">
                        {DAYS.map((d, i) => (
                          <button key={d} type="button" aria-pressed={weekdays.includes(i)} onClick={() => setWeekdays((c) => (c.includes(i) ? c.filter((x) => x !== i) : [...c, i]))} className={`min-h-11 min-w-11 rounded-md border px-2 text-sm ${weekdays.includes(i) ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"}`}>
                            {d}
                          </button>
                        ))}
                      </div>
                    </fieldset>
                    <label className="col-span-2 flex flex-col gap-1 text-sm">
                      <span className="text-text-secondary">Number of sessions</span>
                      <input value={count} onChange={(e) => setCount(e.target.value.replace(/\D/g, ""))} inputMode="numeric" className={inputCls} />
                    </label>
                  </>
                )}
              </div>
              {error && (
                <p role="alert" className="mt-3 text-sm text-text-secondary">
                  {error}
                </p>
              )}
              <div className="mt-5 flex gap-2">
                <button type="button" onClick={() => save.mutate()} disabled={save.isPending || !date} className="min-h-11 flex-1 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast disabled:opacity-60">
                  {save.isPending ? "Adding…" : "Add to calendar"}
                </button>
                <Dialog.Close className="min-h-11 rounded-md border border-border px-4 text-sm text-text-secondary">Cancel</Dialog.Close>
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
