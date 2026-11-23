import { useEffect, useMemo, useRef, useState, useLayoutEffect } from "react";
import { zoneForBpm } from "../../lib/zoneColors";
import { formatDistance, formatDuration, formatSplit } from "../../lib/format";
import { METRIC_COLOR } from "../../lib/metricColors";
import type { Stroke, ZoneName } from "../../lib/types";
import type { Domain } from "../../lib/useChartInteraction";
import { useChartInteraction } from "../../lib/useChartInteraction";
import { useReducedMotion } from "../../lib/useReducedMotion";
import { zoneColor } from "../../lib/zoneColors";
import { EmptyState } from "../ui/EmptyState";
import { ChartTooltip, Legend, extent, linePath as buildLine, lowerBound, nearestIndex, niceTicks, secondsTicks, useSvgId } from "./core";

// Session 35: split, power and stroke rate are three small panels sharing one distance axis (they used to be three lines on three
// unlabelled scales over one plot). Each panel has its own labelled y-axis; one crosshair runs through all three.
const WIDTH = 640;
const PAD_LEFT = 44;
const PAD_RIGHT = 12;
const PANEL_H = 64;
const PANEL_GAP = 30;
const TOP = 20;
const BAND_HEIGHT = 12;
const MIN_SPAN_M = 50;

type PanelKey = "pace_500m" | "watts" | "stroke_rate" | "hr";
type Panel = { key: PanelKey; label: string; unit: string; color: string; inverted?: boolean };
const PANELS: Panel[] = [
  { key: "pace_500m", label: "Split", unit: "/500m", color: METRIC_COLOR.pace, inverted: true },
  { key: "watts", label: "Power", unit: "W", color: METRIC_COLOR.power },
  { key: "stroke_rate", label: "Rate", unit: "spm", color: METRIC_COLOR.rate },
];
// Session 36: the PM5's own heart rate (same recording, so aligned by construction) as a fourth panel when it has any.
const HR_PANEL: Panel = { key: "hr", label: "Heart rate", unit: "bpm", color: METRIC_COLOR.hr };

export function ErgChart({
  strokes,
  hrBoundsBpm,
  domain,
  fullDomain,
  onDomainChange,
  onDomainSettled,
  onResetDomain,
  hoveredInterval,
  onHoverInterval,
  externalHoverX,
  onHoverXChange,
}: {
  strokes: Stroke[];
  /** Each zone's lower bound in bpm, from the workout's own zone basis (server-computed — no zone maths here). */
  hrBoundsBpm: Record<string, number>;
  domain: Domain;
  fullDomain: Domain;
  onDomainChange: (domain: Domain) => void;
  onDomainSettled?: (domain: Domain) => void;
  onResetDomain: () => void;
  hoveredInterval?: number | null;
  onHoverInterval?: (index: number | null) => void;
  /** Session 36: a distance hovered on a linked chart (the heart-rate chart), shown here as this chart's own crosshair. */
  externalHoverX?: number | null;
  /** The distance hovered here, or null — so a linked chart can follow. */
  onHoverXChange?: (distance: number | null) => void;
}) {
  const reduced = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const [plotWidthPx, setPlotWidthPx] = useState(WIDTH - PAD_LEFT - PAD_RIGHT);
  const hasAnimatedIn = useRef(false);
  const clipId = useSvgId("erg-clip");

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setPlotWidthPx(Math.max((el.clientWidth || WIDTH) - PAD_LEFT - PAD_RIGHT, 50));
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setPlotWidthPx(Math.max(w - PAD_LEFT - PAD_RIGHT, 50));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    hasAnimatedIn.current = true;
  }, []);

  const { handlers, hoverX, setHoverX } = useChartInteraction({
    domain,
    fullDomain,
    minSpan: MIN_SPAN_M,
    plotWidthPx,
    surfaceRef: containerRef,
    padLeft: PAD_LEFT,
    onViewChange: onDomainChange,
    onSettled: onDomainSettled,
    onDoubleTap: onResetDomain,
  });

  // Sorted once per data change (it used to filter and sort every stroke on every render).
  const withDistance = useMemo(
    () => strokes.filter((s) => s.distance_cum != null).sort((a, b) => (a.distance_cum ?? 0) - (b.distance_cum ?? 0)),
    [strokes],
  );
  const dists = useMemo(() => withDistance.map((s) => s.distance_cum as number), [withDistance]);
  const panelDefs = useMemo(() => (withDistance.some((s) => s.hr != null) ? [...PANELS, HR_PANEL] : PANELS), [withDistance]);
  const nPanels = panelDefs.length;
  const BAND_Y = TOP + nPanels * PANEL_H + (nPanels - 1) * PANEL_GAP + 14;
  const HEIGHT = BAND_Y + BAND_HEIGHT + 20;
  useEffect(() => {
    onHoverXChange?.(hoverX);
  }, [hoverX, onHoverXChange]);

  const bandSegments = useMemo(() => {
    const out: { zone: ZoneName | null; x0: number; x1: number; interval: number }[] = [];
    let prevZone: ZoneName | null = null;
    let segStart = 0;
    withDistance.forEach((s, i) => {
      const zone = zoneForBpm(s.hr, hrBoundsBpm);
      const d = s.distance_cum as number;
      if (zone !== prevZone) {
        if (prevZone != null) out.push({ zone: prevZone, x0: segStart, x1: d, interval: s.interval_index ?? 0 });
        segStart = d;
        prevZone = zone;
      }
      if (i === withDistance.length - 1 && prevZone != null) out.push({ zone: prevZone, x0: segStart, x1: d, interval: s.interval_index ?? 0 });
    });
    return out;
  }, [withDistance, hrBoundsBpm]);

  const lo = Math.max(lowerBound(dists, domain.min) - 1, 0);
  const hi = Math.min(lowerBound(dists, domain.max + 1e-6) + 1, withDistance.length);

  const panels = useMemo(() => {
    const span = Math.max(domain.max - domain.min, 1);
    const xs: number[] = [];
    for (let i = lo; i < hi; i++) xs.push(PAD_LEFT + ((dists[i] - domain.min) / span) * plotWidthPx);
    return panelDefs.map((panel, pi) => {
      const vals: (number | null)[] = [];
      for (let i = lo; i < hi; i++) vals.push(withDistance[i][panel.key] ?? null);
      const inView = vals.filter((v, k): v is number => v != null && dists[lo + k] >= domain.min && dists[lo + k] <= domain.max);
      const [vmin, vmax] = extent(inView);
      const t = panel.key === "pace_500m" ? secondsTicks(vmin, vmax, 2) : niceTicks(vmin, vmax, 2);
      const top = TOP + pi * (PANEL_H + PANEL_GAP);
      const range = t.max - t.min || 1;
      const y = (v: number) => (panel.inverted ? top + ((v - t.min) / range) * PANEL_H : top + PANEL_H - ((v - t.min) / range) * PANEL_H);
      const ys = vals.map((v) => (v == null ? null : y(v)));
      return { ...panel, top, y, ticks: t.ticks, path: inView.length ? buildLine(xs, ys, false) : null, hasData: inView.length > 0 };
    });
  }, [withDistance, dists, lo, hi, domain.min, domain.max, plotWidthPx, panelDefs]);

  if (withDistance.length < 2) {
    return <EmptyState message="Not enough per-stroke data to chart (Garmin-only erg sessions have no stroke-level data)." />;
  }

  const width = plotWidthPx + PAD_LEFT + PAD_RIGHT;
  const x = (d: number) => PAD_LEFT + ((d - domain.min) / Math.max(domain.max - domain.min, 1)) * plotWidthPx;
  const shownHoverX = hoverX ?? externalHoverX ?? null;
  const hovered = shownHoverX != null ? withDistance[nearestIndex(dists, shownHoverX)] ?? null : null;
  const intervalBounds = (idx: number): { min: number; max: number } => {
    let min = Infinity;
    let max = -Infinity;
    for (const s of withDistance) {
      if ((s.interval_index ?? 0) !== idx) continue;
      const d = s.distance_cum as number;
      if (d < min) min = d;
      if (d > max) max = d;
    }
    return { min, max };
  };
  const fmtTick = (key: PanelKey, v: number) => (key === "pace_500m" ? formatSplit(v) : `${Math.round(v)}`);

  return (
    <div ref={containerRef} className="relative">
      <div
        className="touch-none select-none outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        // See TrendLineChart's identical note: handlers + touch-action live on this HTML div,
        // not the <svg> — WebKit's touch-action support on SVG root elements has real gaps
        // that only surfaced testing on a real iPhone, not Chromium's CDP touch emulation.
        data-chart-surface="true"
        role="img"
        aria-label={`Split, watts${nPanels > 3 ? ", heart rate" : ""} and stroke rate over distance. Focus and press +/- to zoom, arrow keys to pan, Escape to reset.`}
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
        <defs>
          <clipPath id={clipId}>
            <rect x={PAD_LEFT} y={0} width={plotWidthPx} height={HEIGHT} />
          </clipPath>
        </defs>
        {hoveredInterval != null &&
          (() => {
            const { min, max } = intervalBounds(hoveredInterval);
            if (!Number.isFinite(min)) return null;
            return <rect x={x(min)} width={Math.max(x(max) - x(min), 1)} y={TOP - 8} height={BAND_Y + BAND_HEIGHT - TOP + 8} fill="var(--accent)" opacity={0.08} />;
          })()}

        {panels.map((p) => (
          <g key={p.key}>
            <text x={PAD_LEFT} y={p.top - 8} fontSize={10} fontWeight={600} fill="var(--text-secondary)">
              {p.label} <tspan fill="var(--text-tertiary)" fontWeight={400}>{p.unit}{p.inverted ? " · faster is higher" : ""}</tspan>
            </text>
            {p.ticks.map((t, i) => (
              <g key={i}>
                <line x1={PAD_LEFT} x2={PAD_LEFT + plotWidthPx} y1={p.y(t)} y2={p.y(t)} stroke="var(--border)" strokeDasharray="2 4" opacity={0.8} />
                <text x={PAD_LEFT - 6} y={p.y(t) + 3} fontSize={10} fill="var(--text-tertiary)" textAnchor="end" className="font-mono-nums">
                  {fmtTick(p.key, t)}
                </text>
              </g>
            ))}
            <g clipPath={`url(#${clipId})`}>
              {p.path &&
                (reduced || hasAnimatedIn.current ? (
                  // Plain <path> once the one-time draw-in has played — see TrendLineChart's
                  // identical split for why an animated path re-rendered on every pan/zoom frame
                  // is real, measured dropped-frame cost for an animation that's already done.
                  <path d={p.path} fill="none" stroke={p.color} strokeWidth={p.key === "pace_500m" ? 2 : 1.6} strokeLinecap="round" strokeLinejoin="round" />
                ) : (
                  <path
                    d={p.path}
                    fill="none"
                    stroke={p.color}
                    strokeWidth={p.key === "pace_500m" ? 2 : 1.6}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                pathLength={1}
                className="draw-in"
                  />
                ))}
              {hovered && hovered[p.key] != null && (
                <circle cx={x(hovered.distance_cum as number)} cy={p.y(hovered[p.key] as number)} r={3.5} fill={p.color} stroke="var(--surface)" strokeWidth={1.5} />
              )}
            </g>
          </g>
        ))}

        <text x={PAD_LEFT} y={BAND_Y - 4} fontSize={10} fill="var(--text-tertiary)">
          HR zone
        </text>
        {bandSegments.map((seg, i) =>
          seg.zone ? (
            <rect
              key={i}
              x={x(seg.x0)}
              width={Math.max(x(seg.x1) - x(seg.x0), 1)}
              y={BAND_Y}
              height={BAND_HEIGHT}
              rx={2}
              fill={zoneColor(seg.zone)}
              clipPath={`url(#${clipId})`}
              onPointerEnter={() => onHoverInterval?.(seg.interval)}
              style={{ cursor: "pointer" }}
            />
          ) : null,
        )}

        {[0, 0.25, 0.5, 0.75, 1].map((f, i) => (
          <text key={i} x={PAD_LEFT + f * plotWidthPx} y={HEIGHT - 4} fontSize={10} fill="var(--text-tertiary)" textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"} className="font-mono-nums">
            {formatDistance(domain.min + f * (domain.max - domain.min))}
          </text>
        ))}

        {hovered && (
          <line x1={x(hovered.distance_cum as number)} x2={x(hovered.distance_cum as number)} y1={TOP - 4} y2={BAND_Y + BAND_HEIGHT} stroke="var(--text-tertiary)" strokeWidth={1} strokeDasharray="3 3" />
        )}
      </svg>
      </div>

      {hovered && (
        <ChartTooltip
          xPct={(x(hovered.distance_cum as number) / width) * 100}
          title={hovered.t_cum != null ? `${formatDistance(hovered.distance_cum)} · ${formatDuration(hovered.t_cum)}` : formatDistance(hovered.distance_cum)}
          rows={[
            ...(hovered.pace_500m != null ? [{ label: "Split", value: `${formatSplit(hovered.pace_500m)}/500m`, color: METRIC_COLOR.pace }] : []),
            ...(hovered.watts != null ? [{ label: "Power", value: `${hovered.watts.toFixed(0)} W`, color: METRIC_COLOR.power }] : []),
            ...(hovered.stroke_rate != null ? [{ label: "Rate", value: `${hovered.stroke_rate.toFixed(0)} spm`, color: METRIC_COLOR.rate }] : []),
            ...(hovered.hr != null ? [{ label: "HR", value: `${hovered.hr} bpm`, color: METRIC_COLOR.hr }] : []),
          ]}
        />
      )}

      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <Legend items={panelDefs.map((p) => ({ label: p.label, color: p.color }))} />
        <span className="text-xs text-text-tertiary">Strip beneath = heart-rate zone</span>
      </div>
    </div>
  );
}
