import { useMemo, useRef, useState } from "react";
import { ChartTooltip, extent, niceTicks, secondsTicks, useChartWidth } from "./core";

export type ValueBar = { key: string | number; label: string; title?: string; value: number; target?: number | null; emphasis?: boolean };

const PAD_LEFT = 44;
const PAD_RIGHT = 8;
const PAD_TOP = 18;
const PAD_BOTTOM = 22;

function roundedTop(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

/**
 * A small static bar chart for a handful of values (splits of a test, best/typical/recent, a histogram). It measures its own width so
 * text never scales with the card, labels its y-axis on rounded ticks (a non-zero baseline is always shown in numbers, never
 * implied), and `invert` puts lower values higher for paces ("faster reads taller"). An optional dashed target per bar.
 */
export function ValueBars({
  bars,
  format,
  axis = "number",
  invert = false,
  zeroBased = false,
  color = "var(--accent)",
  height = 200,
  ariaLabel,
  testId,
  showValues = true,
  reference,
}: {
  bars: ValueBar[];
  format: (v: number) => string;
  axis?: "number" | "seconds";
  invert?: boolean;
  zeroBased?: boolean;
  color?: string;
  height?: number;
  ariaLabel: string;
  testId?: string;
  showValues?: boolean;
  /** A horizontal reference line across every bar (the average of a set of intervals). */
  reference?: { value: number; label: string } | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const width = useChartWidth(ref, 320);
  const [hover, setHover] = useState<number | null>(null);

  const geo = useMemo(() => {
    const all = [...bars.flatMap((b) => (b.target != null ? [b.value, b.target] : [b.value])), ...(reference ? [reference.value] : [])];
    let [lo, hi] = extent(all);
    if (zeroBased) lo = 0;
    else {
      const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.05 || 1;
      lo -= pad;
      hi += pad * 0.4;
    }
    const t = axis === "seconds" ? secondsTicks(lo, hi, 3) : niceTicks(lo, hi, 3);
    const plotH = height - PAD_TOP - PAD_BOTTOM;
    const range = t.max - t.min || 1;
    // With `invert`, the axis's max (slowest) is the baseline and faster values rise from it.
    const frac = (v: number) => (invert ? (t.max - v) / range : (v - t.min) / range);
    const y = (v: number) => PAD_TOP + plotH - frac(v) * plotH;
    return { ticks: t.ticks, y, base: PAD_TOP + plotH };
  }, [bars, zeroBased, axis, height, invert, reference]);

  const plotW = Math.max(width - PAD_LEFT - PAD_RIGHT, 40);
  const slot = plotW / Math.max(bars.length, 1);
  const bw = Math.max(Math.min(slot * 0.62, 56), 3);
  const labelEvery = Math.ceil(bars.length / Math.max(Math.floor(plotW / 44), 1));

  return (
    <div ref={ref} className="relative" data-testid={testId}>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel} onPointerLeave={() => setHover(null)}>
        {geo.ticks.map((t, i) => (
          <g key={i} aria-hidden>
            <line x1={PAD_LEFT} x2={width - PAD_RIGHT} y1={geo.y(t)} y2={geo.y(t)} stroke="var(--border)" strokeDasharray={i === 0 ? undefined : "2 4"} opacity={0.8} />
            <text x={PAD_LEFT - 6} y={geo.y(t) + 3} fontSize={10} textAnchor="end" fill="var(--text-tertiary)" className="font-mono-nums">
              {format(t)}
            </text>
          </g>
        ))}
        {bars.map((b, i) => {
          const cx = PAD_LEFT + slot * i + slot / 2;
          const top = Math.min(geo.y(b.value), geo.base - 2);
          const h = geo.base - top;
          const dim = hover != null && hover !== i;
          return (
            <g key={b.key} onPointerEnter={() => setHover(i)}>
              <rect x={cx - slot / 2} y={PAD_TOP} width={slot} height={geo.base - PAD_TOP} fill="transparent" />
              <path d={roundedTop(cx - bw / 2, top, bw, h, 4)} fill={color} opacity={dim ? 0.45 : b.emphasis === false ? 0.55 : 0.9} />
              {b.target != null && (
                <line x1={cx - bw / 2 - 3} x2={cx + bw / 2 + 3} y1={geo.y(b.target)} y2={geo.y(b.target)} stroke="var(--text-primary)" strokeDasharray="3 2" strokeWidth={1.5} opacity={0.7} />
              )}
              {showValues && bars.length <= 12 && (
                <text x={cx} y={top - 5} fontSize={10} textAnchor="middle" fill="var(--text-secondary)" className="font-mono-nums">
                  {format(b.value)}
                </text>
              )}
              {i % labelEvery === 0 && (
                <text x={cx} y={height - 6} fontSize={10} textAnchor="middle" fill="var(--text-tertiary)" className="font-mono-nums">
                  {b.label}
                </text>
              )}
            </g>
          );
        })}
        {reference && (
          <g aria-hidden>
            <line x1={PAD_LEFT} x2={width - PAD_RIGHT} y1={geo.y(reference.value)} y2={geo.y(reference.value)} stroke="var(--text-primary)" strokeWidth={1.25} strokeDasharray="5 4" opacity={0.6} />
            <text x={width - PAD_RIGHT} y={geo.y(reference.value) - 4} fontSize={10} textAnchor="end" fill="var(--text-secondary)">
              {reference.label} {format(reference.value)}
            </text>
          </g>
        )}
      </svg>
      {hover != null && bars[hover] && (
        <ChartTooltip
          xPct={((PAD_LEFT + slot * hover + slot / 2) / width) * 100}
          title={bars[hover].title ?? bars[hover].label}
          rows={[
            { label: "Value", value: format(bars[hover].value), color },
            ...(bars[hover].target != null ? [{ label: "Target", value: format(bars[hover].target as number) }] : []),
          ]}
        />
      )}
    </div>
  );
}
