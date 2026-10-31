import type { ErgTechnique } from "../../lib/types";
import { formatNumber } from "../../lib/format";

// Technique bands (consistent/variable, efficient/inefficient, held_pace/faded) aren't one
// of the app's three reserved recovery/strain/load signals, so they're shown as plain text,
// not a BandBadge — same reasoning session 3 applied to sleep-stage colors.
function techniqueBandLabel(band: string): string {
  return band.replace(/_/g, " ");
}

const METRIC_LABELS: { key: keyof ErgTechnique; label: string; suffix?: string }[] = [
  { key: "split_consistency", label: "Split consistency", suffix: "% CV" },
  { key: "watts_per_stroke", label: "Watts/stroke" },
  { key: "rate_power_slope", label: "Rate/power slope" },
  { key: "fade", label: "Fade", suffix: "%" },
];

export function TechniqueGrid({ technique }: { technique: ErgTechnique }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {METRIC_LABELS.map(({ key, label, suffix }) => {
        const metric = technique[key];
        return (
          <div key={key} className="rounded-md bg-surface-2 px-3 py-2.5">
            <div className="text-xs text-text-tertiary">{label}</div>
            <div className="mt-1 font-mono-nums text-lg font-medium text-text-primary">
              {metric.value != null ? `${formatNumber(metric.value, 1)}${suffix ?? ""}` : "—"}
            </div>
            {metric.band !== "n/a" && metric.band !== "insufficient_data" && (
              <div className="mt-1 text-xs capitalize text-text-tertiary">{techniqueBandLabel(metric.band)}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
