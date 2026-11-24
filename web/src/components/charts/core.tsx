import { useId, useLayoutEffect, useState, type ReactNode, type RefObject } from "react";
import { cn } from "../../lib/cn";

/**
 * The chart kit (session 35): the pieces every chart was re-implementing — measured width, rounded ticks, smoothed paths,
 * nearest-point lookup, gradients, tooltip and legend. Pure helpers here are allocation-light because they run on every pan frame.
 */

// ---------------------------------------------------------------- sizing

/** The element's content width, kept current by one ResizeObserver. */
export function useChartWidth(ref: RefObject<HTMLElement | null>, initial = 600): number {
  const [width, setWidth] = useState(initial);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (el.clientWidth) setWidth(el.clientWidth);
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(Math.round(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

// ---------------------------------------------------------------- scales and ticks

/** Rounded ("nice") ticks covering [min, max]: steps of 1, 2, 2.5 or 5 × 10^n. The domain widens to the outer ticks so a line
 * never touches the frame and the gridlines land on readable numbers. */
export function niceTicks(min: number, max: number, count = 4): { ticks: number[]; min: number; max: number } {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { ticks: [0, 1], min: 0, max: 1 };
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / Math.max(count, 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
  return { ticks, min: lo, max: hi };
}

/** Ticks for seconds-valued axes (a pace in s/500m, an elapsed time): 1, 2, 5, 10, 15, 30 s, then minutes. */
export function secondsTicks(min: number, max: number, count = 4): { ticks: number[]; min: number; max: number } {
  const raw = Math.max((max - min) / Math.max(count, 1), 0.5);
  const steps = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1800, 3600];
  const step = steps.find((s) => s >= raw) ?? 3600;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(v);
  return { ticks, min: lo, max: hi === lo ? lo + step : hi };
}

export function extent(values: ArrayLike<number>): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || Number.isNaN(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo === Infinity ? [0, 1] : [lo, hi];
}

/** Index of the value in a sorted array nearest to `target` (binary search; replaces six linear scans). */
export function nearestIndex(sorted: ArrayLike<number>, target: number): number {
  const n = sorted.length;
  if (n === 0) return -1;
  let lo = 0;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(sorted[lo - 1] - target) <= Math.abs(sorted[lo] - target)) return lo - 1;
  return lo;
}

/** First index whose value is >= target. */
export function lowerBound(sorted: ArrayLike<number>, target: number): number {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

// ---------------------------------------------------------------- paths

const r1 = (v: number) => Math.round(v * 10) / 10;

/**
 * A line through screen points. `smooth` uses monotone cubic interpolation (Fritsch–Carlson): curves never overshoot the data,
 * so a smoothed peak is never higher than the real one. `null` y values break the line (a gap stays a gap, never bridged).
 */
export function linePath(xs: ArrayLike<number>, ys: ArrayLike<number | null>, smooth = true): string {
  let out = "";
  let segX: number[] = [];
  let segY: number[] = [];
  const flush = () => {
    if (segX.length === 1) out += `M${r1(segX[0])},${r1(segY[0])}h0.01`;
    else if (segX.length > 1) out += smooth && segX.length > 2 ? monotone(segX, segY) : straight(segX, segY);
    segX = [];
    segY = [];
  };
  for (let i = 0; i < xs.length; i++) {
    const y = ys[i];
    if (y == null || Number.isNaN(y)) {
      flush();
      continue;
    }
    segX.push(xs[i]);
    segY.push(y);
  }
  flush();
  return out;
}

/** The same line closed down to `baseY`, for an area fill under it. */
export function areaPath(xs: ArrayLike<number>, ys: ArrayLike<number | null>, baseY: number, smooth = true): string {
  let out = "";
  let start = -1;
  const close = (from: number, to: number) => {
    if (to - from < 1) return;
    const sx: number[] = [];
    const sy: number[] = [];
    for (let i = from; i <= to; i++) {
      sx.push(xs[i]);
      sy.push(ys[i] as number);
    }
    const body = smooth && sx.length > 2 ? monotone(sx, sy) : straight(sx, sy);
    out += `${body}L${r1(sx[sx.length - 1])},${r1(baseY)}L${r1(sx[0])},${r1(baseY)}Z`;
  };
  for (let i = 0; i <= xs.length; i++) {
    const y = i < xs.length ? ys[i] : null;
    const ok = y != null && !Number.isNaN(y);
    if (ok && start < 0) start = i;
    if (!ok && start >= 0) {
      close(start, i - 1);
      start = -1;
    }
  }
  return out;
}

function straight(xs: number[], ys: number[]): string {
  let d = `M${r1(xs[0])},${r1(ys[0])}`;
  for (let i = 1; i < xs.length; i++) d += `L${r1(xs[i])},${r1(ys[i])}`;
  return d;
}

function monotone(xs: number[], ys: number[]): string {
  const n = xs.length;
  const dx = new Float64Array(n - 1);
  const m = new Float64Array(n - 1);
  for (let i = 0; i < n - 1; i++) {
    dx[i] = xs[i + 1] - xs[i] || 1e-6;
    m[i] = (ys[i + 1] - ys[i]) / dx[i];
  }
  const t = new Float64Array(n);
  t[0] = m[0];
  t[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) {
    if (m[i - 1] * m[i] <= 0) t[i] = 0;
    else {
      const w1 = 2 * dx[i] + dx[i - 1];
      const w2 = dx[i] + 2 * dx[i - 1];
      t[i] = (w1 + w2) / (w1 / m[i - 1] + w2 / m[i]);
    }
  }
  let d = `M${r1(xs[0])},${r1(ys[0])}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += `C${r1(xs[i] + h)},${r1(ys[i] + t[i] * h)},${r1(xs[i + 1] - h)},${r1(ys[i + 1] - t[i + 1] * h)},${r1(xs[i + 1])},${r1(ys[i + 1])}`;
  }
  return d;
}

/** Thins dots for a dense series (stroke rate over thousands of strokes) to at most one per `minGapPx` of screen width. */
export function thinByPixel(xs: ArrayLike<number>, minGapPx = 2): number[] {
  const keep: number[] = [];
  let last = -Infinity;
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] - last >= minGapPx) {
      keep.push(i);
      last = xs[i];
    }
  }
  return keep;
}

// ---------------------------------------------------------------- SVG pieces

/** A gradient id unique to this chart instance, safe inside `url(#…)` (React's ids contain colons). */
export function useSvgId(prefix: string): string {
  return `${prefix}-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
}

/** A vertical fade from the series colour to transparent — the area under a line. */
export function AreaGradient({ id, color, from = 0.32, to = 0 }: { id: string; color: string; from?: number; to?: number }) {
  return (
    <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stopColor={color} stopOpacity={from} />
      <stop offset="100%" stopColor={color} stopOpacity={to} />
    </linearGradient>
  );
}

/** Recessive horizontal gridlines with their labels at the left edge. */
export function YGrid({
  ticks,
  y,
  x0,
  x1,
  format,
  labelX,
  anchor = "start",
}: {
  ticks: number[];
  y: (v: number) => number;
  x0: number;
  x1: number;
  format: (v: number) => string;
  labelX?: number;
  anchor?: "start" | "end";
}) {
  return (
    <g aria-hidden>
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={x0} x2={x1} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth={1} strokeDasharray={i === 0 ? undefined : "2 4"} opacity={i === 0 ? 0.9 : 0.7} />
          <text x={labelX ?? x0} y={y(t) - 4} fontSize={10} fill="var(--text-tertiary)" textAnchor={anchor} className="font-mono-nums">
            {format(t)}
          </text>
        </g>
      ))}
    </g>
  );
}

// ---------------------------------------------------------------- HTML pieces

export type TooltipRow = { label: string; value: string; color?: string };

/**
 * The one tooltip: a title line (usually the date or position) and a row per series, each with its colour swatch. It follows
 * `xPct` (0–100) and slides along itself by the same fraction — its left edge at the chart's left, its right edge at the chart's
 * right — so it can never hang past the chart and widen a phone's page (text-wrap.spec at 320px).
 */
export function ChartTooltip({ xPct, title, rows, testId, pinned = false }: { xPct?: number; title: ReactNode; rows: TooltipRow[]; testId?: string; pinned?: boolean }) {
  const pct = Math.min(Math.max(xPct ?? 0, 0), 100);
  return (
    <div
      data-testid={testId}
      role="presentation"
      className="glass-primary glass-dense glass-elevated pointer-events-none absolute top-1 z-10 min-w-[7.5rem] max-w-full rounded-md border border-border-strong bg-surface-3/95 px-2.5 py-2 text-xs shadow-float backdrop-blur-sm"
      style={pinned || xPct == null ? { left: 4 } : { left: `${pct}%`, transform: `translateX(-${pct}%)` }}
    >
      <div className="mb-1 text-text-tertiary">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5 text-text-secondary">
            {r.color && <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: r.color }} />}
            {r.label}
          </span>
          <span className="font-mono-nums font-medium text-text-primary">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

export type LegendItem = { label: string; color: string; style?: "line" | "dash" | "dot" | "block" };

/** Series identity in words beside a swatch (never colour alone). */
export function Legend({ items, className }: { items: LegendItem[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary", className)}>
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-1.5">
          <Swatch color={it.color} style={it.style ?? "line"} />
          {it.label}
        </li>
      ))}
    </ul>
  );
}

function Swatch({ color, style }: { color: string; style: NonNullable<LegendItem["style"]> }) {
  if (style === "dot") return <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: color }} />;
  if (style === "block") return <span aria-hidden className="h-2.5 w-2.5 rounded-[3px]" style={{ background: color }} />;
  return (
    <svg aria-hidden width="16" height="6" className="shrink-0">
      <line x1="1" x2="15" y1="3" y2="3" stroke={color} strokeWidth="2" strokeLinecap="round" strokeDasharray={style === "dash" ? "3 3" : undefined} />
    </svg>
  );
}

/** A screen-reader sentence summarising a series: range, latest value and direction. Charts render it in an `sr-only` paragraph. */
export function summarize(name: string, values: (number | null | undefined)[], format: (v: number) => string): string {
  const vals = values.filter((v): v is number => v != null && Number.isFinite(v));
  if (vals.length === 0) return `${name}: no data in this range.`;
  const [lo, hi] = extent(vals);
  const first = vals[0];
  const last = vals[vals.length - 1];
  const dir = Math.abs(last - first) < (hi - lo) * 0.1 ? "roughly level" : last > first ? "rising" : "falling";
  return `${name}: ${vals.length} values from ${format(lo)} to ${format(hi)}, latest ${format(last)}, ${dir} over the range.`;
}
