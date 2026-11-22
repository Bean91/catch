import { ZONE_NAMES, type ZoneName } from "../../lib/types";
import { zoneColor } from "../../lib/zoneColors";
import { StackedBar } from "../charts/StackedBar";

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
  return (
    <StackedBar
      height={height}
      legend={showLegend}
      summary={zoneSummaryLabel(zones)}
      segments={ZONE_NAMES.map((z) => ({ key: z, label: z, value: zones[z] || 0, color: zoneColor(z), detail: `${Math.round((zones[z] || 0) / 60)}m` }))}
    />
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
