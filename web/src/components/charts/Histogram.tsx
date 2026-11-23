import { useMemo } from "react";
import { ValueBars } from "./ValueBars";

/** Equal-width bins over the values' 1st–99th percentile (one spike can't stretch the axis); counts as a share of the total. */
export function binValues(values: number[], bins = 12): { lo: number; hi: number; count: number }[] {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (v.length === 0) return [];
  const lo = v[Math.floor(v.length * 0.01)];
  const hi = v[Math.min(v.length - 1, Math.ceil(v.length * 0.99) - 1)];
  const width = (hi - lo) / bins || 1;
  const out = Array.from({ length: bins }, (_, i) => ({ lo: lo + i * width, hi: lo + (i + 1) * width, count: 0 }));
  for (const x of v) {
    if (x < lo || x > hi) continue;
    out[Math.min(Math.floor((x - lo) / width), bins - 1)].count++;
  }
  return out;
}

/** How a measurement was distributed over a session (heart rate, split) — share of the session in each bin. */
export function Histogram({
  values,
  bins = 12,
  format,
  color,
  ariaLabel,
  height = 170,
}: {
  values: number[];
  bins?: number;
  format: (v: number) => string;
  color: string;
  ariaLabel: string;
  height?: number;
}) {
  const data = useMemo(() => binValues(values, bins), [values, bins]);
  const total = data.reduce((a, b) => a + b.count, 0);
  if (total < 5) return <p className="text-sm text-text-tertiary">Not enough data for a distribution.</p>;
  return (
    <ValueBars
      bars={data.map((b, i) => ({ key: i, label: format(b.lo), title: `${format(b.lo)}–${format(b.hi)}`, value: (b.count / total) * 100 }))}
      format={(v) => `${Math.round(v)}%`}
      zeroBased
      showValues={false}
      color={color}
      height={height}
      ariaLabel={ariaLabel}
    />
  );
}
