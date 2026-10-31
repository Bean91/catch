import type { TrainingZones } from "../../lib/types";
import { formatNumber } from "../../lib/format";
import { zoneColor } from "../../lib/zoneColors";
import type { ZoneName } from "../../lib/types";

export function ZoneTable({ zones, currentZone }: { zones: TrainingZones; currentZone: string | null }) {
  return (
    <div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-text-tertiary">
            <th className="py-1 font-normal">Zone</th>
            <th className="py-1 font-normal">HR</th>
            <th className="py-1 font-normal">Power</th>
          </tr>
        </thead>
        <tbody>
          {zones.zones.map((z) => (
            <tr key={z.zone} className={z.zone === currentZone ? "text-text-primary" : "text-text-secondary"}>
              <td className="flex items-center gap-2 py-1.5">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: zoneColor(z.zone as ZoneName) }} aria-hidden />
                <span className={z.zone === currentZone ? "font-semibold" : ""}>{z.zone}</span>
              </td>
              <td className="font-mono-nums py-1.5">
                {z.hr_lo != null ? `${formatNumber(z.hr_lo)}${z.hr_hi != null ? `–${formatNumber(z.hr_hi)}` : "+"}` : "—"}
              </td>
              <td className="font-mono-nums py-1.5">
                {z.power_lo != null ? `${formatNumber(z.power_lo)}${z.power_hi != null ? `–${formatNumber(z.power_hi)}` : "+"}` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-text-tertiary">{zones.note}</p>
    </div>
  );
}
