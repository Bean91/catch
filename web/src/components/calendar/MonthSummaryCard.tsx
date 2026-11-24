import { useQuery } from "@tanstack/react-query";
import { fetchMonthSummary } from "../../lib/api";
import { PlanBar } from "../charts/PlanBar";
import { Card } from "../ui/Card";
import { CardSkeleton } from "../ui/Skeleton";
import { formatMinutes } from "./labels";

const SPORT_LABEL: Record<string, string> = { rowing: "Rowing", cycling: "Cycling", running: "Running", strength: "Strength", other: "Other" };

/** The month's completed training beside what was planned. Plain counts, no verdicts: days with nothing logged are a number, not a
 * "missed" list, and a plan never adds to the completed side. */
export function MonthSummaryCard({ month }: { month: string }) {
  const q = useQuery({ queryKey: ["month-summary", month], queryFn: () => fetchMonthSummary(month) });
  if (q.isError) return null;
  if (!q.data) return <CardSkeleton lines={2} />;
  const m = q.data;
  const sports = Object.entries(m.completed.minutes_by_sport).sort((a, b) => b[1] - a[1]);
  return (
    <Card material="solid" title="This month" testId="month-summary">
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div className="min-w-0">
          <dt className="text-xs text-text-tertiary">Trained</dt>
          <dd className="font-mono-nums font-medium text-text-primary">{formatMinutes(m.completed.minutes)}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-xs text-text-tertiary">Sessions</dt>
          <dd className="font-mono-nums font-medium text-text-primary">{m.completed.sessions}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-xs text-text-tertiary">Distance</dt>
          <dd className="font-mono-nums font-medium text-text-primary">{(m.completed.distance_m / 1000).toFixed(1)} km</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-xs text-text-tertiary">Days with training</dt>
          <dd className="font-mono-nums font-medium text-text-primary">
            {m.completed.training_days} of {m.days_elapsed}
          </dd>
        </div>
      </dl>
      {m.planned.minutes > 0 && (
        <div className="mt-3">
          <PlanBar planned={m.planned.minutes} completed={m.completed.minutes} max={Math.max(m.planned.minutes, m.completed.minutes)} label={`${formatMinutes(m.completed.minutes)} completed; ${formatMinutes(m.planned.minutes)} planned this month`} />
          <p className="mt-1 text-xs text-text-tertiary">
            {formatMinutes(m.planned.minutes)} planned across {m.planned.sessions} session{m.planned.sessions === 1 ? "" : "s"} — a plan is an intention, not training done.
          </p>
        </div>
      )}
      {sports.length > 1 && (
        <p className="mt-2 text-xs text-text-tertiary">{sports.map(([k, v]) => `${SPORT_LABEL[k] ?? k} ${formatMinutes(v)}`).join(" · ")}</p>
      )}
    </Card>
  );
}
