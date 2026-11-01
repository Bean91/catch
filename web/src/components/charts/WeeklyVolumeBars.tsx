import { motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { formatShortDate } from "../../lib/format";
import type { VolumeWeek } from "../../lib/types";
import { ZONE_NAMES } from "../../lib/types";
import type { Domain } from "../../lib/useChartInteraction";
import { useChartInteraction } from "../../lib/useChartInteraction";
import { useReducedMotion } from "../../lib/useReducedMotion";
import { zoneColor } from "../../lib/zoneColors";
import { ChartZoomButtons } from "./ChartZoomButtons";

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
  onDomainChange,
  onDomainSettled,
  onResetDomain,
}: {
  weeks: VolumeWeek[];
  domain: Domain;
  fullDomain: Domain;
  onDomainChange: (domain: Domain) => void;
  onDomainSettled?: (domain: Domain) => void;
  onResetDomain: () => void;
}) {
  const reduced = useReducedMotion();
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

  const { handlers, zoomIn, zoomOut, hoverX, setHoverX } = useChartInteraction({
    domain,
    fullDomain,
    minSpan: WEEK_MS * 4,
    plotWidthPx,
    onViewChange: onDomainChange,
    onSettled: onDomainSettled,
    onDoubleTap: onResetDomain,
  });

  const width = plotWidthPx + PAD_X * 2;
  const visible = weeks.filter((w) => weekMs(w.week_start) + WEEK_MS >= domain.min && weekMs(w.week_start) <= domain.max);
  const totals = visible.map((w) => ZONE_NAMES.reduce((sum, z) => sum + w.zones[z], 0));
  const max = Math.max(...totals, 1);
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const anyEstimated = visible.some((w) => w.estimated);

  const x = (ms: number) => PAD_X + ((ms - domain.min) / Math.max(domain.max - domain.min, 1)) * plotWidthPx;
  const spanWeeks = Math.max((domain.max - domain.min) / WEEK_MS, 1);
  const barWidth = Math.max((plotWidthPx / spanWeeks) * 0.6, 2);

  const hovered =
    hoverX != null
      ? visible.reduce<VolumeWeek | null>((best, w) => {
          if (!best) return w;
          return Math.abs(weekMs(w.week_start) - hoverX) < Math.abs(weekMs(best.week_start) - hoverX) ? w : best;
        }, null)
      : null;

  if (totals.every((t) => t === 0)) {
    return <div className="flex h-40 items-center justify-center text-sm text-text-tertiary">No training volume in range yet.</div>;
  }

  return (
    <div ref={containerRef} className="relative">
      <svg
        width="100%"
        height={HEIGHT}
        viewBox={`0 0 ${width} ${HEIGHT}`}
        role="img"
        aria-label="Weekly training volume by zone"
        tabIndex={0}
        className="touch-pan-y select-none outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        data-chart-surface="true"
        style={{ touchAction: "pan-y" }}
        onPointerDown={handlers.onPointerDown}
        onPointerMove={handlers.onPointerMove}
        onPointerUp={handlers.onPointerUp}
        onPointerCancel={handlers.onPointerCancel}
        onPointerLeave={() => setHoverX(null)}
        onWheel={handlers.onWheel}
        onKeyDown={handlers.onKeyDown}
        onDoubleClick={handlers.onDoubleClick}
      >
        {visible.map((w) => {
          const total = ZONE_NAMES.reduce((sum, z) => sum + w.zones[z], 0);
          const barX = x(weekMs(w.week_start) + WEEK_MS / 2) - barWidth / 2;
          let yCursor = PAD_TOP + plotHeight;
          return (
            <g key={w.week_start} opacity={hovered && hovered !== w ? 0.55 : 1}>
              {ZONE_NAMES.map((z) => {
                const secs = w.zones[z];
                const h = total > 0 ? (secs / max) * plotHeight : 0;
                yCursor -= h;
                return h > 0 ? (
                  <motion.rect
                    key={z}
                    x={barX}
                    width={barWidth}
                    y={yCursor}
                    height={h}
                    fill={zoneColor(z)}
                    initial={reduced ? { opacity: 1 } : { opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: reduced ? 0 : 0.4 }}
                  />
                ) : null;
              })}
              {w.estimated && total > 0 && (
                <text x={barX + barWidth / 2} y={PAD_TOP + plotHeight - (total / max) * plotHeight - 4} fontSize={9} fill="var(--text-tertiary)" textAnchor="middle">
                  ~
                </text>
              )}
            </g>
          );
        })}
        {visible
          .filter((_, i) => i % Math.max(1, Math.ceil(visible.length / 8)) === 0)
          .map((w) => (
            <text key={w.week_start} x={x(weekMs(w.week_start) + WEEK_MS / 2)} y={HEIGHT - 6} fontSize={9} fill="var(--text-tertiary)" textAnchor="middle">
              {formatShortDate(w.week_start)}
            </text>
          ))}
      </svg>

      {hovered && (
        <div className="pointer-events-none absolute top-1 left-1 rounded-md border border-border bg-surface px-2 py-1 text-xs shadow-sm">
          <div className="text-text-tertiary">Week of {formatShortDate(hovered.week_start)}</div>
          {ZONE_NAMES.filter((z) => hovered.zones[z] > 0).map((z) => (
            <div key={z} className="flex items-center gap-1.5 font-mono-nums text-text-primary">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: zoneColor(z) }} />
              {z}: {Math.round(hovered.zones[z] / 60)}m
            </div>
          ))}
        </div>
      )}

      <ChartZoomButtons onZoomIn={zoomIn} onZoomOut={zoomOut} onReset={onResetDomain} />

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-tertiary">
        {ZONE_NAMES.map((z) => (
          <span key={z} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: zoneColor(z) }} />
            {z}
          </span>
        ))}
        {anyEstimated && <span className="ml-auto">~ estimated from average HR (no per-stroke data)</span>}
      </div>
    </div>
  );
}
