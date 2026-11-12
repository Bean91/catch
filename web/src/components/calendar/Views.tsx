import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { declineMatch, linkPlanned, setPlannedSkipped, unlinkPlanned } from "../../lib/api";
import { dayLabel, isSameMonth, monthGrid, parseISODate, weekdayShort } from "../../lib/dates";
import type { CalendarDay, CalendarPayload, MatchSuggestion, PlannedWorkout } from "../../lib/types";
import { CompletedChip, EventChip, PlannedSessionChip } from "./Chips";
import { invalidateCalendar } from "./PlannedWorkoutSheet";

function linkedCompletedIds(day: CalendarDay): Set<number> {
  return new Set(day.planned.map((p) => p.linked_canonical_id).filter((v): v is number => v != null));
}

// --- Week: seven stacked day rows. No horizontal layout, so nothing scrolls sideways at 390px.

export function WeekView({
  days,
  today,
  onOpenPlanned,
  onAdd,
  onSelectDay,
}: {
  days: CalendarDay[];
  today: string;
  onOpenPlanned: (p: PlannedWorkout) => void;
  onAdd: (date: string) => void;
  onSelectDay: (date: string) => void;
}) {
  return (
    <ul className="flex flex-col gap-2" data-testid="week-view">
      {days.map((day) => {
        const linked = linkedCompletedIds(day);
        const loose = day.completed.filter((c) => !linked.has(c.id));
        const empty = !day.planned.length && !loose.length && !day.events.length;
        const isToday = day.date === today;
        return (
          <li
            key={day.date}
            data-testid="week-day"
            data-date={day.date}
            className={`grid grid-cols-[3.25rem_minmax(0,1fr)_2.75rem] items-start gap-2 rounded-lg border bg-surface p-2 ${isToday ? "border-accent/60" : "border-border"}`}
          >
            <button type="button" onClick={() => onSelectDay(day.date)} aria-label={`Open ${dayLabel(day.date)}`} className="flex min-h-11 flex-col items-center justify-center rounded-md text-center">
              <span className="text-xs text-text-tertiary">{weekdayShort(day.date)}</span>
              <span className={`font-mono-nums text-lg leading-tight ${isToday ? "text-accent" : "text-text-primary"}`}>{parseISODate(day.date).getDate()}</span>
              {isToday && <span className="text-[10px] text-accent">Today</span>}
            </button>
            <div className="flex min-w-0 flex-col gap-1.5">
              {day.events.map((e) => (
                <EventChip key={`e${e.id}`} e={e} />
              ))}
              {day.planned.map((p) => (
                <PlannedSessionChip key={`p${p.id}`} p={p} onOpen={onOpenPlanned} />
              ))}
              {loose.map((c) => (
                <CompletedChip key={`c${c.id}`} c={c} />
              ))}
              {empty && <span className="flex min-h-11 items-center px-1 text-sm text-text-tertiary">Nothing planned</span>}
            </div>
            <button
              type="button"
              onClick={() => onAdd(day.date)}
              aria-label={`Plan a session on ${dayLabel(day.date)}`}
              className="flex min-h-11 min-w-11 items-center justify-center rounded-md border border-border text-lg text-text-secondary"
            >
              +
            </button>
          </li>
        );
      })}
    </ul>
  );
}

// --- Day: the full cards, with link suggestions and per-session actions.

function SuggestionRow({ s, planned, day }: { s: MatchSuggestion; planned: PlannedWorkout; day: CalendarDay }) {
  const qc = useQueryClient();
  const workout = day.completed.find((c) => c.id === s.canonical_id);
  const link = useMutation({ mutationFn: () => linkPlanned(s.planned_id, s.canonical_id), onSuccess: () => invalidateCalendar(qc) });
  const decline = useMutation({ mutationFn: () => declineMatch(s.planned_id, s.canonical_id), onSuccess: () => invalidateCalendar(qc) });
  return (
    <div data-testid="link-suggestion" className="flex flex-col gap-2 rounded-md border border-accent/40 bg-accent/5 p-3 text-sm">
      <p className="text-text-primary">
        “{workout?.title ?? "A logged workout"}” looks like it could be your planned “{planned.title}” ({s.reasons.join(", ")}). Link them?
      </p>
      <p className="text-xs text-text-tertiary">Both records stay as they are — linking only connects them.</p>
      <div className="flex gap-2">
        <button type="button" onClick={() => link.mutate()} disabled={link.isPending} className="min-h-11 flex-1 rounded-md bg-accent px-3 text-accent-contrast">
          Link them
        </button>
        <button type="button" onClick={() => decline.mutate()} disabled={decline.isPending} className="min-h-11 flex-1 rounded-md border border-border px-3 text-text-secondary">
          Not this one
        </button>
      </div>
    </div>
  );
}

export function DayView({
  day,
  suggestions,
  onOpenPlanned,
  onAdd,
}: {
  day: CalendarDay;
  suggestions: MatchSuggestion[];
  onOpenPlanned: (p: PlannedWorkout) => void;
  onAdd: (date: string) => void;
}) {
  const qc = useQueryClient();
  const skip = useMutation({ mutationFn: (v: { id: number; skipped: boolean }) => setPlannedSkipped(v.id, v.skipped), onSuccess: () => invalidateCalendar(qc) });
  const unlink = useMutation({ mutationFn: (id: number) => unlinkPlanned(id), onSuccess: () => invalidateCalendar(qc) });
  const linked = linkedCompletedIds(day);
  const loose = day.completed.filter((c) => !linked.has(c.id));
  const daySuggestions = suggestions.filter((s) => day.planned.some((p) => p.id === s.planned_id));
  return (
    <div className="flex flex-col gap-3" data-testid="day-view">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-medium text-text-primary">{dayLabel(day.date)}</h2>
        <button type="button" onClick={() => onAdd(day.date)} className="min-h-11 rounded-md border border-border px-3 text-sm text-text-secondary">
          + Plan a session
        </button>
      </div>
      {day.events.map((e) => (
        <EventChip key={e.id} e={e} />
      ))}
      {day.planned.length === 0 && loose.length === 0 && day.events.length === 0 && <p className="text-sm text-text-tertiary">Nothing planned or logged for this day.</p>}
      {day.planned.map((p) => {
        const s = daySuggestions.find((x) => x.planned_id === p.id);
        const completed = day.completed.find((c) => c.id === p.linked_canonical_id);
        return (
          <div key={p.id} className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-2">
            <PlannedSessionChip p={p} onOpen={onOpenPlanned} />
            {p.structure.length > 0 && (
              <ul className="px-2 text-xs text-text-secondary">
                {p.structure.map((b, i) => (
                  <li key={i}>
                    {b.reps} × {b.work_min ? `${b.work_min} min` : `${b.work_m} m`}
                    {b.rest_min ? `, ${b.rest_min} min rest` : ""}
                    {b.zone ? ` @ ${b.zone}` : ""}
                  </li>
                ))}
              </ul>
            )}
            {p.coach_feedback && <p className="px-2 text-sm text-text-secondary">Coach: {p.coach_feedback}</p>}
            {p.notes && <p className="px-2 text-sm text-text-secondary">Note: {p.notes}</p>}
            {completed && <CompletedChip c={completed} />}
            {s && <SuggestionRow s={s} planned={p} day={day} />}
            <div className="flex flex-wrap gap-2 px-1">
              {p.linked_canonical_id != null && (
                <button type="button" onClick={() => unlink.mutate(p.id)} className="min-h-11 rounded-md border border-border px-3 text-sm text-text-secondary">
                  Unlink workout
                </button>
              )}
              {p.session_type !== "rest" && p.linked_canonical_id == null && (
                <button type="button" onClick={() => skip.mutate({ id: p.id, skipped: p.status !== "skipped" })} className="min-h-11 rounded-md border border-border px-3 text-sm text-text-secondary">
                  {p.status === "skipped" ? "Put back in plan" : "Mark skipped"}
                </button>
              )}
            </div>
          </div>
        );
      })}
      {loose.map((c) => (
        <div key={c.id} className="flex flex-col gap-1">
          <CompletedChip c={c} />
          {c.notes && <p className="px-2 text-sm text-text-secondary">Note: {c.notes}</p>}
        </div>
      ))}
    </div>
  );
}

// --- Month: a dot grid. Every cell has a text label for screen readers; tapping opens the day.

export function MonthView({
  anchor,
  payload,
  today,
  onSelectDay,
}: {
  anchor: string;
  payload: CalendarPayload;
  today: string;
  onSelectDay: (date: string) => void;
}) {
  const d = parseISODate(anchor);
  const grid = monthGrid(d.getFullYear(), d.getMonth());
  const byDate = new Map(payload.days.map((x) => [x.date, x]));
  return (
    <div data-testid="month-view">
      <div className="grid grid-cols-7 gap-1 pb-1 text-center text-xs text-text-tertiary" aria-hidden>
        {grid[0].map((iso) => (
          <span key={iso}>{weekdayShort(iso).slice(0, 2)}</span>
        ))}
      </div>
      <div className="flex flex-col gap-1">
        {grid.map((week) => (
          <div key={week[0]} className="grid grid-cols-7 gap-1">
            {week.map((iso) => {
              const day = byDate.get(iso);
              const planned = day?.planned.filter((p) => p.session_type !== "rest").length ?? 0;
              const done = day?.completed.length ?? 0;
              const events = day?.events.length ?? 0;
              const label = `${dayLabel(iso)}: ${planned} planned, ${done} completed${events ? `, ${events} event${events > 1 ? "s" : ""}` : ""}`;
              return (
                <button
                  key={iso}
                  type="button"
                  onClick={() => onSelectDay(iso)}
                  aria-label={label}
                  data-testid="month-cell"
                  data-date={iso}
                  className={`flex min-h-12 min-w-0 flex-col items-center justify-start gap-1 rounded-md border py-1 text-sm ${
                    iso === today ? "border-accent/60" : "border-border"
                  } ${isSameMonth(iso, anchor) ? "bg-surface text-text-primary" : "bg-transparent text-text-tertiary"}`}
                >
                  <span className="font-mono-nums leading-none">{parseISODate(iso).getDate()}</span>
                  <span className="flex h-2.5 items-center gap-0.5" aria-hidden>
                    {planned > 0 && <span className="h-2 w-2 rounded-full border border-accent" />}
                    {done > 0 && <span className="h-2 w-2 rounded-full bg-text-secondary" />}
                    {events > 0 && <span className="text-[9px] leading-none text-accent">◆</span>}
                  </span>
                </button>
              );
            })}
          </div>
        ))}
      </div>
      <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-tertiary">
        <span>○ planned</span>
        <span>● completed</span>
        <span>◆ event</span>
      </p>
    </div>
  );
}

export function NavLinks() {
  const cls = "flex min-h-11 items-center rounded-full border border-border bg-surface px-4 text-sm font-medium text-text-secondary transition-colors hover:border-accent/40";
  return (
    <nav aria-label="Related" className="flex flex-wrap gap-2">
      <Link to="/calendar/plan" className={cls}>
        Training plan
      </Link>
      <Link to="/library" className={cls}>
        Library
      </Link>
      <Link to="/feedback" className={cls}>
        Feedback
      </Link>
      <Link to="/workouts" className={cls}>
        Workouts
      </Link>
      <Link to="/tests" className={cls}>
        Tests
      </Link>
      <Link to="/routes" className={cls}>
        Routes
      </Link>
      <Link to="/workouts/duplicates" className={cls}>
        Duplicates
      </Link>
    </nav>
  );
}
