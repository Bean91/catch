import { bandLabel } from "../../lib/format";

const BAND_COLOR_VAR: Record<string, string> = {
  green: "var(--band-green)",
  optimal: "var(--band-green)",
  light: "var(--band-green)",
  on_target: "var(--band-green)",
  yellow: "var(--band-yellow)",
  caution: "var(--band-yellow)",
  moderate: "var(--band-yellow)",
  undertraining: "var(--band-yellow)",
  below_target: "var(--band-yellow)",
  red: "var(--band-red)",
  high_risk: "var(--band-red)",
  high: "var(--band-red)",
  all_out: "var(--band-red)",
  well_below_target: "var(--band-red)",
  calibrating: "var(--band-calibrating)",
  insufficient_data: "var(--band-calibrating)",
};

export function BandBadge({ band, label }: { band: string | null | undefined; label?: string }) {
  const color = BAND_COLOR_VAR[band ?? "calibrating"] ?? "var(--band-calibrating)";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-1 text-xs font-medium text-text-primary">
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: color }} />
      {label ?? bandLabel(band)}
    </span>
  );
}
