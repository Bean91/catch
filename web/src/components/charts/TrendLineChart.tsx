import { motion } from "framer-motion";
import type { TrendPoint } from "../../lib/types";
import { formatShortDate } from "../../lib/format";
import { useReducedMotion } from "../../lib/useReducedMotion";

const WIDTH = 600;
const HEIGHT = 220;
const PAD_X = 12;
const PAD_TOP = 16;
const PAD_BOTTOM = 28;

interface Series {
  points: { date: string; value: number | null }[];
  color: string;
  dashed?: boolean;
}

export function TrendLineChart({
  points,
  secondary,
  color = "var(--accent)",
  formatValue = (v: number) => v.toFixed(0),
}: {
  points: TrendPoint[];
  secondary?: { date: string; value: number | null }[];
  color?: string;
  formatValue?: (value: number) => string;
}) {
  const reduced = useReducedMotion();
  const series: Series[] = [{ points, color }, ...(secondary ? [{ points: secondary, color: "var(--text-secondary)", dashed: true }] : [])];
  const allValues = series.flatMap((s) => s.points.map((p) => p.value)).filter((v): v is number => v != null);

  if (allValues.length === 0) {
    return <div className="flex h-40 items-center justify-center text-sm text-text-tertiary">Not enough history yet.</div>;
  }

  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const range = max - min || 1;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;

  const x = (i: number, n: number) => PAD_X + (i / Math.max(n - 1, 1)) * (WIDTH - PAD_X * 2);
  const y = (v: number) => PAD_TOP + plotHeight - ((v - min) / range) * plotHeight;

  const gridlines = [min, (min + max) / 2, max];
  const first = points[0];
  const last = points[points.length - 1];
  const mid = points[Math.floor(points.length / 2)];

  return (
    <svg width="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Trend over time">
      {gridlines.map((v, i) => (
        <g key={i}>
          <line x1={PAD_X} x2={WIDTH - PAD_X} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth={1} />
          <text x={PAD_X} y={y(v) - 4} fontSize={10} fill="var(--text-tertiary)" className="font-mono-nums">
            {formatValue(v)}
          </text>
        </g>
      ))}
      {series.map((s, si) => {
        const defined = s.points.map((p, i) => ({ i, p })).filter((e) => e.p.value != null);
        if (defined.length === 0) return null;
        const path = defined.map(({ i, p }) => `${x(i, s.points.length)},${y(p.value as number)}`).join(" L ");
        return (
          <motion.path
            key={si}
            d={`M ${path}`}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeDasharray={s.dashed ? "4 4" : undefined}
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduced ? { pathLength: 1 } : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: reduced ? 0 : 0.9, ease: [0.16, 1, 0.3, 1] }}
          />
        );
      })}
      {first && (
        <text x={PAD_X} y={HEIGHT - 8} fontSize={10} fill="var(--text-tertiary)">
          {formatShortDate(first.date)}
        </text>
      )}
      {mid && (
        <text x={WIDTH / 2} y={HEIGHT - 8} fontSize={10} fill="var(--text-tertiary)" textAnchor="middle">
          {formatShortDate(mid.date)}
        </text>
      )}
      {last && (
        <text x={WIDTH - PAD_X} y={HEIGHT - 8} fontSize={10} fill="var(--text-tertiary)" textAnchor="end">
          {formatShortDate(last.date)}
        </text>
      )}
    </svg>
  );
}
