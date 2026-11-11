import { useEffect, useRef, useState } from "react";
import { formatDuration } from "../../lib/format";
import { formatMmSs, formatPace } from "../../lib/gpsFormat";
import type { PaceUnit, TrackPoint } from "../../lib/types";

export type TrackMetric = "pace" | "speed" | "elevation";

const HEIGHT = 220;
const PAD_X = 44;
const PAD_RIGHT = 12;
const PAD_TOP = 10;
const PAD_BOTTOM = 24;

function value(p: TrackPoint, metric: TrackMetric): number | null {
  if (metric === "pace") return p.pace;
  if (metric === "speed") return p.speed_mps * 3.6;
  return p.elevation_m;
}

function percentile(sorted: number[], q: number): number {
  return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * q)))];
}

function fmtTick(metric: TrackMetric, unit: PaceUnit, v: number): string {
  if (metric === "pace") return unit === "km_per_h" ? v.toFixed(0) : formatMmSs(v);
  if (metric === "speed") return v.toFixed(1);
  return `${Math.round(v)}`;
}

export function trackMetricUnit(metric: TrackMetric, unit: PaceUnit): string {
  if (metric === "pace") return unit === "s_per_500m" ? "/500m" : unit === "s_per_km" ? "/km" : "km/h";
  return metric === "speed" ? "km/h" : "m";
}

/** A read-only chart of one GPS-derived series against elapsed time or distance. Hover (mouse) or
 * a horizontal drag (touch) moves a crosshair and reports the elapsed second so the map can show
 * the same instant. The surface is `touch-action: pan-y` — unlike the pan/zoom charts it must
 * never trap a vertical swipe, since there is nothing to pan. */
export function TrackChart({
  points,
  metric,
  xAxis,
  paceUnit,
  onHoverElapsed,
}: {
  points: TrackPoint[];
  metric: TrackMetric;
  xAxis: "time" | "distance";
  paceUnit: PaceUnit;
  onHoverElapsed?: (elapsedS: number | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const xs = points.map((p) => (xAxis === "time" ? p.elapsed_s : p.distance_m));
  const xMin = xs[0] ?? 0;
  const xMax = Math.max(xs[xs.length - 1] ?? 1, xMin + 1);
  const ys = points.map((p) => value(p, metric));
  const defined = ys.filter((v): v is number => v != null && Number.isFinite(v)).sort((a, b) => a - b);

  if (defined.length < 2) {
    const why = metric === "elevation" ? "This device recorded no elevation." : "Not enough data to chart.";
    return <div className="flex h-32 items-center justify-center text-sm text-text-tertiary">{why}</div>;
  }

  // 2nd-98th percentile with a margin: one noisy fix must not flatten the whole line.
  const lo0 = percentile(defined, 0.02);
  const hi0 = percentile(defined, 0.98);
  const margin = (hi0 - lo0 || 1) * 0.1;
  const yLo = lo0 - margin;
  const yHi = hi0 + margin;
  // Pace is "lower is faster": plotted inverted so a faster stretch rises, like speed does.
  const invert = metric === "pace" && paceUnit !== "km_per_h";

  const plotW = Math.max(width - PAD_X - PAD_RIGHT, 50);
  const plotH = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const x = (v: number) => PAD_X + ((v - xMin) / (xMax - xMin)) * plotW;
  const y = (v: number) => {
    const f = (Math.min(Math.max(v, yLo), yHi) - yLo) / (yHi - yLo);
    return PAD_TOP + (invert ? f : 1 - f) * plotH;
  };

  // Break the line at missing values and at segment changes (a GPS gap is never bridged).
  let path = "";
  let pen = false;
  points.forEach((p, i) => {
    const v = ys[i];
    const prev = points[i - 1];
    if (v == null || !Number.isFinite(v) || (prev && prev.segment !== p.segment)) pen = false;
    if (v == null || !Number.isFinite(v)) return;
    path += `${pen ? "L" : "M"}${x(xs[i]).toFixed(1)},${y(v).toFixed(1)} `;
    pen = true;
  });

  const setFromClient = (clientX: number) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const target = xMin + ((clientX - rect.left - PAD_X) / plotW) * (xMax - xMin);
    let best = 0;
    for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - target) < Math.abs(xs[best] - target)) best = i;
    setHoverIdx(best);
    onHoverElapsed?.(points[best].elapsed_s);
  };
  const clear = () => {
    setHoverIdx(null);
    onHoverElapsed?.(null);
  };

  const hp = hoverIdx != null ? points[hoverIdx] : null;
  const hv = hp ? value(hp, metric) : null;
  const unitLabel = trackMetricUnit(metric, paceUnit);

  return (
    <div ref={ref} className="relative">
      <div
        data-testid="track-chart-surface"
        role="img"
        aria-label={`${metric === "pace" ? "Pace" : metric === "speed" ? "Speed" : "Elevation"} (${unitLabel}) over ${xAxis === "time" ? "elapsed time" : "distance"}, from GPS`}
        className="select-none"
        style={{ touchAction: "pan-y" }}
        onPointerMove={(e) => setFromClient(e.clientX)}
        onPointerDown={(e) => setFromClient(e.clientX)}
        onPointerLeave={clear}
        onPointerCancel={clear}
      >
        <svg width="100%" height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`} aria-hidden="true" className="pointer-events-none block">
          {[yLo + margin, (yLo + yHi) / 2, yHi - margin].map((v, i) => (
            <g key={i}>
              <line x1={PAD_X} x2={PAD_X + plotW} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth={1} />
              <text x={2} y={y(v) - 3} fontSize={10} fill="var(--text-tertiary)" className="font-mono-nums">
                {fmtTick(metric, paceUnit, v)}
              </text>
            </g>
          ))}
          <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          {hp && hv != null && (
            <g>
              <line x1={x(xs[hoverIdx!])} x2={x(xs[hoverIdx!])} y1={PAD_TOP} y2={PAD_TOP + plotH} stroke="var(--text-secondary)" strokeWidth={1} />
              <circle cx={x(xs[hoverIdx!])} cy={y(hv)} r={4} fill="var(--accent)" />
            </g>
          )}
          {Array.from({ length: 5 }, (_, i) => xMin + ((xMax - xMin) * i) / 4).map((v, i) => (
            <text key={i} x={x(v)} y={HEIGHT - 6} fontSize={10} fill="var(--text-tertiary)" textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"}>
              {xAxis === "time" ? formatDuration(v) : `${(v / 1000).toFixed(1)} km`}
            </text>
          ))}
        </svg>
      </div>
      {hp && (
        <div
          data-testid="track-chart-tooltip"
          className="pointer-events-none absolute top-1 rounded-md border border-border bg-surface px-2 py-1 text-xs shadow-sm"
          style={{ left: `clamp(4px, ${(x(xs[hoverIdx!]) / width) * 100}%, calc(100% - 110px))` }}
        >
          <div className="text-text-tertiary">
            {formatDuration(hp.elapsed_s)} · {(hp.distance_m / 1000).toFixed(2)} km
          </div>
          <div className="font-mono-nums text-text-primary">
            {hv == null ? "—" : metric === "pace" ? formatPace(paceUnit, hv) : `${hv.toFixed(metric === "speed" ? 1 : 0)} ${unitLabel}`}
          </div>
        </div>
      )}
    </div>
  );
}
