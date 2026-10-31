import { motion } from "framer-motion";
import type { BaselineBand, SparklinePoint } from "../../lib/types";
import { formatShortDate } from "../../lib/format";
import { useReducedMotion } from "../../lib/useReducedMotion";

const WIDTH = 280;
const HEIGHT = 56;
const PAD = 6;

export function Sparkline({
  points,
  baselineBand,
  color = "var(--accent)",
}: {
  points: SparklinePoint[];
  baselineBand: BaselineBand | null;
  color?: string;
}) {
  const reduced = useReducedMotion();
  const values = points.map((p) => p.value).filter((v): v is number => v != null);
  if (values.length === 0) {
    return <div className="flex h-14 items-center text-xs text-text-tertiary">Not enough history yet.</div>;
  }

  const allValues = baselineBand ? [...values, baselineBand.low, baselineBand.high] : values;
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const range = max - min || 1;

  const x = (i: number) => PAD + (i / Math.max(points.length - 1, 1)) * (WIDTH - PAD * 2);
  const y = (v: number) => HEIGHT - PAD - ((v - min) / range) * (HEIGHT - PAD * 2);

  const definedPoints = points.map((p, i) => ({ i, p })).filter((e) => e.p.value != null);
  const path = definedPoints.map(({ i, p }) => `${x(i)},${y(p.value as number)}`).join(" L ");
  const last = definedPoints[definedPoints.length - 1];

  return (
    <svg width="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="overflow-visible" role="img" aria-label="14 day trend">
      {baselineBand && (
        <rect
          x={PAD}
          width={WIDTH - PAD * 2}
          y={y(baselineBand.high)}
          height={Math.max(y(baselineBand.low) - y(baselineBand.high), 1)}
          fill="var(--text-tertiary)"
          opacity={0.14}
        />
      )}
      <motion.path
        d={`M ${path}`}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={reduced ? { pathLength: 1 } : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: reduced ? 0 : 0.9, ease: [0.16, 1, 0.3, 1] }}
      />
      {last && (
        <g>
          <circle cx={x(last.i)} cy={y(last.p.value as number)} r={4} fill={color} />
          <title>{`${formatShortDate(last.p.date)}: ${last.p.value}`}</title>
        </g>
      )}
    </svg>
  );
}
