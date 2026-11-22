import { Link } from "react-router-dom";
import type { WorkoutListItem } from "../../lib/types";
import { bandLabel, formatDistance, formatDuration, formatShortDate, formatSplit } from "../../lib/format";
import { BandBadge } from "../ui/Badge";
import { ZoneBar } from "./ZoneBar";

export function WorkoutRow({
  workout,
  selectable,
  selected,
  onToggleSelected,
}: {
  workout: WorkoutListItem;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelected?: (id: number) => void;
}) {
  const avgSplit = workout.category !== "other" && workout.duration && workout.distance ? (workout.duration / workout.distance) * 500 : null;

  const dateText = workout.local_date ? formatShortDate(workout.local_date) : workout.start ? formatShortDate(workout.start, workout.local_tz) : "—";
  const glyph = SPORT_GLYPH[workout.category === "erg" || workout.category === "on_water" ? "rowing" : workout.sport_family] ?? SPORT_GLYPH.other;

  // A container query, not the viewport: the same row sits in the full-width Workouts list and in narrow dashboard cards.
  const content = (
    <>
      {selectable && (
        <input
          type="checkbox"
          aria-label={`Select ${workout.title ?? "workout"}`}
          checked={!!selected}
          onChange={() => onToggleSelected?.(workout.id)}
          onClick={(e) => e.stopPropagation()}
          className="h-5 w-5 shrink-0 accent-accent"
        />
      )}
      <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-sm" style={{ background: `color-mix(in oklab, ${glyph.color} 16%, transparent)`, color: glyph.color }}>
        {glyph.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="min-w-0 truncate text-sm font-medium text-text-primary">{workout.title ?? "Workout"}</span>
          {workout.exclude_from_totals && <span className="shrink-0 text-xs text-text-tertiary">(excluded)</span>}
        </div>
        <div className="flex min-w-0 flex-wrap gap-x-2 text-xs text-text-tertiary">
          <span className="font-mono-nums">{dateText}</span>
          <span className="font-mono-nums">{formatDistance(workout.distance)}</span>
          <span className="font-mono-nums @md:hidden">{formatDuration(workout.duration)}</span>
          {workout.session_label && <span className="hidden truncate @sm:inline">{workout.session_label}</span>}
        </div>
        {workout.zones?.hr && (
          <div className="mt-1.5 max-w-[220px]">
            <ZoneBar zones={workout.zones.hr} height={4} />
          </div>
        )}
      </div>
      <div className="hidden w-16 shrink-0 text-right font-mono-nums text-sm text-text-secondary @md:block">{formatDuration(workout.duration)}</div>
      <div className="hidden w-24 shrink-0 text-right font-mono-nums text-sm text-text-secondary @lg:block">{avgSplit ? `${formatSplit(avgSplit)}/500m` : "—"}</div>
      <div className="shrink-0">
        {workout.strain ? <BandBadge band={workout.strain.band} label={bandLabel(workout.strain.band)} /> : <span className="text-xs text-text-tertiary">—</span>}
      </div>
    </>
  );

  if (selectable) {
    return (
      <div className="@container">
        <div className="flex min-h-11 items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2.5 shadow-[var(--highlight),var(--shadow-1)] sm:px-4">{content}</div>
      </div>
    );
  }

  return (
    <div className="@container">
      <Link
        to={`/workouts/${workout.id}`}
        className="flex min-h-11 items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2.5 shadow-[var(--highlight),var(--shadow-1)] transition-[border-color,background-color] hover:border-accent/40 hover:bg-surface-2/40 sm:px-4"
      >
        {content}
      </Link>
    </div>
  );
}

const svg = (d: string) => (
  <svg viewBox="0 0 20 20" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

const SPORT_GLYPH: Record<string, { icon: React.ReactNode; color: string }> = {
  rowing: { icon: svg("M3 8c2.3-1.6 4.7-1.6 7 0s4.7 1.6 7 0M3 13c2.3-1.6 4.7-1.6 7 0s4.7 1.6 7 0"), color: "var(--metric-pace)" },
  cycling: { icon: svg("M6 14.5a3 3 0 1 0 0-.01M14 14.5a3 3 0 1 0 0-.01M6 14.5l3-6h4l1 6M9 8.5h-1.5"), color: "var(--metric-power)" },
  running: { icon: svg("M12 4.5a1.2 1.2 0 1 0 0-.01M8 16l2.5-4 2.5 2v3M6.5 10l3-2.5 3 1 2 2.5"), color: "var(--metric-hr)" },
  strength: { icon: svg("M3 10h14M5.5 7v6M14.5 7v6M3 8.5v3M17 8.5v3"), color: "var(--metric-rate)" },
  other: { icon: svg("M10 6v8M6 10h8"), color: "var(--text-secondary)" },
};
