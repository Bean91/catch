import { formatSpeedKmh } from "../../lib/gpsFormat";
import { METRIC_COLOR } from "../../lib/metricColors";
import type { RouteHistory } from "../../lib/types";
import { ValueBars } from "../charts/ValueBars";


/** A static count-per-bin chart of each session's average moving speed — dependency-free SVG, no
 * pan/zoom (the PieceTrendMiniChart precedent). The summary figures and every bar's count are
 * also in text, so nothing depends on seeing the bars. */
export function SpeedHistogram({ dist }: { dist: NonNullable<RouteHistory["stats"]["speed_distribution"]> }) {
  const bins = dist.histogram;
  if (bins.length === 0) return <p className="text-sm text-text-tertiary">Not enough sessions for a distribution yet.</p>;
  return (
    <div>
      <ValueBars
        testId="speed-histogram"
        bars={bins.map((b, i) => ({ key: i, label: i === 0 ? formatSpeedKmh(dist.min) : i === bins.length - 1 ? formatSpeedKmh(dist.max) : "", value: b.count }))}
        format={(v) => String(Math.round(v))}
        zeroBased
        color={METRIC_COLOR.pace}
        height={130}
        ariaLabel={`Distribution of average speed across ${dist.n} sessions`}
      />
      <p className="mt-1 text-xs text-text-tertiary">
        {dist.n} session{dist.n === 1 ? "" : "s"}: median {formatSpeedKmh(dist.median)} (middle half {formatSpeedKmh(dist.p25)}–{formatSpeedKmh(dist.p75)}). {dist.basis}.
      </p>
    </div>
  );
}
