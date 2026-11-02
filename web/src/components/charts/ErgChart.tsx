import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { hrZoneForHr } from "../../lib/hrZone";
import { formatDistance, formatSplit } from "../../lib/format";
import type { Stroke, ZoneName } from "../../lib/types";
import type { Domain } from "../../lib/useChartInteraction";
import { useChartInteraction } from "../../lib/useChartInteraction";
import { useReducedMotion } from "../../lib/useReducedMotion";
import { zoneColor } from "../../lib/zoneColors";
import { EmptyState } from "../ui/EmptyState";
import { ChartZoomButtons } from "./ChartZoomButtons";

const WIDTH = 640;
const HEIGHT = 260;
const PAD_X = 12;
const PAD_TOP = 12;
const BAND_HEIGHT = 14;
const PAD_BOTTOM = BAND_HEIGHT + 8;
const PLOT_HEIGHT = HEIGHT - PAD_TOP - PAD_BOTTOM;
const MIN_SPAN_M = 50;

function scaleY(values: number[]): (v: number) => number {
  if (values.length === 0) return () => PAD_TOP + PLOT_HEIGHT;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return (v: number) => PAD_TOP + PLOT_HEIGHT - ((v - min) / range) * PLOT_HEIGHT;
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

function nearestStroke(strokes: Stroke[], distance: number): Stroke | null {
  if (strokes.length === 0) return null;
  let best = strokes[0];
  let bestDist = Math.abs((best.distance_cum ?? 0) - distance);
  for (const s of strokes) {
    const d = Math.abs((s.distance_cum ?? 0) - distance);
    if (d < bestDist) {
      best = s;
      bestDist = d;
    }
  }
  return best;
}

export function ErgChart({
  strokes,
  maxHr,
  hrPct,
  domain,
  fullDomain,
  onDomainChange,
  onDomainSettled,
  onResetDomain,
  hoveredInterval,
  onHoverInterval,
}: {
  strokes: Stroke[];
  maxHr: number | null;
  hrPct: Record<string, number>;
  domain: Domain;
  fullDomain: Domain;
  onDomainChange: (domain: Domain) => void;
  onDomainSettled?: (domain: Domain) => void;
  onResetDomain: () => void;
  hoveredInterval?: number | null;
  onHoverInterval?: (index: number | null) => void;
}) {
  const reduced = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const [plotWidthPx, setPlotWidthPx] = useState(WIDTH - PAD_X * 2);
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

  useEffect(() => {
    hasAnimatedIn.current = true;
  }, []);

  const { handlers, zoomIn, zoomOut, hoverX, setHoverX } = useChartInteraction({
    domain,
    fullDomain,
    minSpan: MIN_SPAN_M,
    plotWidthPx,
    surfaceRef: containerRef,
    padLeft: PAD_X,
    onViewChange: onDomainChange,
    onSettled: onDomainSettled,
    onDoubleTap: onResetDomain,
  });

  const withDistance = strokes.filter((s) => s.distance_cum != null).sort((a, b) => (a.distance_cum ?? 0) - (b.distance_cum ?? 0));

  if (withDistance.length < 2) {
    return <EmptyState message="Not enough per-stroke data to chart (Garmin-only erg sessions have no stroke-level data)." />;
  }

  const width = plotWidthPx + PAD_X * 2;
  const x = (d: number) => PAD_X + ((d - domain.min) / Math.max(domain.max - domain.min, 1)) * plotWidthPx;

  const visible = withDistance.filter((s) => (s.distance_cum ?? 0) >= domain.min && (s.distance_cum ?? 0) <= domain.max);
  const splitValues = visible.map((s) => s.pace_500m).filter((v): v is number => v != null);
  const wattsValues = visible.map((s) => s.watts).filter((v): v is number => v != null);
  const rateValues = visible.map((s) => s.stroke_rate).filter((v): v is number => v != null);
  const ySplit = invertedScaleY(splitValues);
  const yWatts = scaleY(wattsValues);
  const yRate = scaleY(rateValues);

  const bandSegments: { zone: ZoneName | null; x0: number; x1: number; interval: number }[] = [];
  let prevZone: ZoneName | null = null;
  let segStart = 0;
  withDistance.forEach((s, i) => {
    const zone = hrZoneForHr(s.hr, maxHr, hrPct) as ZoneName | null;
    const d = s.distance_cum as number;
    if (zone !== prevZone) {
      if (prevZone != null) bandSegments.push({ zone: prevZone, x0: segStart, x1: d, interval: s.interval_index ?? 0 });
      segStart = d;
      prevZone = zone;
    }
    if (i === withDistance.length - 1 && prevZone != null) bandSegments.push({ zone: prevZone, x0: segStart, x1: d, interval: s.interval_index ?? 0 });
  });

  const lines: { key: "pace_500m" | "watts"; color: string; y: (v: number) => number; label: string; dashed?: boolean }[] = [
    { key: "pace_500m", color: "var(--accent)", y: ySplit, label: "Split" },
    { key: "watts", color: "var(--text-secondary)", y: yWatts, label: "Watts", dashed: true },
  ];
  const rateDots = visible.filter((s) => s.stroke_rate != null);

  const linePath = (key: "pace_500m" | "watts", y: (v: number) => number) => {
    const defined = visible.filter((s) => s[key] != null);
    return defined.map((s) => `${x(s.distance_cum as number)},${y(s[key] as number)}`).join(" L ");
  };

  const hovered = hoverX != null ? nearestStroke(visible, hoverX) : null;
  const intervalBounds = (idx: number): { min: number; max: number } => {
    const inInterval = withDistance.filter((s) => (s.interval_index ?? 0) === idx);
    const ds = inInterval.map((s) => s.distance_cum as number);
    return { min: Math.min(...ds), max: Math.max(...ds) };
  };

  return (
    <div ref={containerRef} className="relative">
      <div
        className="touch-none select-none outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        // See TrendLineChart's identical note: handlers + touch-action live on this HTML div,
        // not the <svg> — WebKit's touch-action support on SVG root elements has real gaps
        // that only surfaced testing on a real iPhone, not Chromium's CDP touch emulation.
        data-chart-surface="true"
        role="img"
        aria-label="Split, watts and stroke rate over distance"
        tabIndex={0}
        onPointerDown={handlers.onPointerDown}
        onPointerMove={handlers.onPointerMove}
        onPointerUp={handlers.onPointerUp}
        onPointerCancel={handlers.onPointerCancel}
        onPointerLeave={() => {
          setHoverX(null);
          onHoverInterval?.(null);
        }}
        onKeyDown={handlers.onKeyDown}
        onDoubleClick={handlers.onDoubleClick}
      >
      <svg width="100%" height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`} aria-hidden="true" className="block">
        {hoveredInterval != null &&
          (() => {
            const { min, max } = intervalBounds(hoveredInterval);
            return <rect x={x(min)} width={Math.max(x(max) - x(min), 1)} y={PAD_TOP} height={PLOT_HEIGHT} fill="var(--accent)" opacity={0.08} />;
          })()}

        {rateDots.map((s, i) => (
          <circle key={i} cx={x(s.distance_cum as number)} cy={yRate(s.stroke_rate as number)} r={1.6} fill="var(--text-tertiary)" opacity={0.6} />
        ))}
        {lines.map((line) =>
          reduced || hasAnimatedIn.current ? (
            // Plain <path> once the one-time draw-in has played — see TrendLineChart's
            // identical split for why a motion.path re-rendered on every pan/zoom frame
            // (hundreds of times during a drag) is real, measured dropped-frame cost for an
            // animation that's already a no-op by then.
            <path
              key={line.key}
              d={`M ${linePath(line.key, line.y)}`}
              fill="none"
              stroke={line.color}
              strokeWidth={line.key === "pace_500m" ? 2.5 : 1.5}
              strokeDasharray={line.dashed ? "3 3" : undefined}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ) : (
            <motion.path
              key={line.key}
              d={`M ${linePath(line.key, line.y)}`}
              fill="none"
              stroke={line.color}
              strokeWidth={line.key === "pace_500m" ? 2.5 : 1.5}
              strokeDasharray={line.dashed ? "3 3" : undefined}
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
            />
          ),
        )}
        {bandSegments.map((seg, i) =>
          seg.zone ? (
            <rect
              key={i}
              x={x(seg.x0)}
              width={Math.max(x(seg.x1) - x(seg.x0), 1)}
              y={HEIGHT - BAND_HEIGHT}
              height={BAND_HEIGHT}
              fill={zoneColor(seg.zone)}
              onPointerEnter={() => onHoverInterval?.(seg.interval)}
              style={{ cursor: "pointer" }}
            />
          ) : null,
        )}

        {hovered && (
          <line
            x1={x(hovered.distance_cum as number)}
            x2={x(hovered.distance_cum as number)}
            y1={PAD_TOP}
            y2={PAD_TOP + PLOT_HEIGHT}
            stroke="var(--text-secondary)"
            strokeWidth={1}
          />
        )}
      </svg>
      </div>

      {hovered && (
        <div className="pointer-events-none absolute top-1 left-1 rounded-md border border-border bg-surface px-2 py-1 text-xs shadow-sm">
          <div className="text-text-tertiary">{formatDistance(hovered.distance_cum)}</div>
          {hovered.pace_500m != null && <div className="font-mono-nums text-text-primary">{formatSplit(hovered.pace_500m)}/500m</div>}
          {hovered.watts != null && <div className="font-mono-nums text-text-secondary">{hovered.watts.toFixed(0)}w</div>}
          {hovered.stroke_rate != null && <div className="font-mono-nums text-text-tertiary">{hovered.stroke_rate.toFixed(0)}spm</div>}
        </div>
      )}

      <ChartZoomButtons onZoomIn={zoomIn} onZoomOut={zoomOut} onReset={onResetDomain} />

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
