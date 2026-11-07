import { formatNumber } from "../../lib/format";
import { ZONE_NAMES, zoneColor } from "../../lib/zoneColors";
import { EmptyState } from "../ui/EmptyState";
import type { TrainingDistributionWeek } from "../../lib/types";

/** A static, non-zoomable stacked-bar summary — deliberately not WeeklyVolumeBars.tsx
 * (that component's controlled pan/zoom domain is built for Trends' own interactive chart;
 * plumbing that machinery in here for a secondary summary card would be a lot of state for
 * no real benefit, the same reasoning SplitBarChart.tsx already gives for staying simple). */
export function TrainingDistributionCard({ weeks }: { weeks: TrainingDistributionWeek[] }) {
  const totalSeconds = weeks.reduce((sum, w) => sum + ZONE_NAMES.reduce((s, z) => s + (w.zones[z] ?? 0), 0), 0);
  if (totalSeconds === 0) {
    return <EmptyState message="No training volume in this window yet." />;
  }
  const totalStrengthMinutes = weeks.reduce((sum, w) => sum + (w.strength_minutes ?? 0), 0);
  const zoneTotals = ZONE_NAMES.map((z) => ({
    zone: z,
    seconds: weeks.reduce((sum, w) => sum + (w.zones[z] ?? 0), 0),
  }));

  return (
    <div>
      <div className="flex h-6 w-full overflow-hidden rounded-md">
        {zoneTotals.map(({ zone, seconds }) =>
          seconds > 0 ? (
            <div key={zone} style={{ width: `${(seconds / totalSeconds) * 100}%`, background: zoneColor(zone) }} title={`${zone}: ${formatNumber((seconds / totalSeconds) * 100)}%`} />
          ) : null
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-3">
        {zoneTotals.map(({ zone, seconds }) => (
          <div key={zone} className="flex items-center gap-1.5 text-xs text-text-secondary">
            <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: zoneColor(zone) }} />
            {zone} {formatNumber((seconds / totalSeconds) * 100)}%
          </div>
        ))}
      </div>
      {totalStrengthMinutes > 0 && <p className="mt-3 text-xs text-text-tertiary">Plus {formatNumber(totalStrengthMinutes)} minutes of strength work.</p>}
    </div>
  );
}
