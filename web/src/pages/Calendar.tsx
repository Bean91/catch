import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PhaseBanner, WeekSummaryCard } from "../components/calendar/WeekSummaryCard";
import { AgendaView, DayView, MonthView, NavLinks, WeekView } from "../components/calendar/Views";
import { MonthSummaryCard } from "../components/calendar/MonthSummaryCard";
import { Button, IconButton } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";
import { Segmented } from "../components/ui/Segmented";
import { EventSheet } from "../components/calendar/EventSheet";
import { PlannedWorkoutSheet } from "../components/calendar/PlannedWorkoutSheet";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { fetchCalendar, fetchPlanWeekSummary } from "../lib/api";
import { addDays, addMonths, dayLabel, monthGrid, monthLabel, parseISODate, todayISO, weekRangeLabel, weekStart } from "../lib/dates";
import type { PlannedWorkout } from "../lib/types";
import { downloadCalendarIcs } from "../lib/privacy";

type View = "day" | "week" | "month" | "agenda";
const VIEWS: { value: View; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "agenda", label: "Agenda" },
];

function rangeFor(view: View, date: string): [string, string] {
  if (view === "day") return [date, date];
  if (view === "agenda") return [date, addDays(date, 27)];
  if (view === "week") {
    const s = weekStart(date);
    return [s, addDays(s, 6)];
  }
  const d = parseISODate(date);
  const grid = monthGrid(d.getFullYear(), d.getMonth());
  return [grid[0][0], grid[grid.length - 1][6]];
}

/** Session 36 follow-up: planned sessions and events as an .ics file. */
function CalendarDownload() {
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const run = async () => {
    setState("busy");
    try {
      await downloadCalendarIcs();
      setState("idle");
    } catch {
      setState("error");
    }
  };
  return (
    <div className="glass-subtle flex flex-col gap-2 rounded-lg border border-border bg-surface/60 p-3 text-sm text-text-secondary sm:flex-row sm:items-center sm:justify-between" data-testid="calendar-download">
      <p>
        Put your plans in another calendar app: a file of planned sessions and events from 30 days ago to a year ahead. Importing a newer file updates the same
        entries.{state === "error" ? " The download didn't work — try again." : ""}
      </p>
      <Button size="sm" loading={state === "busy"} onClick={run} className="shrink-0">
        Download .ics
      </Button>
    </div>
  );
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

  const step = (dir: -1 | 1) =>
    setNav({ date: view === "month" ? addMonths(date, dir) : addDays(date, dir * (view === "week" ? 7 : view === "agenda" ? 28 : 1)) });
  const label =
    view === "day" ? dayLabel(date) : view === "week" ? weekRangeLabel(weekISO) : view === "agenda" ? `${dayLabel(date)} + 4 weeks` : monthLabel(date);
  const phase = cal.data?.phases.find((p) => p.start_date <= date && date <= p.end_date) ?? null;
  const openNew = (d: string) => setSheet({ open: true, existing: null, date: d });
  const openExisting = (p: PlannedWorkout) => setSheet({ open: true, existing: p, date: p.date });
  const day = cal.data?.days.find((d) => d.date === date);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow="Plan"
        title="Calendar"
        actions={
          <>
            <Button size="sm" onClick={() => setEventSheet(true)}>
              + Event
            </Button>
            <Button size="sm" variant="primary" onClick={() => openNew(date)}>
              + Plan
            </Button>
          </>
        }
      />

      <NavLinks />

      <div className="glass-subtle flex flex-col gap-2 rounded-lg border border-border bg-surface/60 p-2 sm:flex-row sm:items-center sm:justify-between">
        <Segmented label="Calendar view" value={view} onChange={(v) => setNav({ view: v })} options={VIEWS} className="w-full sm:w-auto" stretch />
        <div className="flex items-center justify-between gap-1 sm:justify-end">
          <IconButton label="Previous" onClick={() => step(-1)}>
            <span aria-hidden className="text-xl leading-none">‹</span>
          </IconButton>
          <button
            type="button"
            onClick={() => setNav({ date: today })}
            className="min-h-11 min-w-0 flex-1 truncate rounded-md px-3 text-center text-sm font-semibold text-text-primary transition-colors hover:bg-surface-2 sm:flex-none"
            aria-label={`${label} — jump to today`}
          >
            {label}
          </button>
          <IconButton label="Next" onClick={() => step(1)}>
            <span aria-hidden className="text-xl leading-none">›</span>
          </IconButton>
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
        // A day the payload doesn't list (the server only returns days in range) is an empty day, not a loading one.
        <DayView day={day ?? { date, planned: [], completed: [], events: [], phase_id: null }} suggestions={cal.data.suggestions} onOpenPlanned={openExisting} onAdd={openNew} />
      ) : view === "agenda" ? (
        <AgendaView days={cal.data.days} today={today} onOpenPlanned={openExisting} onSelectDay={(d) => setNav({ view: "day", date: d })} />
      ) : (
        <MonthView anchor={date} payload={cal.data} today={today} onSelectDay={(d) => setNav({ view: "day", date: d })} />
      )}

      {cal.data && view === "week" && cal.data.suggestions.length > 0 && (
        <p data-testid="week-suggestion-hint" className="rounded-md border border-accent/40 bg-accent-soft p-3 text-sm text-text-secondary">
          {cal.data.suggestions.length === 1 ? "A logged workout looks like a planned session." : `${cal.data.suggestions.length} logged workouts look like planned sessions.`} Open the day to link{" "}
          {cal.data.suggestions.length === 1 ? "it" : "them"} — nothing is linked automatically.
        </p>
      )}

      {view === "month" ? <MonthSummaryCard month={date.slice(0, 7)} /> : summary.data && <WeekSummaryCard s={summary.data} />}

      <CalendarDownload />

      <PlannedWorkoutSheet open={sheet.open} onOpenChange={(o) => setSheet((s) => ({ ...s, open: o }))} existing={sheet.existing} defaultDate={sheet.date} />
      <EventSheet open={eventSheet} onOpenChange={setEventSheet} existing={null} defaultDate={date} />
    </div>
  );
}
