import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PhaseBanner, WeekSummaryCard } from "../components/calendar/WeekSummaryCard";
import { DayView, MonthView, NavLinks, WeekView } from "../components/calendar/Views";
import { EventSheet } from "../components/calendar/EventSheet";
import { PlannedWorkoutSheet } from "../components/calendar/PlannedWorkoutSheet";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { fetchCalendar, fetchPlanWeekSummary } from "../lib/api";
import { addDays, addMonths, dayLabel, monthGrid, monthLabel, parseISODate, todayISO, weekRangeLabel, weekStart } from "../lib/dates";
import type { PlannedWorkout } from "../lib/types";

type View = "day" | "week" | "month";
const VIEWS: { value: View; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];

function rangeFor(view: View, date: string): [string, string] {
  if (view === "day") return [date, date];
  if (view === "week") {
    const s = weekStart(date);
    return [s, addDays(s, 6)];
  }
  const d = parseISODate(date);
  const grid = monthGrid(d.getFullYear(), d.getMonth());
  return [grid[0][0], grid[grid.length - 1][6]];
}

export function CalendarPage() {
  const [params, setParams] = useSearchParams();
  const today = todayISO();
  const view = (VIEWS.find((v) => v.value === params.get("view"))?.value ?? "week") as View;
  const date = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") ?? "") ? params.get("date")! : today;
  const [sheet, setSheet] = useState<{ open: boolean; existing: PlannedWorkout | null; date: string }>({ open: false, existing: null, date: today });
  const [eventSheet, setEventSheet] = useState(false);

  const setNav = (next: { view?: View; date?: string }) => {
    const p = new URLSearchParams(params);
    p.set("view", next.view ?? view);
    p.set("date", next.date ?? date);
    setParams(p, { replace: true });
  };

  // Day view fetches its whole week so stepping between days doesn't flash empty.
  const [from, to] = rangeFor(view === "day" ? "week" : view, date);
  const cal = useQuery({ queryKey: ["calendar", from, to], queryFn: () => fetchCalendar(from, to) });
  const weekISO = weekStart(date);
  const summary = useQuery({ queryKey: ["plan-week", weekISO], queryFn: () => fetchPlanWeekSummary(weekISO) });

  const step = (dir: -1 | 1) => setNav({ date: view === "month" ? addMonths(date, dir) : addDays(date, dir * (view === "week" ? 7 : 1)) });
  const label = view === "day" ? dayLabel(date) : view === "week" ? weekRangeLabel(weekISO) : monthLabel(date);
  const phase = cal.data?.phases.find((p) => p.start_date <= date && date <= p.end_date) ?? null;
  const openNew = (d: string) => setSheet({ open: true, existing: null, date: d });
  const openExisting = (p: PlannedWorkout) => setSheet({ open: true, existing: p, date: p.date });
  const day = cal.data?.days.find((d) => d.date === date);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-text-primary">Calendar</h1>
        <div className="flex gap-2">
          <button type="button" onClick={() => setEventSheet(true)} className="min-h-11 rounded-full border border-border bg-surface px-4 text-sm font-medium text-text-secondary">
            + Event
          </button>
          <button type="button" onClick={() => openNew(date)} className="min-h-11 rounded-full bg-accent px-4 text-sm font-medium text-accent-contrast">
            + Plan
          </button>
        </div>
      </div>

      <NavLinks />

      <div className="flex flex-col gap-2">
        <div role="tablist" aria-label="Calendar view" className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-surface p-1">
          {VIEWS.map((v) => (
            <button
              key={v.value}
              type="button"
              role="tab"
              aria-selected={view === v.value}
              onClick={() => setNav({ view: v.value })}
              className={`min-h-11 rounded-md text-sm font-medium transition-colors ${view === v.value ? "bg-surface-2 text-accent" : "text-text-secondary"}`}
            >
              {v.label}
            </button>
          ))}
        </div>
        <div className="flex items-center justify-between gap-2">
          <button type="button" aria-label="Previous" onClick={() => step(-1)} className="min-h-11 min-w-11 rounded-md border border-border text-text-secondary">
            ‹
          </button>
          <button type="button" onClick={() => setNav({ date: today })} className="min-h-11 flex-1 truncate rounded-md px-2 text-center text-sm font-medium text-text-primary" aria-label={`${label} — jump to today`}>
            {label}
          </button>
          <button type="button" aria-label="Next" onClick={() => step(1)} className="min-h-11 min-w-11 rounded-md border border-border text-text-secondary">
            ›
          </button>
        </div>
      </div>

      {phase && <PhaseBanner phase={phase} />}

      {cal.isError ? (
        <ErrorState message="Couldn't load the calendar." onRetry={() => cal.refetch()} />
      ) : !cal.data ? (
        <CardSkeleton lines={4} />
      ) : view === "week" ? (
        <WeekView
          days={cal.data.days}
          today={today}
          onOpenPlanned={openExisting}
          onAdd={openNew}
          onSelectDay={(d) => setNav({ view: "day", date: d })}
        />
      ) : view === "day" ? (
        day ? <DayView day={day} suggestions={cal.data.suggestions} onOpenPlanned={openExisting} onAdd={openNew} /> : <CardSkeleton lines={2} />
      ) : (
        <MonthView anchor={date} payload={cal.data} today={today} onSelectDay={(d) => setNav({ view: "day", date: d })} />
      )}

      {cal.data && view === "week" && cal.data.suggestions.length > 0 && (
        <p data-testid="week-suggestion-hint" className="rounded-md border border-accent/40 bg-accent/5 p-3 text-sm text-text-secondary">
          {cal.data.suggestions.length === 1 ? "A logged workout looks like a planned session." : `${cal.data.suggestions.length} logged workouts look like planned sessions.`} Open the day to link{" "}
          {cal.data.suggestions.length === 1 ? "it" : "them"} — nothing is linked automatically.
        </p>
      )}

      {summary.data && <WeekSummaryCard s={summary.data} />}

      <PlannedWorkoutSheet open={sheet.open} onOpenChange={(o) => setSheet((s) => ({ ...s, open: o }))} existing={sheet.existing} defaultDate={sheet.date} />
      <EventSheet open={eventSheet} onOpenChange={setEventSheet} existing={null} defaultDate={date} />
    </div>
  );
}
