import { Link } from "react-router-dom";
import type { WorkoutListItem } from "../../lib/types";
import { activityTypeLabel, bandLabel, formatDistance, formatDuration, formatShortDate, formatSplit } from "../../lib/format";
import { BandBadge } from "../ui/Badge";

export function WorkoutRow({ workout }: { workout: WorkoutListItem }) {
  const avgSplit = workout.category !== "other" && workout.duration && workout.distance ? (workout.duration / workout.distance) * 500 : null;

  return (
    <Link
      to={`/workouts/${workout.id}`}
      className="flex min-h-11 items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 transition-colors hover:border-accent/40 sm:gap-4 sm:px-5"
    >
      <div className="w-16 shrink-0 font-mono-nums text-xs text-text-tertiary sm:w-20 sm:text-sm">
        {workout.start ? formatShortDate(workout.start) : "—"}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-text-primary">{activityTypeLabel(workout.type)}</div>
        <div className="text-xs text-text-tertiary">{formatDistance(workout.distance)}</div>
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
    </Link>
  );
}
