import { formatDistance, formatSplit } from "../../lib/format";
import type { PerformanceTrendBucket } from "../../lib/types";

const WIDTH = 320;
const HEIGHT = 140;
const PAD = 24;

/** Best/typical/recent as three static bars, one per equivalence bucket — the same
 * dependency-free, non-zoomable-SVG pattern as SplitBarChart.tsx (components/tests/
 * SplitBarChart.tsx): three points is nothing to pan or zoom into, and this reuses that
 * component's exact "faster/more reads taller" convention rather than inventing a new one.
 * `kind === "distance"` buckets (500m..6000m) compare pace (lower is better, taller bar);
 * `kind === "duration"` buckets (30min_r20, 60min) compare distance covered (higher is
 * better, taller bar) — see catch/analytics/training_intelligence.py's _metric_for_row. */
export function PieceTrendMiniChart({ bucket }: { bucket: PerformanceTrendBucket }) {
  if (!bucket.best || !bucket.typical || !bucket.recent) {
    return <p className="text-sm text-text-tertiary">No usable pieces of this type yet.</p>;
  }
  const lowerIsBetter = bucket.kind === "distance";
  const points = [
    { label: "Best", value: bucket.best.value },
    { label: "Typical", value: bucket.typical.value },
    { label: "Recent", value: bucket.recent.value },
  ];
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const plotH = HEIGHT - PAD * 2;
  const barH = (v: number) => {
    const frac = lowerIsBetter ? (max - v) / range : (v - min) / range;
    return frac * plotH + 6;
  };
  const barW = (WIDTH - PAD * 2) / points.length;
  const formatValue = (v: number) => (lowerIsBetter ? formatSplit(v) : formatDistance(v));

  return (
    <div>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" role="img" aria-label={`${bucket.bucket_label} best, typical, and recent`}>
        {points.map((p, i) => {
          const x = PAD + i * barW;
          const h = barH(p.value);
          return (
            <g key={p.label}>
              <rect x={x + 6} y={PAD + plotH - h + 6} width={barW - 12} height={h} rx={3} fill="var(--accent)" opacity={i === 2 ? 1 : 0.55} />
              <text x={x + barW / 2} y={HEIGHT - 6} textAnchor="middle" className="fill-[var(--text-tertiary)] text-[10px]">
                {p.label}
              </text>
              <text x={x + barW / 2} y={PAD + plotH - h - 2} textAnchor="middle" className="font-mono-nums fill-[var(--text-primary)] text-[10px]">
                {formatValue(p.value)}
              </text>
            </g>
          );
        })}
      </svg>
      {bucket.rate_note && <p className="mt-1 text-xs text-text-tertiary">{bucket.rate_note}</p>}
      {bucket.drag_note && <p className="mt-1 text-xs text-text-tertiary">{bucket.drag_note}</p>}
    </div>
  );
}
