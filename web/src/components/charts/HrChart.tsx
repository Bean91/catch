import { useMemo, useRef, useState, useLayoutEffect } from "react";
import type { LapMarker, SamplePoint, TrainingZones } from "../../lib/types";
import { formatDuration } from "../../lib/format";
import type { Domain } from "../../lib/useChartInteraction";
import { useChartInteraction } from "../../lib/useChartInteraction";
import { zoneColor } from "../../lib/zoneColors";
import { METRIC_COLOR } from "../../lib/metricColors";
import { AreaGradient, ChartTooltip, areaPath, linePath, lowerBound, nearestIndex, niceTicks, useSvgId } from "./core";
import type { ZoneName } from "../../lib/types";

const HR_HEIGHT = 240;
const OVERLAY_HEIGHT = 92; // a second panel under the HR plot, sharing its time axis (never a second y-axis on one plot)
const PANEL_GAP = 22;
const PAD_X = 40;
const PAD_RIGHT = 36;
const PAD_TOP = 14;
const PAD_BOTTOM = 24;
const MIN_SPAN_S = 30;

const OVERLAY_UNITS: Record<"power" | "cadence", string> = { power: "W", cadence: "spm" };
const OVERLAY_LABEL: Record<"power" | "cadence", string> = { power: "Power", cadence: "Stroke rate" };
const OVERLAY_COLOR: Record<"power" | "cadence", string> = { power: METRIC_COLOR.power, cadence: METRIC_COLOR.rate };

export interface PieceBand {
  id: number;
  startS: number;
  endS: number;
}

export function HrChart({
  points,
  allPoints,
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
  pieceBands,
  selectedPieceId,
  onPieceDragEnd,
}: {
  points: SamplePoint[];
  /** Full-recording points (any resolution) used only to pick stable axis bounds, so the
   * y-axis doesn't rescale on every pan/zoom refetch of `points`. Falls back to `points`. */
  allPoints?: SamplePoint[];
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
  /** Session 17 (see PLAN.md Part D.1) — pieces aligned to this chart's own sample stream,
   * shown as a shaded band. Only `selectedPieceId`'s band gets a drag handle at its start
   * edge; the rest are shown read-only so a crowded session doesn't offer several
   * simultaneous drag targets at once. */
  pieceBands?: PieceBand[];
  selectedPieceId?: number | null;
  onPieceDragEnd?: (pieceId: number, startS: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidthPx, setContainerWidthPx] = useState(600 + PAD_X * 2);
  const padRight = PAD_RIGHT;
  const plotWidthPx = Math.max(containerWidthPx - PAD_X - padRight, 50);
  const gradId = useSvgId("hr-area");
  const clipId = useSvgId("hr-clip");

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setContainerWidthPx(el.clientWidth || 680);
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setContainerWidthPx(w);
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

  const width = plotWidthPx + PAD_X + padRight;
  const plotHeight = HR_HEIGHT - PAD_TOP - PAD_BOTTOM;
  const HEIGHT = overlay === "none" ? HR_HEIGHT : HR_HEIGHT + PANEL_GAP + OVERLAY_HEIGHT;
  const overlayTop = HR_HEIGHT + PANEL_GAP - PAD_BOTTOM + 6;

  // Session 17 (see PLAN.md Part D.1) — dragging a piece's start handle. Live local state
  // while the pointer moves, same live/settled split every other chart gesture here uses
  // (DESIGN.md); onPieceDragEnd (a PATCH) only fires once, on release.
  const dragRef = useRef<{ pieceId: number; pointerId: number; startClientX: number; originalStartS: number; durationS: number } | null>(null);
  const [dragLiveStartS, setDragLiveStartS] = useState<number | null>(null);

  const onHandlePointerDown = (band: PieceBand) => (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragRef.current = { pieceId: band.id, pointerId: e.pointerId, startClientX: e.clientX, originalStartS: band.startS, durationS: band.endS - band.startS };
    setDragLiveStartS(band.startS);
  };
  const onHandlePointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    e.stopPropagation();
    const deltaS = ((e.clientX - drag.startClientX) / plotWidthPx) * (domain.max - domain.min);
    setDragLiveStartS(Math.max(fullDomain.min, Math.min(fullDomain.max - drag.durationS, drag.originalStartS + deltaS)));
  };
  const onHandlePointerUp = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    e.stopPropagation();
    const finalStart = dragLiveStartS ?? drag.originalStartS;
    dragRef.current = null;
    setDragLiveStartS(null);
    onPieceDragEnd?.(drag.pieceId, Math.round(finalStart));
  };

  const axisPoints = allPoints ?? points;
  // Axis bounds come from the full recording (`allPoints`), not the zoom window, so the y-axis doesn't rescale on every pan/zoom
  // refetch; starting near the lowest observed HR avoids a half-empty plot for a typical 120–180 bpm session.
  const axis = useMemo(() => {
    let lo = Infinity;
    let hi = -Infinity;
    let oHi = 1;
    for (const p of axisPoints) {
      if (p.hr != null) {
        if (p.hr < lo) lo = p.hr;
        if (p.hr > hi) hi = p.hr;
      }
      const o = overlay === "power" ? p.power : overlay === "cadence" ? p.cadence : null;
      if (o != null && o > oHi) oHi = o;
    }
    if (lo === Infinity) {
      lo = 60;
      hi = 180;
    }
    const nice = niceTicks(Math.max(0, lo - 8), Math.max(hi, maxHrSetting ?? 0) + 4, 4);
    const oNice = niceTicks(0, oHi, 2);
    return { hrMin: nice.min, hrMax: nice.max, ticks: nice.ticks, overlayMax: oNice.max, overlayTicks: oNice.ticks };
  }, [axisPoints, overlay, maxHrSetting]);
  const { hrMin, hrMax } = axis;
  const hrRange = hrMax - hrMin || 1;
  const overlayMax = axis.overlayMax || 1;
  const overlayPlotH = OVERLAY_HEIGHT - 16;

  const x = (s: number) => PAD_X + ((s - domain.min) / Math.max(domain.max - domain.min, 1)) * plotWidthPx;
  const yHr = (v: number) => PAD_TOP + plotHeight - ((v - hrMin) / hrRange) * plotHeight;
  const yOverlay = (v: number) => overlayTop + overlayPlotH - (v / overlayMax) * overlayPlotH;

  const elapsed = useMemo(() => points.map((p) => p.elapsed_s), [points]);
  const paths = useMemo(() => {
    const lo = Math.max(lowerBound(elapsed, domain.min - 5) - 1, 0);
    const hi = Math.min(lowerBound(elapsed, domain.max + 5) + 1, points.length);
    const span = Math.max(domain.max - domain.min, 1);
    const xs: number[] = [];
    const ys: (number | null)[] = [];
    const os: (number | null)[] = [];
    for (let i = lo; i < hi; i++) {
      const p = points[i];
      xs.push(PAD_X + ((p.elapsed_s - domain.min) / span) * plotWidthPx);
      ys.push(p.hr != null ? PAD_TOP + plotHeight - ((p.hr - hrMin) / hrRange) * plotHeight : null);
      if (overlay !== "none") {
        const o = overlay === "power" ? p.power : p.cadence;
        os.push(o != null ? overlayTop + overlayPlotH - (o / overlayMax) * overlayPlotH : null);
      }
    }
    return {
      line: xs.length ? linePath(xs, ys, false) : null,
      area: xs.length > 1 ? areaPath(xs, ys, PAD_TOP + plotHeight, false) : null,
      overlayLine: overlay !== "none" && xs.length ? linePath(xs, os, false) : null,
    };
  }, [points, elapsed, domain.min, domain.max, plotWidthPx, plotHeight, hrMin, hrRange, overlay, overlayTop, overlayPlotH, overlayMax]);

  // Derived from fullDomain, not `points` — `points` is only the current zoom window since
  // the live/settled windowed refetch, so computing this from it greys the wrong stretch of
  // the chart whenever the view is zoomed in anywhere but the very end (advisor review finding).
  const trimStart = trimmedTailS > 0 ? fullDomain.max - trimmedTailS : null;

  const hoverIdx = hoverX != null && !isPanning ? nearestIndex(elapsed, hoverX) : -1;
  const hoverPoint = hoverIdx >= 0 ? points[hoverIdx] : null;

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
          <defs>
            <AreaGradient id={gradId} color={METRIC_COLOR.hr} from={0.28} />
            <clipPath id={clipId}>
              <rect x={PAD_X} y={0} width={plotWidthPx} height={HEIGHT} />
            </clipPath>
          </defs>
          {zonesConfig.zones.map((z) => {
            // Clamped to the visible HR range: with the axis no longer pinned at 0, a zone's
            // configured hr_lo/hr_hi can fall outside [hrMin, hrMax], which would otherwise
            // draw the band (and its label) over the x-axis labels (advisor review finding).
            const lo = Math.max(z.hr_lo ?? hrMin, hrMin);
            const hi = Math.min(z.hr_hi ?? hrMax, hrMax);
            if (hi <= lo) return null;
            return (
              <g key={z.zone}>
                <rect x={PAD_X} width={plotWidthPx} y={yHr(hi)} height={Math.max(yHr(lo) - yHr(hi), 0)} fill={zoneColor(z.zone as ZoneName)} opacity={0.16} />
                <line x1={PAD_X} x2={PAD_X + plotWidthPx} y1={yHr(lo)} y2={yHr(lo)} stroke={zoneColor(z.zone as ZoneName)} strokeWidth={1} opacity={0.5} />
                <text x={PAD_X + plotWidthPx + 6} y={(yHr(lo) + yHr(hi)) / 2} fontSize={10} fill="var(--text-tertiary)" dominantBaseline="middle">
                  {z.zone}
                </text>
              </g>
            );
          })}

          {axis.ticks.map((v, i) => (
            <text key={i} x={2} y={yHr(v) + 3} fontSize={10} fill="var(--text-tertiary)" className="font-mono-nums">
              {Math.round(v)}
            </text>
          ))}

          <g clipPath={`url(#${clipId})`}>
            {trimStart != null && trimStart < domain.max && (
              <rect
                x={x(Math.max(trimStart, domain.min))}
                width={Math.max(x(domain.max) - x(Math.max(trimStart, domain.min)), 0)}
                y={PAD_TOP}
                height={plotHeight}
                fill="var(--text-tertiary)"
                opacity={0.2}
              />
            )}

            {laps.slice(1).map((lap, i) => (
              <line key={i} x1={x(lap.offset_s)} x2={x(lap.offset_s)} y1={PAD_TOP} y2={PAD_TOP + plotHeight} stroke="var(--text-secondary)" strokeWidth={1} strokeDasharray="2 3" opacity={0.5} />
            ))}

            {(pieceBands ?? []).map((band) => {
              const isDraggingThis = dragRef.current?.pieceId === band.id && dragLiveStartS != null;
              const startS = isDraggingThis ? dragLiveStartS! : band.startS;
              const endS = startS + (band.endS - band.startS);
              const lo = Math.max(startS, domain.min);
              const hi = Math.min(endS, domain.max);
              if (hi <= lo) return null;
              return <rect key={band.id} x={x(lo)} width={Math.max(x(hi) - x(lo), 0)} y={PAD_TOP} height={plotHeight} fill="var(--accent)" opacity={band.id === selectedPieceId ? 0.22 : 0.1} />;
            })}

            {maxHrSetting != null && (
              <line x1={PAD_X} x2={PAD_X + plotWidthPx} y1={yHr(maxHrSetting)} y2={yHr(maxHrSetting)} stroke="var(--text-primary)" strokeWidth={1} strokeDasharray="4 3" opacity={0.5} />
            )}
            {avgHr != null && (
              <line x1={PAD_X} x2={PAD_X + plotWidthPx} y1={yHr(avgHr)} y2={yHr(avgHr)} stroke="var(--text-secondary)" strokeWidth={1} strokeDasharray="4 3" opacity={0.6} />
            )}

            {paths.area && <path d={paths.area} fill={`url(#${gradId})`} />}
            {paths.line && <path d={paths.line} fill="none" stroke={METRIC_COLOR.hr} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />}

            {overlay !== "none" && paths.overlayLine && (
              <path d={paths.overlayLine} fill="none" stroke={OVERLAY_COLOR[overlay]} strokeWidth={1.5} strokeLinejoin="round" />
            )}
          </g>

          {overlay !== "none" && (
            <g>
              <text x={PAD_X} y={overlayTop - 6} fontSize={10} fontWeight={600} fill="var(--text-secondary)">
                {OVERLAY_LABEL[overlay]} ({OVERLAY_UNITS[overlay]})
              </text>
              {axis.overlayTicks.map((v, i) => (
                <g key={i}>
                  <line x1={PAD_X} x2={PAD_X + plotWidthPx} y1={yOverlay(v)} y2={yOverlay(v)} stroke="var(--border)" strokeDasharray={i === 0 ? undefined : "2 4"} />
                  <text x={2} y={yOverlay(v) + 3} fontSize={10} fill="var(--text-tertiary)" className="font-mono-nums">
                    {Math.round(v)}
                  </text>
                </g>
              ))}
            </g>
          )}

          {hoverPoint && (
            <g>
              <line x1={x(hoverPoint.elapsed_s)} x2={x(hoverPoint.elapsed_s)} y1={PAD_TOP} y2={HEIGHT - PAD_BOTTOM + (overlay === "none" ? 0 : 6)} stroke="var(--text-tertiary)" strokeWidth={1} strokeDasharray="3 3" />
              {hoverPoint.hr != null && <circle cx={x(hoverPoint.elapsed_s)} cy={yHr(hoverPoint.hr)} r={4.5} fill={METRIC_COLOR.hr} stroke="var(--surface)" strokeWidth={2} />}
            </g>
          )}

          {Array.from({ length: 5 }, (_, i) => domain.min + ((domain.max - domain.min) * i) / 4).map((s, i) => (
            <text key={i} x={x(s)} y={(overlay === "none" ? HR_HEIGHT : HEIGHT) - 6} fontSize={10} fill="var(--text-tertiary)" textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"}>
              {formatDuration(s)}
            </text>
          ))}
        </svg>
      </div>

      {selectedPieceId != null &&
        onPieceDragEnd &&
        (() => {
          const band = pieceBands?.find((b) => b.id === selectedPieceId);
          if (!band) return null;
          const isDraggingThis = dragRef.current?.pieceId === band.id && dragLiveStartS != null;
          const startS = isDraggingThis ? dragLiveStartS! : band.startS;
          // Only while the piece's start is in view: outside it the handle would sit past the chart's edge and widen a phone's page.
          if (!isDraggingThis && (startS < domain.min || startS > domain.max)) return null;
          const leftPx = x(startS);
          return (
            <div
              role="slider"
              aria-label="Drag to realign this piece's start"
              aria-valuenow={Math.round(startS)}
              tabIndex={0}
              onPointerDown={onHandlePointerDown(band)}
              onPointerMove={onHandlePointerMove}
              onPointerUp={onHandlePointerUp}
              onPointerCancel={onHandlePointerUp}
              className="absolute flex w-11 -translate-x-1/2 touch-none cursor-ew-resize items-center justify-center outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
              style={{ left: leftPx, top: PAD_TOP, height: plotHeight }}
            >
              <div className="h-full w-0.5 rounded bg-accent" />
            </div>
          );
        })()}

      {hoverPoint && (
        <ChartTooltip
          testId="hr-chart-tooltip"
          xPct={(x(hoverPoint.elapsed_s) / width) * 100}
          title={formatDuration(hoverPoint.elapsed_s)}
          rows={[
            ...(hoverPoint.hr != null ? [{ label: "Heart rate", value: `${hoverPoint.hr} bpm`, color: METRIC_COLOR.hr }] : []),
            ...(overlay === "power" && hoverPoint.power != null ? [{ label: "Power", value: `${hoverPoint.power} W`, color: METRIC_COLOR.power }] : []),
            ...(overlay === "cadence" && hoverPoint.cadence != null ? [{ label: "Rate", value: `${hoverPoint.cadence} spm`, color: METRIC_COLOR.rate }] : []),
          ]}
        />
      )}
    </div>
  );
}
