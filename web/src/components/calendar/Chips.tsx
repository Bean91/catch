import { Link } from "react-router-dom";
import type { CalendarCompleted, PlannedWorkout, UpcomingEvent } from "../../lib/types";
import { eventTypeLabel, formatDistance, formatMinutes, plannedMeta, sportColor, STATUS_STYLE } from "./labels";

export function PlannedSessionChip({ p, onOpen }: { p: PlannedWorkout; onOpen: (p: PlannedWorkout) => void }) {
  const s = STATUS_STYLE[p.display_status];
  return (
    <button
      type="button"
      onClick={() => onOpen(p)}
      data-testid="planned-chip"
      data-status={p.display_status}
      className={`flex min-h-11 w-full items-center gap-2.5 rounded-md border px-2.5 py-1.5 text-left text-sm transition-colors hover:border-accent/60 ${s.cls}`}
    >
      <span aria-hidden className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono-nums text-xs ${p.display_status === "planned" ? "bg-accent/15 text-accent" : p.display_status === "linked" ? "bg-band-green/15 text-band-green" : "text-text-tertiary"}`}>
        {s.glyph}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{p.title}</span>
        {p.display_status !== "rest" && <span className="block truncate text-xs text-text-tertiary">{plannedMeta(p) || "No details yet"}</span>}
      </span>
      <span className="shrink-0 rounded-full bg-surface/60 px-2 py-0.5 text-[11px] font-medium text-text-secondary">{s.label}</span>
    </button>
  );
}

export function CompletedChip({ c }: { c: CalendarCompleted }) {
  return (
    <Link
      to={`/workouts/${c.id}`}
      data-testid="completed-chip"
      className="relative flex min-h-11 w-full items-center gap-2.5 overflow-hidden rounded-md border border-border bg-surface-2 py-1.5 pl-3.5 pr-2.5 text-sm text-text-primary transition-colors hover:border-accent/60"
    >
      <span aria-hidden className="absolute inset-y-0 left-0 w-1" style={{ background: sportColor(c) }} />
      <span aria-hidden className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono-nums text-xs" style={{ background: `color-mix(in oklab, ${sportColor(c)} 18%, transparent)`, color: sportColor(c) }}>
        ●
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{c.title ?? "Workout"}</span>
        <span className="block truncate text-xs text-text-tertiary">
          {[formatMinutes(c.duration_min), formatDistance(c.distance_m), c.is_test ? "test" : null].filter(Boolean).join(" · ")}
        </span>
      </span>
      <span className="shrink-0 rounded-full bg-surface/60 px-2 py-0.5 text-[11px] font-medium text-text-secondary">Completed</span>
    </Link>
  );
}

export function EventChip({ e }: { e: UpcomingEvent }) {
  return (
    <Link
      to={`/calendar/events/${e.id}`}
      data-testid="event-chip"
      className="flex min-h-11 w-full items-center gap-2.5 rounded-md border border-accent/50 bg-[linear-gradient(90deg,var(--accent-soft),transparent)] px-2.5 py-1.5 text-sm text-text-primary transition-colors hover:bg-accent/10"
    >
      <span aria-hidden className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent text-[10px] text-accent-contrast">
        ◆
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{e.name}</span>
        <span className="block truncate text-xs text-text-tertiary">
          {eventTypeLabel(e.type)}
          {e.priority ? ` · ${e.priority} priority` : ""}
        </span>
      </span>
      <span className="shrink-0 rounded-full bg-surface/60 px-2 py-0.5 text-[11px] font-medium text-text-secondary">Event</span>
    </Link>
  );
}
