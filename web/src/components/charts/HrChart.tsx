import { useEffect, useRef, useState } from "react";
import type { LapMarker, SamplePoint, TrainingZones } from "../../lib/types";
import { formatDuration } from "../../lib/format";
import type { Domain } from "../../lib/useChartInteraction";
import { useChartInteraction } from "../../lib/useChartInteraction";
import { zoneColor } from "../../lib/zoneColors";
import type { ZoneName } from "../../lib/types";

const HEIGHT = 280;
const PAD_X = 40;
const PAD_TOP = 12;
const PAD_BOTTOM = 24;
const MIN_SPAN_S = 30;

function nearestPoint(points: SamplePoint[], targetS: number): SamplePoint | null {
  if (points.length === 0) return null;
  let best = points[0];
  let bestDist = Math.abs(best.elapsed_s - targetS);
  for (const p of points) {
    const d = Math.abs(p.elapsed_s - targetS);
    if (d < bestDist) {
      best = p;
      bestDist = d;
    }
  }
  return best;
}

export function HrChart({
  points,
  zonesConfig,
  maxHrSetting,
  avgHr,
  laps,
  trimmedTailS,
  overlay,
  domain,
  fullDomain,
  onDomainChange,
  onDomainSettled,
  onResetDomain,
}: {
  points: SamplePoint[];
  zonesConfig: TrainingZones;
  maxHrSetting: number | null;
  avgHr: number | null;
  laps: LapMarker[];
  trimmedTailS: number;
  overlay: "none" | "power" | "cadence";
  domain: Domain;
  fullDomain: Domain;
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

  const { handlers, hoverX, setHoverX, isPanning } = useChartInteraction({
    domain,
    fullDomain,
    minSpan: MIN_SPAN_S,
    plotWidthPx,
    surfaceRef: containerRef,
    padLeft: PAD_X,
    onViewChange: onDomainChange,
    onSettled: onDomainSettled,
    onDoubleTap: onResetDomain,
  });

  const width = plotWidthPx + PAD_X * 2;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;

  const hrValues = points.map((p) => p.hr).filter((v): v is number => v != null);
  const hrMin = Math.min(0, ...hrValues, maxHrSetting ?? 0);
  const hrMax = Math.max(maxHrSetting ?? 0, ...hrValues, 1) * 1.05;
  const hrRange = hrMax - hrMin || 1;

  const overlayValues = overlay === "none" ? [] : points.map((p) => (overlay === "power" ? p.power : p.cadence)).filter((v): v is number => v != null);
  const overlayMax = Math.max(1, ...overlayValues) * 1.1;

  const x = (s: number) => PAD_X + ((s - domain.min) / Math.max(domain.max - domain.min, 1)) * plotWidthPx;
  const yHr = (v: number) => PAD_TOP + plotHeight - ((v - hrMin) / hrRange) * plotHeight;
  const yOverlay = (v: number) => PAD_TOP + plotHeight - (v / overlayMax) * plotHeight;

  const visible = points.filter((p) => p.elapsed_s >= domain.min - 5 && p.elapsed_s <= domain.max + 5);
  const linePath = visible.length
    ? "M " + visible.filter((p) => p.hr != null).map((p) => `${x(p.elapsed_s)},${yHr(p.hr as number)}`).join(" L ")
    : null;

  const trimStart = trimmedTailS > 0 ? Math.max(...points.map((p) => p.elapsed_s), 0) - trimmedTailS : null;

  const hoverPoint = hoverX != null && !isPanning ? nearestPoint(points, hoverX) : null;

  if (points.length === 0) {
    return <div className="flex h-40 items-center justify-center text-sm text-text-tertiary">No heart-rate data for this activity.</div>;
  }

  return (
    <div ref={containerRef} className="relative">
      <div
        className="touch-none select-none outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        data-chart-surface="true"
        role="img"
        aria-label={`Heart rate over elapsed time. Focus and press +/- to zoom, arrow keys to pan, Escape to reset.`}
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
          {zonesConfig.zones.map((z) => {
            const lo = z.hr_lo ?? hrMin;
            const hi = z.hr_hi ?? hrMax;
            return (
              <g key={z.zone}>
                <rect x={PAD_X} width={plotWidthPx} y={yHr(hi)} height={Math.max(yHr(lo) - yHr(hi), 0)} fill={zoneColor(z.zone as ZoneName)} opacity={0.35} />
                <text x={width - PAD_X + 4} y={(yHr(lo) + yHr(hi)) / 2} fontSize={9} fill="var(--text-tertiary)" dominantBaseline="middle">
                  {z.zone}
                </text>
              </g>
            );
          })}

          {trimStart != null && trimStart < domain.max && (
            <rect
              x={x(Math.max(trimStart, domain.min))}
              width={Math.max(x(domain.max) - x(Math.max(trimStart, domain.min)), 0)}
              y={PAD_TOP}
              height={plotHeight}
              fill="var(--text-tertiary)"
              opacity={0.25}
            />
          )}

          {laps.slice(1).map((lap, i) => (
            <line key={i} x1={x(lap.offset_s)} x2={x(lap.offset_s)} y1={PAD_TOP} y2={PAD_TOP + plotHeight} stroke="var(--text-secondary)" strokeWidth={1} strokeDasharray="2 2" opacity={0.6} />
          ))}

          {maxHrSetting != null && (
            <line x1={PAD_X} x2={PAD_X + plotWidthPx} y1={yHr(maxHrSetting)} y2={yHr(maxHrSetting)} stroke="var(--text-primary)" strokeWidth={1} strokeDasharray="4 3" opacity={0.6} />
          )}
          {avgHr != null && (
            <line x1={PAD_X} x2={PAD_X + plotWidthPx} y1={yHr(avgHr)} y2={yHr(avgHr)} stroke="var(--text-secondary)" strokeWidth={1} strokeDasharray="4 3" opacity={0.5} />
          )}

          {overlay !== "none" &&
            visible
              .filter((p) => (overlay === "power" ? p.power : p.cadence) != null)
              .map((p, i) => (
                <circle key={i} cx={x(p.elapsed_s)} cy={yOverlay((overlay === "power" ? p.power : p.cadence) as number)} r={1.2} fill="var(--text-tertiary)" opacity={0.6} />
              ))}

          {linePath && <path d={linePath} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />}

          {hoverPoint && hoverPoint.hr != null && (
            <g>
              <line x1={x(hoverPoint.elapsed_s)} x2={x(hoverPoint.elapsed_s)} y1={PAD_TOP} y2={PAD_TOP + plotHeight} stroke="var(--text-secondary)" strokeWidth={1} />
              <circle cx={x(hoverPoint.elapsed_s)} cy={yHr(hoverPoint.hr)} r={4} fill="var(--accent)" />
            </g>
          )}

          {[hrMin, (hrMin + hrMax) / 2, hrMax].map((v, i) => (
            <text key={i} x={2} y={yHr(v) - 3} fontSize={10} fill="var(--text-tertiary)" className="font-mono-nums">
              {Math.round(v)}
            </text>
          ))}
          {Array.from({ length: 5 }, (_, i) => domain.min + ((domain.max - domain.min) * i) / 4).map((s, i) => (
            <text key={i} x={x(s)} y={HEIGHT - 6} fontSize={10} fill="var(--text-tertiary)" textAnchor="middle">
              {formatDuration(s)}
            </text>
          ))}
        </svg>
      </div>

      {hoverPoint && (
        <div
          data-testid="hr-chart-tooltip"
          className="pointer-events-none absolute top-1 rounded-md border border-border bg-surface px-2 py-1 text-xs shadow-sm"
          style={{ left: `clamp(4px, ${(x(hoverPoint.elapsed_s) / width) * 100}%, calc(100% - 100px))` }}
        >
          <div className="text-text-tertiary">{formatDuration(hoverPoint.elapsed_s)}</div>
          {hoverPoint.hr != null && <div className="font-mono-nums text-text-primary">{hoverPoint.hr} bpm</div>}
          {overlay === "power" && hoverPoint.power != null && <div className="font-mono-nums text-text-secondary">{hoverPoint.power} W</div>}
          {overlay === "cadence" && hoverPoint.cadence != null && <div className="font-mono-nums text-text-secondary">{hoverPoint.cadence} spm</div>}
        </div>
      )}
    </div>
  );
}
