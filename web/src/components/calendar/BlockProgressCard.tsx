import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchPhaseProgress } from "../../lib/api";
import { weekRangeLabel } from "../../lib/dates";
import { formatDuration, formatShortDate } from "../../lib/format";
import type { PlanPhase } from "../../lib/types";
import { PlanBar } from "../charts/PlanBar";
import { Card } from "../ui/Card";
import { ErrorState } from "../ui/EmptyState";
import { CardSkeleton } from "../ui/Skeleton";
import { formatMinutes, phaseKindLabel } from "./labels";

function km(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

/** One training block, week by week: completed against planned time (and the block's weekly target), plus the tests and pieces
 * done inside it. Neutral throughout — planned is an intention, a future week has nothing completed yet, and no week is "behind". */
export function BlockProgressCard({ phase }: { phase: PlanPhase }) {
  const q = useQuery({ queryKey: ["phase-progress", phase.id], queryFn: () => fetchPhaseProgress(phase.id) });
  if (q.isError) return <ErrorState message="Couldn't load this block." onRetry={() => q.refetch()} />;
  if (!q.data) return <CardSkeleton lines={4} />;
  const d = q.data;
  const max = Math.max(1, ...d.weeks.map((w) => Math.max(w.planned.minutes, w.completed?.minutes ?? 0, d.targets.minutes ?? 0)));
  return (
    <Card material="solid" title={`Block: ${phase.name}`} eyebrow={phase.category ?? phaseKindLabel(phase.kind)} testId="block-progress">
      <p className="text-sm text-text-secondary">
        {formatShortDate(phase.start_date)} – {formatShortDate(phase.end_date)} · week {Math.min(d.totals.weeks_elapsed, d.totals.weeks_total)} of {d.totals.weeks_total}
      </p>
      <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
        <div className="min-w-0">
          <dt className="text-xs text-text-tertiary">Completed so far</dt>
          <dd className="font-mono-nums font-medium text-text-primary">{formatMinutes(d.totals.completed_minutes)}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-xs text-text-tertiary">Sessions</dt>
          <dd className="font-mono-nums font-medium text-text-primary">{d.totals.completed_sessions}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-xs text-text-tertiary">Distance</dt>
          <dd className="font-mono-nums font-medium text-text-primary">{km(d.totals.completed_distance_m)}</dd>
        </div>
      </dl>
      <ul className="mt-4 flex flex-col gap-3" data-testid="block-weeks">
        {d.weeks.map((w) => {
          const done = w.completed?.minutes ?? 0;
          return (
            <li key={w.week_start} className="flex flex-col gap-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-2 text-sm">
                <span className={w.state === "current" ? "font-medium text-text-primary" : "text-text-secondary"}>
                  {weekRangeLabel(w.week_start)}
                  {w.state === "current" ? " · this week" : ""}
                </span>
                <span className="font-mono-nums text-text-secondary">
                  {w.completed ? `${formatMinutes(done)} / ` : ""}
                  {formatMinutes(w.planned.minutes)} planned
                </span>
              </div>
              <PlanBar
                planned={w.planned.minutes}
                completed={done}
                target={d.targets.minutes ?? null}
                max={max}
                label={w.completed ? `${formatMinutes(done)} completed of ${formatMinutes(w.planned.minutes)} planned` : `${formatMinutes(w.planned.minutes)} planned; this week hasn't started`}
              />
              {w.completed && (
                <p className="text-xs text-text-tertiary">
                  {w.completed.sessions} session{w.completed.sessions === 1 ? "" : "s"}
                  {w.completed.distance_m > 0 ? ` · ${km(w.completed.distance_m)}` : ""}
                  {w.completed.zone_pct && w.completed.zone_pct.UT2 != null ? ` · ${Math.round(w.completed.zone_pct.UT2)}% UT2` : ""}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {d.efforts.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <h4 className="text-xs font-medium uppercase tracking-wide text-text-tertiary">Tests and pieces in this block</h4>
          <ul className="mt-2 flex flex-col gap-1.5 text-sm">
            {d.efforts.map((e, i) => (
              <li key={i} className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                <Link to={e.piece_id != null ? `/tests/piece/${e.piece_id}` : `/tests/${e.canonical_id}`} className="min-w-0 wrap-anywhere text-accent underline">
                  {e.test_type ?? e.title ?? "Effort"}
                </Link>
                <span className="font-mono-nums text-text-secondary">{formatDuration(e.duration_s)}</span>
                <span className="text-xs text-text-tertiary">
                  {formatShortDate(e.date)} · {e.kind === "piece" ? "piece" : "test"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="mt-3 text-xs text-text-tertiary">Filled bar: completed. Outlined bar: planned. Dashed line: the block's weekly target.</p>
    </Card>
  );
}
