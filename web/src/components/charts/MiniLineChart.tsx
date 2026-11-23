import { useMemo, useRef, useState } from "react";
import { formatShortDate } from "../../lib/format";
import { AreaGradient, ChartTooltip, areaPath, extent, linePath, nearestIndex, niceTicks, secondsTicks, summarize, useChartWidth, useSvgId } from "./core";

const PAD_LEFT = 44;
const PAD_RIGHT = 10;
const PAD_TOP = 10;
const PAD_BOTTOM = 22;

export type DatedValue = { date: string; value: number | null };

/**
 * A static line over dates — progression, a secondary trend in a card — with labelled y ticks, an area fade, hover for exact values,
 * and dots when there are few points (each test result is its own event, not a sample). `invert` puts lower values higher (paces).
 * Optional `markers` are measured results drawn as rings over an estimated line (actual vs predicted).
 */
export function MiniLineChart({
  points,
  color,
  format,
  axis = "number",
  invert = false,
  height = 180,
  label,
  markers,
  markerLabel = "Measured",
}: {
  points: DatedValue[];
  color: string;
  format: (v: number) => string;
  axis?: "number" | "seconds";
  invert?: boolean;
  height?: number;
  label: string;
  markers?: DatedValue[];
  markerLabel?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const width = useChartWidth(ref, 320);
  const gradId = useSvgId("mini");
  const [hover, setHover] = useState<number | null>(null);

  const data = useMemo(() => points.filter((p) => p.value != null), [points]);
  const geo = useMemo(() => {
    if (data.length === 0) return null;
    const ms = data.map((p) => new Date(`${p.date.slice(0, 10)}T00:00:00`).getTime());
    const mms = (markers ?? []).filter((m) => m.value != null).map((m) => ({ ms: new Date(`${m.date.slice(0, 10)}T00:00:00`).getTime(), v: m.value as number, date: m.date }));
    const [lo, hi] = extent([...data.map((p) => p.value as number), ...mms.map((m) => m.v)]);
    const t = axis === "seconds" ? secondsTicks(lo, hi, 3) : niceTicks(lo, hi, 3);
    const t0 = Math.min(ms[0], ...mms.map((m) => m.ms));
    const t1 = Math.max(ms[ms.length - 1], ...mms.map((m) => m.ms), t0 + 86_400_000);
    const plotW = Math.max(width - PAD_LEFT - PAD_RIGHT, 40);
    const plotH = height - PAD_TOP - PAD_BOTTOM;
    const range = t.max - t.min || 1;
    const x = (v: number) => PAD_LEFT + ((v - t0) / (t1 - t0)) * plotW;
    const y = (v: number) => (invert ? PAD_TOP + ((v - t.min) / range) * plotH : PAD_TOP + plotH - ((v - t.min) / range) * plotH);
    const xs = ms.map(x);
    const ys = data.map((p) => y(p.value as number));
    const base = invert ? PAD_TOP : PAD_TOP + plotH;
    return { ms, xs, ys, x, y, ticks: t.ticks, line: linePath(xs, ys), area: xs.length > 1 ? areaPath(xs, ys, base) : null, plotW, markers: mms, t0, t1 };
  }, [data, markers, axis, invert, width, height]);

  if (!geo) return <div className="flex h-24 items-center justify-center text-sm text-text-tertiary">Not enough history yet.</div>;
  const hp = hover != null ? data[hover] : null;

  return (
    <div ref={ref} className="relative">
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={summarize(label, data.map((p) => p.value), format)}
        onPointerMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - r.left) / r.width) * width;
          setHover(nearestIndex(geo.xs, px));
        }}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <AreaGradient id={gradId} color={color} from={invert ? 0 : 0.24} to={invert ? 0.24 : 0} />
        </defs>
        {geo.ticks.map((t, i) => (
          <g key={i} aria-hidden>
            <line x1={PAD_LEFT} x2={width - PAD_RIGHT} y1={geo.y(t)} y2={geo.y(t)} stroke="var(--border)" strokeDasharray={i === 0 ? undefined : "2 4"} opacity={0.8} />
            <text x={PAD_LEFT - 6} y={geo.y(t) + 3} fontSize={10} textAnchor="end" fill="var(--text-tertiary)" className="font-mono-nums">
              {format(t)}
            </text>
          </g>
        ))}
        {geo.area && <path d={geo.area} fill={`url(#${gradId})`} />}
        <path d={geo.line} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        {data.length <= 24 && geo.xs.map((cx, i) => <circle key={i} cx={cx} cy={geo.ys[i]} r={3} fill={color} stroke="var(--surface)" strokeWidth={1.5} />)}
        {geo.markers.map((m, i) => (
          <circle key={`m${i}`} cx={geo.x(m.ms)} cy={geo.y(m.v)} r={5} fill="var(--surface)" stroke="var(--text-primary)" strokeWidth={2}>
            <title>{`${markerLabel} ${format(m.v)} · ${formatShortDate(m.date)}`}</title>
          </circle>
        ))}
        {hp && (
          <g>
            <line x1={geo.xs[hover!]} x2={geo.xs[hover!]} y1={PAD_TOP} y2={height - PAD_BOTTOM} stroke="var(--text-tertiary)" strokeDasharray="3 3" />
            <circle cx={geo.xs[hover!]} cy={geo.ys[hover!]} r={4.5} fill={color} stroke="var(--surface)" strokeWidth={2} />
          </g>
        )}
        {[0, 1].map((i) => (
          <text key={i} x={i ? width - PAD_RIGHT : PAD_LEFT} y={height - 6} fontSize={10} textAnchor={i ? "end" : "start"} fill="var(--text-tertiary)">
            {new Date(i ? geo.t1 : geo.t0).toLocaleDateString(undefined, geo.t1 - geo.t0 > 300 * 86_400_000 ? { month: "short", year: "numeric" } : { month: "short", day: "numeric" })}
          </text>
        ))}
      </svg>
      {hp && <ChartTooltip xPct={(geo.xs[hover!] / width) * 100} title={formatShortDate(hp.date)} rows={[{ label, value: format(hp.value as number), color }]} />}
    </div>
  );
}
