import { motion } from "framer-motion";
import type { Stroke } from "../../lib/types";
import { hrZoneForHr } from "../../lib/hrZone";
import { zoneColor } from "../../lib/zoneColors";
import type { ZoneName } from "../../lib/types";
import { useReducedMotion } from "../../lib/useReducedMotion";
import { EmptyState } from "../ui/EmptyState";

const WIDTH = 640;
const HEIGHT = 260;
const PAD_X = 12;
const PAD_TOP = 12;
const BAND_HEIGHT = 14;
const PAD_BOTTOM = BAND_HEIGHT + 8;
const PLOT_HEIGHT = HEIGHT - PAD_TOP - PAD_BOTTOM;

function scaleY(values: number[]): (v: number) => number {
  if (values.length === 0) return () => PAD_TOP + PLOT_HEIGHT;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return (v: number) => PAD_TOP + PLOT_HEIGHT - ((v - min) / range) * PLOT_HEIGHT;
}

function linePath(points: Stroke[], x: (d: number) => number, y: (v: number) => number, key: "pace_500m" | "watts" | "stroke_rate"): string {
  const defined = points.filter((s) => s.distance_cum != null && s[key] != null);
  return defined.map((s) => `${x(s.distance_cum as number)},${y(s[key] as number)}`).join(" L ");
}

// split/500m and pace read better "lower = faster", so this line is flipped: faster splits
// sit higher on the chart, same visual direction as watts/rate (higher = harder).
function invertedScaleY(values: number[]): (v: number) => number {
  if (values.length === 0) return () => PAD_TOP + PLOT_HEIGHT;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return (v: number) => PAD_TOP + ((v - min) / range) * PLOT_HEIGHT;
}

export function ErgChart({ strokes, maxHr, hrPct }: { strokes: Stroke[]; maxHr: number | null; hrPct: Record<string, number> }) {
  const reduced = useReducedMotion();
  const withDistance = strokes.filter((s) => s.distance_cum != null).sort((a, b) => (a.distance_cum ?? 0) - (b.distance_cum ?? 0));

  if (withDistance.length < 2) {
    return <EmptyState message="Not enough per-stroke data to chart (Garmin-only erg sessions have no stroke-level data)." />;
  }

  const maxDistance = withDistance[withDistance.length - 1].distance_cum as number;
  const x = (d: number) => PAD_X + (d / maxDistance) * (WIDTH - PAD_X * 2);

  const splitValues = withDistance.map((s) => s.pace_500m).filter((v): v is number => v != null);
  const wattsValues = withDistance.map((s) => s.watts).filter((v): v is number => v != null);
  const rateValues = withDistance.map((s) => s.stroke_rate).filter((v): v is number => v != null);
  const ySplit = invertedScaleY(splitValues);
  const yWatts = scaleY(wattsValues);
  const yRate = scaleY(rateValues);

  const bandSegments: { zone: ZoneName | null; x0: number; x1: number }[] = [];
  let prevZone: ZoneName | null = null;
  let segStart = 0;
  withDistance.forEach((s, i) => {
    const zone = hrZoneForHr(s.hr, maxHr, hrPct) as ZoneName | null;
    const d = s.distance_cum as number;
    if (zone !== prevZone) {
      if (prevZone != null) bandSegments.push({ zone: prevZone, x0: segStart, x1: d });
      segStart = d;
      prevZone = zone;
    }
    if (i === withDistance.length - 1 && prevZone != null) bandSegments.push({ zone: prevZone, x0: segStart, x1: d });
  });

  const lines: { key: "pace_500m" | "watts"; color: string; y: (v: number) => number; label: string; dashed?: boolean }[] = [
    { key: "pace_500m", color: "var(--accent)", y: ySplit, label: "Split" },
    { key: "watts", color: "var(--text-secondary)", y: yWatts, label: "Watts", dashed: true },
  ];
  // Rate is whole-number spm per stroke — a connected line through a value that only ever
  // steps between a handful of integers, independently auto-scaled to fill the chart height,
  // reads as a harsh zigzag rather than a trend. Small dots show the same data without that.
  const rateDots = withDistance.filter((s) => s.stroke_rate != null);

  return (
    <div>
      <svg width="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Split, watts and stroke rate over distance">
        {rateDots.map((s, i) => (
          <circle key={i} cx={x(s.distance_cum as number)} cy={yRate(s.stroke_rate as number)} r={1.6} fill="var(--text-tertiary)" opacity={0.6} />
        ))}
        {lines.map((line) => (
          <motion.path
            key={line.key}
            d={`M ${linePath(withDistance, x, line.y, line.key)}`}
            fill="none"
            stroke={line.color}
            strokeWidth={line.key === "pace_500m" ? 2.5 : 1.5}
            strokeDasharray={line.dashed ? "3 3" : undefined}
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduced ? { pathLength: 1 } : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: reduced ? 0 : 1, ease: [0.16, 1, 0.3, 1] }}
          />
        ))}
        {/* HR zone band beneath the lines, in distance order */}
        {bandSegments.map((seg, i) =>
          seg.zone ? (
            <rect
              key={i}
              x={x(seg.x0)}
              width={Math.max(x(seg.x1) - x(seg.x0), 1)}
              y={HEIGHT - BAND_HEIGHT}
              height={BAND_HEIGHT}
              fill={zoneColor(seg.zone)}
            />
          ) : null,
        )}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-tertiary">
        {lines.map((line) => (
          <span key={line.key} className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full" style={{ background: line.color }} />
            {line.label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--text-tertiary)" }} />
          Rate (spm)
        </span>
        <span className="ml-auto">band beneath = HR zone</span>
      </div>
    </div>
  );
}
