import { formatDistance, formatSplit } from "../../lib/format";
import { METRIC_COLOR } from "../../lib/metricColors";
import type { PerformanceTrendBucket } from "../../lib/types";
import { ValueBars } from "./ValueBars";


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
  const formatValue = (v: number) => (lowerIsBetter ? formatSplit(v) : formatDistance(v));

  return (
    <div>
      <ValueBars
        bars={points.map((p, i) => ({ key: p.label, label: p.label, value: p.value, emphasis: i === 2 ? true : false }))}
        format={formatValue}
        axis={lowerIsBetter ? "seconds" : "number"}
        invert={lowerIsBetter}
        color={lowerIsBetter ? METRIC_COLOR.pace : METRIC_COLOR.load}
        height={150}
        ariaLabel={`${bucket.bucket_label}: best ${formatValue(points[0].value)}, typical ${formatValue(points[1].value)}, recent ${formatValue(points[2].value)}`}
      />
      {bucket.rate_note && <p className="mt-1 text-xs text-text-tertiary">{bucket.rate_note}</p>}
      {bucket.drag_note && <p className="mt-1 text-xs text-text-tertiary">{bucket.drag_note}</p>}
    </div>
  );
}
