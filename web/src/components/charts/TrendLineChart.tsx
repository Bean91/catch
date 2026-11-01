import { motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import type { EventMarker } from "../../lib/chartAnnotations";
import { formatShortDate } from "../../lib/format";
import type { SeriesPoint } from "../../lib/types";
import { useReducedMotion } from "../../lib/useReducedMotion";
import type { Domain } from "../../lib/useChartInteraction";
import { useChartInteraction } from "../../lib/useChartInteraction";
import { ChartZoomButtons } from "./ChartZoomButtons";

const HEIGHT = 240;
const PAD_X = 36;
const PAD_TOP = 16;
const PAD_BOTTOM = 28;
const DAY_MS = 86_400_000;

function dateToMs(date: string): number {
  return new Date(date + "T00:00:00").getTime();
}

function nearestPoint(points: SeriesPoint[], targetMs: number): SeriesPoint | null {
  if (points.length === 0) return null;
  let best = points[0];
  let bestDist = Math.abs(dateToMs(best.date) - targetMs);
  for (const p of points) {
    const dist = Math.abs(dateToMs(p.date) - targetMs);
    if (dist < bestDist) {
      best = p;
      bestDist = dist;
    }
  }
  return best;
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
  onPointTap?: (date: string) => void;
  showBand?: boolean;
}) {
  const reduced = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const [plotWidthPx, setPlotWidthPx] = useState(600);
  const hasAnimatedIn = useRef(false);

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

  const { handlers, zoomIn, zoomOut, hoverX, setHoverX, isPanning } = useChartInteraction({
    domain,
    fullDomain,
    minSpan: minSpanMs,
    plotWidthPx,
    onViewChange: onDomainChange,
    onSettled: onDomainSettled,
    onTap: (domainX) => {
      if (!onPointTap) return;
      const point = nearestPoint(points, domainX);
      if (point) onPointTap(point.date);
    },
    onDoubleTap: onResetDomain,
  });

  const width = plotWidthPx + PAD_X * 2;
  const visible = useMemo(() => points.filter((p) => dateToMs(p.date) >= domain.min && dateToMs(p.date) <= domain.max), [points, domain]);

  const allValues = showBand
    ? visible.flatMap((p) => [p.value_min, p.value_max])
    : visible.map((p) => p.value);
  const min = allValues.length ? Math.min(...allValues) : 0;
  const max = allValues.length ? Math.max(...allValues) : 1;
  const range = max - min || 1;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;

  const x = (ms: number) => PAD_X + ((ms - domain.min) / Math.max(domain.max - domain.min, 1)) * plotWidthPx;
  const y = (v: number) => PAD_TOP + plotHeight - ((v - min) / range) * plotHeight;

  const linePath = points.length
    ? "M " + points.map((p) => `${x(dateToMs(p.date))},${y(p.value)}`).join(" L ")
    : null;
  const bandPath =
    showBand && points.length > 1
      ? `M ${points.map((p) => `${x(dateToMs(p.date))},${y(p.value_max)}`).join(" L ")} L ${points
          .slice()
          .reverse()
          .map((p) => `${x(dateToMs(p.date))},${y(p.value_min)}`)
          .join(" L ")} Z`
      : null;
  const secondaryPath =
    secondaryKey && points.length
      ? "M " +
        points
          .filter((p) => p[secondaryKey] != null)
          .map((p) => `${x(dateToMs(p.date))},${y(p[secondaryKey] as number)}`)
          .join(" L ")
      : null;

  const ticks = useMemo(() => buildDateTicks(domain, plotWidthPx), [domain, plotWidthPx]);
  const visibleAnnotations = annotations.filter((a) => {
    const ms = dateToMs(a.date);
    return ms >= domain.min - DAY_MS && ms <= domain.max + DAY_MS;
  });

  const hoverPoint = hoverX != null && !isPanning ? nearestPoint(points, hoverX) : null;

  useEffect(() => {
    hasAnimatedIn.current = true;
  }, []);

  if (points.length === 0) {
    return <div className="flex h-40 items-center justify-center text-sm text-text-tertiary">Not enough history yet.</div>;
  }

  const rangeLabel = `Showing ${formatShortDate(new Date(domain.min).toISOString().slice(0, 10))} to ${formatShortDate(
    new Date(domain.max).toISOString().slice(0, 10),
  )}`;

  return (
    <div ref={containerRef} className="relative">
      <svg
        width="100%"
        height={HEIGHT}
        viewBox={`0 0 ${width} ${HEIGHT}`}
        role="img"
        aria-label={`Trend over time. ${rangeLabel}`}
        tabIndex={0}
        className="touch-pan-y select-none outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        data-chart-surface="true"
        style={{ touchAction: "pan-y" }}
        onPointerDown={handlers.onPointerDown}
        onPointerMove={(e) => {
          handlers.onPointerMove(e);
        }}
        onPointerUp={handlers.onPointerUp}
        onPointerCancel={handlers.onPointerCancel}
        onPointerLeave={() => setHoverX(null)}
        onWheel={handlers.onWheel}
        onKeyDown={handlers.onKeyDown}
        onDoubleClick={handlers.onDoubleClick}
      >
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={x(t.ms)} x2={x(t.ms)} y1={PAD_TOP} y2={PAD_TOP + plotHeight} stroke="var(--border)" strokeWidth={1} opacity={0.5} />
            <text x={x(t.ms)} y={HEIGHT - 8} fontSize={10} fill="var(--text-tertiary)" textAnchor="middle">
              {t.label}
            </text>
          </g>
        ))}
        {[min, (min + max) / 2, max].map((v, i) => (
          <g key={i}>
            <text x={2} y={y(v) - 3} fontSize={10} fill="var(--text-tertiary)" className="font-mono-nums">
              {formatValue(v)}
            </text>
          </g>
        ))}

        {visibleAnnotations.map((a, i) => (
          <g key={i}>
            {a.taperStart && (
              <rect
                x={x(dateToMs(a.taperStart))}
                width={Math.max(x(dateToMs(a.date)) - x(dateToMs(a.taperStart)), 0)}
                y={PAD_TOP}
                height={plotHeight}
                fill="var(--accent)"
                opacity={0.06}
              />
            )}
            <line
              x1={x(dateToMs(a.date))}
              x2={x(dateToMs(a.date))}
              y1={PAD_TOP}
              y2={PAD_TOP + plotHeight}
              stroke={a.emphasized ? "var(--band-red)" : "var(--text-tertiary)"}
              strokeWidth={a.emphasized ? 2 : 1}
              strokeDasharray={a.emphasized ? undefined : "3 3"}
              opacity={0.8}
            />
            <title>{`${a.label} — ${formatShortDate(a.date)}`}</title>
          </g>
        ))}

        {bandPath && <path d={bandPath} fill={color} opacity={0.08} />}
        {secondaryPath && (
          <path d={secondaryPath} fill="none" stroke="var(--text-secondary)" strokeWidth={2} strokeDasharray="4 4" strokeLinecap="round" />
        )}
        {linePath &&
          (reduced || hasAnimatedIn.current ? (
            // A plain <path> once the one-time draw-in has played — re-rendering a
            // motion.path on every pan/zoom frame (hundreds of times during a drag) carries
            // real Framer Motion overhead for an animation that's already a no-op by then;
            // measured as dropped frames in a CPU-throttled pan test before this split.
            <path d={linePath} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          ) : (
            <motion.path
              d={linePath}
              fill="none"
              stroke={color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
            />
          ))}

        {hoverPoint && (
          <g>
            <line
              x1={x(dateToMs(hoverPoint.date))}
              x2={x(dateToMs(hoverPoint.date))}
              y1={PAD_TOP}
              y2={PAD_TOP + plotHeight}
              stroke="var(--text-secondary)"
              strokeWidth={1}
            />
            <circle cx={x(dateToMs(hoverPoint.date))} cy={y(hoverPoint.value)} r={4} fill={color} />
          </g>
        )}
      </svg>

      {hoverPoint && (
        <div
          className="pointer-events-none absolute top-1 rounded-md border border-border bg-surface px-2 py-1 text-xs shadow-sm"
          style={{ left: `clamp(4px, ${(x(dateToMs(hoverPoint.date)) / width) * 100}%, calc(100% - 100px))` }}
        >
          <div className="text-text-tertiary">{formatShortDate(hoverPoint.date)}</div>
          <div className="font-mono-nums text-text-primary">{formatValue(hoverPoint.value)}</div>
        </div>
      )}

      <ChartZoomButtons onZoomIn={zoomIn} onZoomOut={zoomOut} onReset={onResetDomain} />
      <p className="sr-only" aria-live="polite">
        {rangeLabel}
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
    ticks.push({ ms, label: formatShortDate(new Date(ms).toISOString().slice(0, 10)) });
  }
  return ticks;
}
