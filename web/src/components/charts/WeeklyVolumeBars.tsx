import { useEffect, useMemo, useRef, useState } from "react";
import { formatShortDate } from "../../lib/format";
import type { VolumeWeek } from "../../lib/types";
import { ZONE_NAMES } from "../../lib/types";
import type { Domain } from "../../lib/useChartInteraction";
import { useChartInteraction } from "../../lib/useChartInteraction";
import { zoneColor } from "../../lib/zoneColors";
import { ChartTooltip, YGrid, nearestIndex, niceTicks } from "./core";

function roundedTop(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.min(r, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

const HEIGHT = 220;
const PAD_X = 12;
const PAD_TOP = 12;
const PAD_BOTTOM = 24;
const WEEK_MS = 7 * 86_400_000;

function weekMs(weekStart: string): number {
  return new Date(weekStart + "T00:00:00").getTime();
}

export function WeeklyVolumeBars({
  weeks,
  domain,
  fullDomain,
  minSpan = WEEK_MS * 4,
  onDomainChange,
  onDomainSettled,
  onResetDomain,
}: {
  weeks: VolumeWeek[];
  domain: Domain;
  fullDomain: Domain;
  /** Defaults to 4 weeks (a volume chart has nothing to show inside a single week), but a
   * caller linking this to a sibling chart with a *smaller* minimum zoom (e.g. Trends'
   * 7-day-minimum metric chart) must pass that same value — otherwise this chart's own
   * clamp-on-mount silently widens the shared domain back out, fighting the other chart's
   * "7d" preset every time it's picked. */
  minSpan?: number;
  onDomainChange: (domain: Domain) => void;
  onDomainSettled?: (domain: Domain) => void;
  onResetDomain: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [plotWidthPx, setPlotWidthPx] = useState(600);

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

  const { handlers, hoverX, setHoverX } = useChartInteraction({
    domain,
    fullDomain,
    minSpan,
    plotWidthPx,
    surfaceRef: containerRef,
    padLeft: PAD_X,
    onViewChange: onDomainChange,
    onSettled: onDomainSettled,
    onDoubleTap: onResetDomain,
  });

  const width = plotWidthPx + PAD_X * 2;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const starts = useMemo(() => weeks.map((w) => weekMs(w.week_start)), [weeks]);
  const totalsAll = useMemo(() => weeks.map((w) => ZONE_NAMES.reduce((sum, z) => sum + w.zones[z], 0)), [weeks]);
  const visibleIdx: number[] = [];
  for (let i = 0; i < weeks.length; i++) if (starts[i] + WEEK_MS >= domain.min && starts[i] <= domain.max) visibleIdx.push(i);
  const visible = visibleIdx.map((i) => weeks[i]);
  const totals = visibleIdx.map((i) => totalsAll[i]);
  const maxSecs = Math.max(...totals, 1);
  // The y-axis is in hours, on rounded ticks, so a bar's height reads as an amount, not just a comparison.
  const nice = niceTicks(0, maxSecs / 3600, 3);
  const max = nice.max * 3600 || 1;
  const anyEstimated = visible.some((w) => w.estimated);

  const x = (ms: number) => PAD_X + ((ms - domain.min) / Math.max(domain.max - domain.min, 1)) * plotWidthPx;
  const yOfHours = (h: number) => PAD_TOP + plotHeight - (h / nice.max) * plotHeight;
  const spanWeeks = Math.max((domain.max - domain.min) / WEEK_MS, 1);
  const barWidth = Math.max((plotWidthPx / spanWeeks) * 0.62, 2);
  const radius = Math.min(4, barWidth / 2);

  const hovered = hoverX != null && visibleIdx.length ? weeks[nearestIndex(starts, hoverX - WEEK_MS / 2)] : null;

  if (totals.every((t) => t === 0)) {
    return <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-border-strong/60 text-sm text-text-tertiary">No training volume in range yet.</div>;
  }

  return (
    <div ref={containerRef} className="relative">
      <div
        className="touch-none select-none outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        // See TrendLineChart's identical note: handlers + touch-action live on this HTML div,
        // not the <svg> — WebKit's touch-action support on SVG root elements has real gaps
        // that only surfaced testing on a real iPhone, not Chromium's CDP touch emulation.
        data-chart-surface="true"
        role="img"
        aria-label="Weekly training volume by zone. Focus and press +/- to zoom, arrow keys to pan, Escape to reset."
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
        <YGrid ticks={nice.ticks} y={yOfHours} x0={PAD_X} x1={PAD_X + plotWidthPx} format={(h) => (h === 0 ? "0" : `${h}h`)} />
        {visible.map((w, vi) => {
          const total = totals[vi];
          const barX = x(starts[visibleIdx[vi]] + WEEK_MS / 2) - barWidth / 2;
          let yCursor = PAD_TOP + plotHeight;
          const segs = ZONE_NAMES.filter((z) => w.zones[z] > 0);
          return (
            <g key={w.week_start} opacity={hovered && hovered !== w ? 0.5 : 1}>
              {segs.map((z, si) => {
                const h = (w.zones[z] / max) * plotHeight;
                yCursor -= h;
                const top = si === segs.length - 1;
                // A 1.5px surface gap between segments; only the top segment gets rounded corners.
                const hh = Math.max(h - (top ? 0 : 1.5), 0.5);
                return top ? (
                  <path key={z} d={roundedTop(barX, yCursor, barWidth, hh, radius)} fill={zoneColor(z)} />
                ) : (
                  <rect key={z} x={barX} width={barWidth} y={yCursor + (h - hh)} height={hh} fill={zoneColor(z)} />
                );
              })}
              {w.estimated && total > 0 && (
                <text x={barX + barWidth / 2} y={PAD_TOP + plotHeight - (total / max) * plotHeight - 4} fontSize={10} fill="var(--text-tertiary)" textAnchor="middle">
                  ~
                </text>
              )}
            </g>
          );
        })}
        {visible
          .filter((_, i) => i % Math.max(1, Math.ceil(visible.length / 8)) === 0)
          .map((w) => (
            <text key={w.week_start} x={x(weekMs(w.week_start) + WEEK_MS / 2)} y={HEIGHT - 6} fontSize={10} fill="var(--text-tertiary)" textAnchor="middle">
              {formatShortDate(w.week_start)}
            </text>
          ))}
      </svg>
      </div>

      {hovered && (
        <ChartTooltip
          xPct={((x(weekMs(hovered.week_start) + WEEK_MS / 2)) / width) * 100}
          title={`Week of ${formatShortDate(hovered.week_start)}`}
          rows={ZONE_NAMES.filter((z) => hovered.zones[z] > 0).map((z) => ({ label: z, value: `${Math.round(hovered.zones[z] / 60)}m`, color: zoneColor(z) }))}
        />
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-tertiary">
        {ZONE_NAMES.map((z) => (
          <span key={z} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: zoneColor(z) }} />
            {z}
          </span>
        ))}
        {anyEstimated && <span className="ml-auto">~ estimated from average HR (no per-stroke data)</span>}
      </div>
    </div>
  );
}
