import type { HrBasis, TrainingZones } from "../../lib/types";
import { formatNumber, formatShortDate } from "../../lib/format";
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
      {zones.hr_basis && <p className="mt-2 text-xs text-text-secondary" data-testid="zone-basis">{describeHrBasis(zones.hr_basis)}</p>}
      <p className="mt-2 text-xs text-text-tertiary">{zones.note}</p>
    </div>
  );
}

/** One plain sentence: which method the heart-rate zones used and the resting/max heart rate behind them (session 33). */
export function describeHrBasis(b: HrBasis): string {
  if (b.method === "none") return b.reason ?? "No heart-rate zones without a max heart rate.";
  const max = `max ${formatNumber(b.max_hr)} bpm`;
  if (b.method === "max_pct") return `% of max heart rate (${max}).${b.reason ? ` ${b.reason}` : ""}`;
  const rest = formatNumber(b.resting_hr);
  const from =
    b.rhr_source === "setting"
      ? "your setting"
      : b.rhr_window
        ? `median of ${b.rhr_readings} mornings, ${formatShortDate(b.rhr_window[0])}–${formatShortDate(b.rhr_window[1])}${b.rhr_source === "measured_stale" ? ", the latest available" : ""}`
        : "measured";
  return `Heart-rate reserve: resting ${rest} bpm (${from}), ${max}.`;
}
