import { useMemo, useRef } from "react";
import { extent, niceTicks, secondsTicks, useChartWidth } from "./core";

const PAD_LEFT = 46;
const PAD_RIGHT = 10;
const PAD_TOP = 10;
const PAD_BOTTOM = 34;

/**
 * Two measurements against each other (split vs stroke rate per stroke). One axis each, both labelled; dots are small and translucent
 * so dense regions read as density, and at most `maxPoints` are drawn (evenly sampled) so a long session stays cheap.
 */
export function ScatterPlot({
  points,
  xLabel,
  yLabel,
  formatX,
  formatY,
  yAxis = "number",
  invertY = false,
  color,
  height = 220,
  ariaLabel,
  maxPoints = 900,
}: {
  points: { x: number; y: number }[];
  xLabel: string;
  yLabel: string;
  formatX: (v: number) => string;
  formatY: (v: number) => string;
  yAxis?: "number" | "seconds";
  invertY?: boolean;
  color: string;
  height?: number;
  ariaLabel: string;
  maxPoints?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const width = useChartWidth(ref, 320);
  const geo = useMemo(() => {
    const step = Math.max(1, Math.ceil(points.length / maxPoints));
    const pts = points.filter((_, i) => i % step === 0);
    const [x0, x1] = extent(pts.map((p) => p.x));
    const [y0, y1] = extent(pts.map((p) => p.y));
    const tx = niceTicks(x0, x1, 4);
    const ty = yAxis === "seconds" ? secondsTicks(y0, y1, 3) : niceTicks(y0, y1, 3);
    return { pts, tx, ty };
  }, [points, maxPoints, yAxis]);

  const plotW = Math.max(width - PAD_LEFT - PAD_RIGHT, 40);
  const plotH = height - PAD_TOP - PAD_BOTTOM;
  const x = (v: number) => PAD_LEFT + ((v - geo.tx.min) / (geo.tx.max - geo.tx.min || 1)) * plotW;
  const y = (v: number) => {
    const f = (v - geo.ty.min) / (geo.ty.max - geo.ty.min || 1);
    return PAD_TOP + (invertY ? f : 1 - f) * plotH;
  };

  if (geo.pts.length < 3) return <p className="text-sm text-text-tertiary">Not enough data for this view.</p>;

  return (
    <div ref={ref}>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
        {geo.ty.ticks.map((t, i) => (
          <g key={`y${i}`} aria-hidden>
            <line x1={PAD_LEFT} x2={width - PAD_RIGHT} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray="2 4" opacity={0.8} />
            <text x={PAD_LEFT - 6} y={y(t) + 3} fontSize={10} textAnchor="end" fill="var(--text-tertiary)" className="font-mono-nums">
              {formatY(t)}
            </text>
          </g>
        ))}
        {geo.tx.ticks.map((t, i) => (
          <text key={`x${i}`} x={x(t)} y={height - PAD_BOTTOM + 14} fontSize={10} textAnchor="middle" fill="var(--text-tertiary)" className="font-mono-nums" aria-hidden>
            {formatX(t)}
          </text>
        ))}
        <g aria-hidden>
          {geo.pts.map((p, i) => (
            <circle key={i} cx={x(p.x)} cy={y(p.y)} r={2.6} fill={color} opacity={0.42} />
          ))}
        </g>
        <text x={PAD_LEFT + plotW / 2} y={height - 4} fontSize={10} textAnchor="middle" fill="var(--text-secondary)" aria-hidden>
          {xLabel}
        </text>
        <text x={PAD_LEFT} y={PAD_TOP - 2} fontSize={10} fill="var(--text-secondary)" aria-hidden>
          {yLabel}
        </text>
      </svg>
    </div>
  );
}
