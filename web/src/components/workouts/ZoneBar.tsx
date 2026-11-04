import { ZONE_NAMES, type ZoneName } from "../../lib/types";
import { zoneColor } from "../../lib/zoneColors";

/** A stacked time-in-zone bar (task Part E.4) — one segment per zone, width proportional to
 * seconds in that zone. Used both on workout detail (larger, with a legend) and compactly in
 * the Workouts list row. */
export function ZoneBar({
  zones,
  height = 8,
  showLegend = false,
}: {
  zones: Record<ZoneName, number> | null | undefined;
  height?: number;
  showLegend?: boolean;
}) {
  if (!zones) return null;
  const total = ZONE_NAMES.reduce((sum, z) => sum + (zones[z] || 0), 0);
  if (total <= 0) return null;

  return (
    <div>
      <div className="flex w-full overflow-hidden rounded-full" style={{ height }} role="img" aria-label={zoneSummaryLabel(zones)}>
        {ZONE_NAMES.map((z) => {
          const seconds = zones[z] || 0;
          if (seconds <= 0) return null;
          return <div key={z} style={{ width: `${(seconds / total) * 100}%`, background: zoneColor(z) }} title={`${z}: ${Math.round(seconds / 60)} min`} />;
        })}
      </div>
      {showLegend && (
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-tertiary">
          {ZONE_NAMES.filter((z) => (zones[z] || 0) > 0).map((z) => (
            <span key={z} className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ background: zoneColor(z) }} aria-hidden />
              {z} {Math.round((zones[z] || 0) / 60)}m
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function zoneSummaryLabel(zones: Record<ZoneName, number>): string {
  return (
    "Time in zone: " +
    ZONE_NAMES.filter((z) => (zones[z] || 0) > 0)
      .map((z) => `${z} ${Math.round((zones[z] || 0) / 60)} minutes`)
      .join(", ")
  );
}
