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
      <div className="w-16 shrink-0 font-mono-nums text-xs text-text-tertiary sm:w-20 sm:text-sm">
        {workout.start ? formatShortDate(workout.start) : "—"}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-text-primary">
          {workout.title ?? "Workout"}
          {workout.exclude_from_totals && <span className="ml-2 text-xs text-text-tertiary">(excluded)</span>}
        </div>
        <div className="text-xs text-text-tertiary">
          {formatDistance(workout.distance)}
          {workout.session_label && <span className="ml-2">{workout.session_label}</span>}
        </div>
        {workout.zones?.hr && (
          <div className="mt-1 max-w-[220px]">
            <ZoneBar zones={workout.zones.hr} height={4} />
          </div>
        )}
      </div>
      <div className="hidden w-20 shrink-0 text-right font-mono-nums text-sm text-text-secondary sm:block">
        {formatDuration(workout.duration)}
      </div>
      <div className="hidden w-24 shrink-0 text-right font-mono-nums text-sm text-text-secondary sm:block">
        {avgSplit ? `${formatSplit(avgSplit)}/500m` : "—"}
      </div>
      <div className="shrink-0">
        {workout.strain ? (
          <BandBadge band={workout.strain.band} label={bandLabel(workout.strain.band)} />
        ) : (
          <span className="text-xs text-text-tertiary">—</span>
        )}
      </div>
    </>
  );

  if (selectable) {
    return (
      <div className="flex min-h-11 items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 sm:gap-4 sm:px-5">
        {content}
      </div>
    );
  }

  return (
    <Link
      to={`/workouts/${workout.id}`}
      className="flex min-h-11 items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 transition-colors hover:border-accent/40 sm:gap-4 sm:px-5"
    >
      {content}
    </Link>
  );
}
