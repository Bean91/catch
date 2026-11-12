import { Link } from "react-router-dom";
import type { CalendarCompleted, PlannedWorkout, UpcomingEvent } from "../../lib/types";
import { eventTypeLabel, formatDistance, formatMinutes, plannedMeta, STATUS_STYLE } from "./labels";

export function PlannedSessionChip({ p, onOpen }: { p: PlannedWorkout; onOpen: (p: PlannedWorkout) => void }) {
  const s = STATUS_STYLE[p.display_status];
  return (
    <button
      type="button"
      onClick={() => onOpen(p)}
      data-testid="planned-chip"
      data-status={p.display_status}
      className={`flex min-h-11 w-full items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-sm transition-colors hover:border-accent/60 ${s.cls}`}
    >
      <span aria-hidden className="w-4 shrink-0 text-center font-mono-nums">
        {s.glyph}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{p.title}</span>
        {p.display_status !== "rest" && <span className="block truncate text-xs text-text-tertiary">{plannedMeta(p) || "No details yet"}</span>}
      </span>
      <span className="shrink-0 text-xs text-text-tertiary">{s.label}</span>
    </button>
  );
}

export function CompletedChip({ c }: { c: CalendarCompleted }) {
  return (
    <Link
      to={`/workouts/${c.id}`}
      data-testid="completed-chip"
      className="flex min-h-11 w-full items-center gap-2 rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm text-text-primary transition-colors hover:border-accent/60"
    >
      <span aria-hidden className="w-4 shrink-0 text-center font-mono-nums">
        ●
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{c.title ?? "Workout"}</span>
        <span className="block truncate text-xs text-text-tertiary">
          {[formatMinutes(c.duration_min), formatDistance(c.distance_m), c.is_test ? "test" : null].filter(Boolean).join(" · ")}
        </span>
      </span>
      <span className="shrink-0 text-xs text-text-tertiary">Completed</span>
    </Link>
  );
}

export function EventChip({ e }: { e: UpcomingEvent }) {
  return (
    <Link
      to={`/calendar/events/${e.id}`}
      data-testid="event-chip"
      className="flex min-h-11 w-full items-center gap-2 rounded-md border border-accent/50 bg-transparent px-2.5 py-1.5 text-sm text-text-primary transition-colors hover:bg-accent/10"
    >
      <span aria-hidden className="w-4 shrink-0 text-center text-accent">
        ◆
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{e.name}</span>
        <span className="block truncate text-xs text-text-tertiary">
          {eventTypeLabel(e.type)}
          {e.priority ? ` · ${e.priority} priority` : ""}
        </span>
      </span>
      <span className="shrink-0 text-xs text-text-tertiary">Event</span>
    </Link>
  );
}
