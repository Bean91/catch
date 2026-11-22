import { toISODate } from "../../lib/dates";
import { motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import type { EventMarker } from "../../lib/chartAnnotations";
import { formatShortDate } from "../../lib/format";
import type { SeriesPoint } from "../../lib/types";
import { useReducedMotion } from "../../lib/useReducedMotion";
import type { Domain } from "../../lib/useChartInteraction";
import { useChartInteraction } from "../../lib/useChartInteraction";
import { AreaGradient, ChartTooltip, YGrid, areaPath, linePath, lowerBound, nearestIndex, niceTicks, useSvgId } from "./core";

const HEIGHT = 240;
const PAD_X = 36;
const TAP_PROXIMITY_PX = 20;
const PAD_TOP = 16;
const PAD_BOTTOM = 28;
const DAY_MS = 86_400_000;

function dateToMs(date: string): number {
  return new Date(date + "T00:00:00").getTime();
}

export function TrendLineChart({
  points,
  secondaryKey,
  color = "var(--accent)",
  formatValue = (v: number) => v.toFixed(0),
  domain,
  fullDomain,
  minSpanMs = 7 * DAY_MS,
  onDomainChange,
  onDomainSettled,
  onResetDomain,
  annotations = [],
  onPointTap,
  showBand = true,
}: {
  points: SeriesPoint[];
  secondaryKey?: "smoothed";
  color?: string;
  formatValue?: (value: number) => string;
  domain: Domain;
  fullDomain: Domain;
  minSpanMs?: number;
  onDomainChange: (domain: Domain) => void;
  onDomainSettled?: (domain: Domain) => void;
  onResetDomain: () => void;
  annotations?: EventMarker[];
  /** A tap/click on a point that isn't a drag or the second tap of a double-tap — gives the
   * full point so callers can read e.g. `activity_id` (spec #4: tapping a workouts-series
   * point opens that workout), not just the date. */
  onPointTap?: (point: SeriesPoint) => void;
  showBand?: boolean;
}) {
  const reduced = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const [plotWidthPx, setPlotWidthPx] = useState(600);
  const hasAnimatedIn = useRef(false);
  const gradId = useSvgId("trend-area");
  const clipId = useSvgId("trend-clip");

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setPlotWidthPx(Math.max(w - PAD_X * 2, 50));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Dates parsed once per data change, not once per point per pan frame.
  const msArr = useMemo(() => points.map((p) => dateToMs(p.date)), [points]);

  const nearest = (targetMs: number): SeriesPoint | null => {
    const i = nearestIndex(msArr, targetMs);
    return i < 0 ? null : points[i];
  };

  const { handlers, hoverX, setHoverX, isPanning } = useChartInteraction({
    domain,
    fullDomain,
    minSpan: minSpanMs,
    plotWidthPx,
    surfaceRef: containerRef,
    padLeft: PAD_X,
    onViewChange: onDomainChange,
    onSettled: onDomainSettled,
    onTap: (domainX, clientX) => {
      if (!onPointTap) return;
      const point = nearest(domainX);
      if (!point) return;
      // Without a screen-distance check, tapping *anywhere* on the chart — including empty
      // space between two widely-spaced points — would still "find" and open the nearest one.
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const tapPlotX = clientX - rect.left;
      const pointPlotX = x(dateToMs(point.date));
      if (Math.abs(tapPlotX - pointPlotX) > TAP_PROXIMITY_PX) return;
      onPointTap(point);
    },
    onDoubleTap: onResetDomain,
  });

  const width = plotWidthPx + PAD_X * 2;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;

  // The visible slice (binary search on the pre-parsed dates) sets the y-range; paths are built from it plus a margin of
  // one point either side, so a line still runs off the edge of the plot instead of stopping short.
  const lo = Math.max(lowerBound(msArr, domain.min) - 1, 0);
  const hi = Math.min(lowerBound(msArr, domain.max + 1) + 1, points.length);
  const geometry = useMemo(() => {
    let vmin = Infinity;
    let vmax = -Infinity;
    for (let i = lo; i < hi; i++) {
      const ms = msArr[i];
      if (ms < domain.min || ms > domain.max) continue;
      const p = points[i];
      const a = showBand ? p.value_min : p.value;
      const b = showBand ? p.value_max : p.value;
      if (a < vmin) vmin = a;
      if (b > vmax) vmax = b;
    }
    if (vmin === Infinity) {
      vmin = 0;
      vmax = 1;
    }
    const nice = niceTicks(vmin, vmax, plotHeight < 180 ? 3 : 4);
    const range = nice.max - nice.min || 1;
    const yOf = (v: number) => PAD_TOP + plotHeight - ((v - nice.min) / range) * plotHeight;
    const span = Math.max(domain.max - domain.min, 1);
    const xs: number[] = [];
    const ys: number[] = [];
    const yMax: number[] = [];
    const yMin: number[] = [];
    const ySec: (number | null)[] = [];
    for (let i = lo; i < hi; i++) {
      const p = points[i];
      xs.push(PAD_X + ((msArr[i] - domain.min) / span) * plotWidthPx);
      ys.push(yOf(p.value));
      if (showBand) {
        yMax.push(yOf(p.value_max));
        yMin.push(yOf(p.value_min));
      }
      if (secondaryKey) ySec.push(p[secondaryKey] != null ? yOf(p[secondaryKey] as number) : null);
    }
    const base = PAD_TOP + plotHeight;
    const line = xs.length ? linePath(xs, ys) : null;
    const area = xs.length > 1 ? areaPath(xs, ys, base) : null;
    let band: string | null = null;
    if (showBand && xs.length > 1) {
      band = linePath(xs, yMax, false);
      for (let i = xs.length - 1; i >= 0; i--) band += `L${xs[i].toFixed(1)},${yMin[i].toFixed(1)}`;
      band += "Z";
    }
    const secondary = secondaryKey && xs.length ? linePath(xs, ySec) : null;
    return { ticks: nice.ticks, yOf, line, area, band, secondary };
  }, [points, msArr, lo, hi, domain.min, domain.max, plotWidthPx, plotHeight, showBand, secondaryKey]);

  const x = (ms: number) => PAD_X + ((ms - domain.min) / Math.max(domain.max - domain.min, 1)) * plotWidthPx;
  const y = geometry.yOf;
  const linePath_ = geometry.line;

  const ticks = useMemo(() => buildDateTicks(domain, plotWidthPx), [domain, plotWidthPx]);
  const visibleAnnotations = annotations.filter((a) => {
    const ms = dateToMs(a.date);
    return ms >= domain.min - DAY_MS && ms <= domain.max + DAY_MS;
  });

  const hoverPoint = hoverX != null && !isPanning ? nearest(hoverX) : null;

  useEffect(() => {
    hasAnimatedIn.current = true;
  }, []);

  // `domain` changes on every pan/zoom frame, but an aria-live region re-announces its text on
  // every change — wiring it straight to `domain` would read the visible range aloud dozens of
  // times during a single drag. Debounced so a screen reader hears one announcement, ~400ms
  // after the gesture actually stops (covers both a pan/zoom settling and a preset-button
  // click, which doesn't go through the pan/zoom "settled" callback at all).
  const [announcedDomain, setAnnouncedDomain] = useState(domain);
  useEffect(() => {
    const id = setTimeout(() => setAnnouncedDomain(domain), 400);
    return () => clearTimeout(id);
  }, [domain]);

  if (points.length === 0) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border-strong/60 text-sm text-text-tertiary">
        Not enough history yet.
      </div>
    );
  }

  const describeDomain = (d: Domain) =>
    `Showing ${formatShortDate(toISODate(new Date(d.min)))} to ${formatShortDate(toISODate(new Date(d.max)))}`;
  const rangeLabel = describeDomain(domain);
  const announcedRangeLabel = describeDomain(announcedDomain);
  const hoverXPx = hoverPoint ? x(dateToMs(hoverPoint.date)) : 0;

  return (
    <div ref={containerRef} className="relative">
      <div
        className="touch-none select-none outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        // Handlers + touch-action live on this HTML div, not the <svg> itself — WebKit's
        // touch-action support on SVG root elements has real, documented gaps (confirmed the
        // hard way: this chart's touches did nothing on a real iPhone despite working under
        // Chromium's CDP touch emulation in session 8's own testing). A plain HTMLElement is
        // the one thing every engine, including iOS Safari, reliably honors `touch-action:
        // none` on. See DESIGN.md's "Chart touch-action" note.
        data-chart-surface="true"
        role="img"
        // The range text stays last in the label, not first — a touch regression test
        // (charts.spec.ts) parses "Showing X to Y" by anchoring on the label's own end.
        aria-label={`Trend over time. Focus and press +/- to zoom, arrow keys to pan, Escape to reset. ${rangeLabel}`}
        tabIndex={0}
        onPointerDown={handlers.onPointerDown}
        onPointerMove={handlers.onPointerMove}
        onPointerUp={handlers.onPointerUp}
        onPointerCancel={handlers.onPointerCancel}
        onPointerLeave={() => setHoverX(null)}
        onKeyDown={handlers.onKeyDown}
        onDoubleClick={handlers.onDoubleClick}
      >
      <svg width="100%" height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`} aria-hidden="true" className="pointer-events-none block">
        <defs>
          <AreaGradient id={gradId} color={color} from={0.3} />
          <clipPath id={clipId}>
            <rect x={PAD_X} y={0} width={plotWidthPx} height={HEIGHT} />
          </clipPath>
        </defs>

        <YGrid ticks={geometry.ticks} y={y} x0={PAD_X} x1={PAD_X + plotWidthPx} format={formatValue} labelX={2} />
        {ticks.map((t, i) => (
          <text key={i} x={x(t.ms)} y={HEIGHT - 8} fontSize={10} fill="var(--text-tertiary)" textAnchor="middle">
            {t.label}
          </text>
        ))}

        <g clipPath={`url(#${clipId})`}>
          {visibleAnnotations.map((a, i) => (
            <g key={i}>
              {a.taperStart && (
                <rect
                  x={x(dateToMs(a.taperStart))}
                  width={Math.max(x(dateToMs(a.date)) - x(dateToMs(a.taperStart)), 0)}
                  y={PAD_TOP}
                  height={plotHeight}
                  fill="var(--accent)"
                  opacity={0.07}
                />
              )}
              <line
                x1={x(dateToMs(a.date))}
                x2={x(dateToMs(a.date))}
                y1={PAD_TOP}
                y2={PAD_TOP + plotHeight}
                // DESIGN.md reserves --band-red/yellow/green for recovery/strain status only —
                // an A-race marker is emphasis, not a status color, so it uses the accent instead.
                stroke={a.emphasized ? "var(--accent)" : "var(--text-tertiary)"}
                strokeWidth={a.emphasized ? 2 : 1}
                strokeDasharray={a.emphasized ? undefined : "3 3"}
                opacity={0.8}
              />
              <title>{`${a.label} — ${formatShortDate(a.date)}`}</title>
            </g>
          ))}

          {geometry.area && <path d={geometry.area} fill={`url(#${gradId})`} />}
          {geometry.band && <path d={geometry.band} fill={color} opacity={0.1} />}
          {geometry.secondary && (
            <path d={geometry.secondary} fill="none" stroke="var(--text-secondary)" strokeWidth={1.5} strokeDasharray="4 4" strokeLinecap="round" opacity={0.8} />
          )}
          {linePath_ &&
            (reduced || hasAnimatedIn.current ? (
              // A plain <path> once the one-time draw-in has played — re-rendering a
              // motion.path on every pan/zoom frame (hundreds of times during a drag) carries
              // real Framer Motion overhead for an animation that's already a no-op by then;
              // measured as dropped frames in a CPU-throttled pan test before this split.
              <path data-testid="chart-line" d={linePath_} fill="none" stroke={color} strokeWidth={2.25} strokeLinecap="round" strokeLinejoin="round" />
            ) : (
              <motion.path
                data-testid="chart-line"
                d={linePath_}
                fill="none"
                stroke={color}
                strokeWidth={2.25}
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
              />
            ))}
        </g>

        {hoverPoint && (
          <g>
            <line x1={hoverXPx} x2={hoverXPx} y1={PAD_TOP} y2={PAD_TOP + plotHeight} stroke="var(--text-tertiary)" strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={hoverXPx} cy={y(hoverPoint.value)} r={5} fill={color} stroke="var(--surface)" strokeWidth={2} />
          </g>
        )}
      </svg>
      </div>

      {hoverPoint && (
        <ChartTooltip
          testId="chart-tooltip"
          xPct={(hoverXPx / width) * 100}
          title={formatShortDate(hoverPoint.date)}
          rows={[
            { label: "Value", value: formatValue(hoverPoint.value), color },
            ...(secondaryKey && hoverPoint[secondaryKey] != null ? [{ label: "Smoothed", value: formatValue(hoverPoint[secondaryKey] as number) }] : []),
          ]}
        />
      )}

      <p className="sr-only" aria-live="polite">
        {announcedRangeLabel}
      </p>
    </div>
  );
}

function buildDateTicks(domain: Domain, plotWidthPx: number): { ms: number; label: string }[] {
  const spanDays = (domain.max - domain.min) / DAY_MS;
  const targetTicks = plotWidthPx < 400 ? 4 : 6;
  const stepDays = Math.max(1, Math.round(spanDays / targetTicks));
  const ticks: { ms: number; label: string }[] = [];
  const start = Math.ceil(domain.min / DAY_MS) * DAY_MS;
  for (let ms = start; ms <= domain.max; ms += stepDays * DAY_MS) {
    ticks.push({ ms, label: formatShortDate(toISODate(new Date(ms))) });
  }
  return ticks;
}
