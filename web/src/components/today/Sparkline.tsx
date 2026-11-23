import { motion } from "framer-motion";
import { useMemo } from "react";
import { AreaGradient, areaPath, extent, linePath, summarize, useSvgId } from "../charts/core";
import type { BaselineBand, SparklinePoint } from "../../lib/types";
import { formatShortDate } from "../../lib/format";
import { useReducedMotion } from "../../lib/useReducedMotion";

const WIDTH = 280;
const HEIGHT = 56;
const PAD = 6;
const DAY_MS = 86_400_000;

/**
 * A compact trend: a smoothed line with a soft area under it, the person's baseline band behind, and the latest value as a dot.
 * Points sit at their dates (not evenly by index), so irregular readings — weigh-ins — keep their real spacing.
 */
export function Sparkline({
  points,
  baselineBand,
  color = "var(--accent)",
  label = "Recent trend",
  format = (v: number) => String(Math.round(v * 10) / 10),
}: {
  points: SparklinePoint[];
  baselineBand: BaselineBand | null;
  color?: string;
  label?: string;
  format?: (v: number) => string;
}) {
  const reduced = useReducedMotion();
  const gradId = useSvgId("spark");
  const geo = useMemo(() => {
    const defined = points.filter((p) => p.value != null);
    if (defined.length === 0) return null;
    const ms = defined.map((p) => new Date(p.date.length > 10 ? p.date : `${p.date}T00:00:00`).getTime());
    const values = defined.map((p) => p.value as number);
    const [vmin, vmax] = extent(baselineBand ? [...values, baselineBand.low, baselineBand.high] : values);
    const pad = (vmax - vmin) * 0.12 || 1;
    const lo = vmin - pad;
    const range = vmax + pad - lo;
    const t0 = ms[0];
    const span = Math.max(ms[ms.length - 1] - t0, DAY_MS);
    const x = (t: number) => PAD + ((t - t0) / span) * (WIDTH - PAD * 2);
    const y = (v: number) => HEIGHT - PAD - ((v - lo) / range) * (HEIGHT - PAD * 2);
    const xs = ms.map(x);
    const ys = values.map(y);
    return {
      line: linePath(xs, ys),
      area: xs.length > 1 ? areaPath(xs, ys, HEIGHT - PAD) : null,
      last: { x: xs[xs.length - 1], y: ys[ys.length - 1], point: defined[defined.length - 1] },
      band: baselineBand ? { y: y(baselineBand.high), h: Math.max(y(baselineBand.low) - y(baselineBand.high), 1) } : null,
      summary: summarize(label, values, format),
    };
  }, [points, baselineBand, label, format]);

  if (!geo) {
    return <div className="flex h-14 items-center text-xs text-text-tertiary">Not enough history yet.</div>;
  }

  return (
    <svg width="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="overflow-visible" role="img" aria-label={geo.summary}>
      <defs>
        <AreaGradient id={gradId} color={color} from={0.26} />
      </defs>
      {geo.band && <rect x={PAD} width={WIDTH - PAD * 2} y={geo.band.y} height={geo.band.h} rx={3} fill="var(--text-tertiary)" opacity={0.12} />}
      {geo.area && <path d={geo.area} fill={`url(#${gradId})`} />}
      <motion.path
        d={geo.line}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={reduced ? { pathLength: 1 } : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: reduced ? 0 : 0.9, ease: [0.16, 1, 0.3, 1] }}
      />
      <g>
        <circle cx={geo.last.x} cy={geo.last.y} r={6} fill={color} opacity={0.2} />
        <circle cx={geo.last.x} cy={geo.last.y} r={3.5} fill={color} stroke="var(--surface)" strokeWidth={1.5} />
        <title>{`${formatShortDate(geo.last.point.date)}: ${format(geo.last.point.value as number)}`}</title>
      </g>
    </svg>
  );
}
