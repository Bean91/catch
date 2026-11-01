import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ChartNavigator } from "../components/charts/ChartNavigator";
import { TrendLineChart } from "../components/charts/TrendLineChart";
import { WeeklyVolumeBars } from "../components/charts/WeeklyVolumeBars";
import { PbTable } from "../components/workouts/PbTable";
import { Card } from "../components/ui/Card";
import { eventsToMarkers } from "../lib/chartAnnotations";
import { RANGE_PRESETS, parseChartUrlState, presetToDomain, writeChartUrlState, type RangePreset } from "../lib/chartRange";
import { fetchMemory, fetchPbs, fetchSeries, fetchVolume } from "../lib/api";
import { formatTimeTenths } from "../lib/format";
import type { TrendMetric } from "../lib/types";
import type { Domain } from "../lib/useChartInteraction";

const METRICS: { value: TrendMetric; label: string; format: (v: number) => string }[] = [
  { value: "recovery", label: "Recovery", format: (v) => `${v.toFixed(0)}%` },
  { value: "hrv_rmssd", label: "HRV", format: (v) => `${v.toFixed(0)}ms` },
  { value: "resting_hr", label: "Resting HR", format: (v) => `${v.toFixed(0)}bpm` },
  { value: "sleep_score", label: "Sleep", format: (v) => v.toFixed(0) },
  { value: "strain", label: "Strain", format: (v) => v.toFixed(1) },
  { value: "load_acr", label: "Load / form", format: (v) => v.toFixed(2) },
  { value: "weight", label: "Weight", format: (v) => `${v.toFixed(1)}kg` },
  { value: "w_per_kg", label: "W/kg", format: (v) => v.toFixed(2) },
  { value: "predicted_2k", label: "Predicted 2k", format: (v) => formatTimeTenths(v) },
];

const DAY_MS = 86_400_000;

function quantizePoints(plotWidthPx: number): number {
  // 2x the chart's pixel width (task spec's default), rounded to a step so a few px of
  // ResizeObserver jitter doesn't spawn a new TanStack Query cache entry every time.
  return Math.min(2000, Math.max(200, Math.ceil((plotWidthPx * 2) / 100) * 100));
}

function padDomain(domain: Domain, full: Domain): { from: string; to: string } {
  // Fetches the visible range plus one screen of padding on each side (task spec's DATA #3)
  // so a small pan has data to show immediately instead of a loading edge.
  const span = domain.max - domain.min;
  const min = Math.max(full.min, domain.min - span);
  const max = Math.min(full.max, domain.max + span);
  return { from: new Date(min).toISOString().slice(0, 10), to: new Date(max).toISOString().slice(0, 10) };
}

const TAPPABLE_WORKOUT_METRICS = new Set<TrendMetric>(["w_per_kg", "predicted_2k"]);

export function TrendsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const metric = (params.get("metric") as TrendMetric | null) ?? "recovery";
  const activeMetric = METRICS.find((m) => m.value === metric) ?? METRICS[0];
  const now = useMemo(() => new Date(), []);

  // The metric's own full history, fetched once (cheap and cached server-side by metric) to
  // learn (a) the real earliest-data bound for "all"/zoom-out clamping and (b) a thin backdrop
  // sparkline for the navigator — not re-fetched on every pan/zoom.
  const allQuery = useQuery({
    queryKey: ["series-all", metric],
    queryFn: () => fetchSeries([metric], "1900-01-01", now.toISOString().slice(0, 10), 600),
  });
  const allPoints = allQuery.data?.series[metric]?.points ?? [];
  const earliestMs = allPoints.length ? new Date(allPoints[0].date + "T00:00:00").getTime() : now.getTime() - 84 * DAY_MS;

  const urlState = parseChartUrlState(params);
  const defaultDomain = useMemo(() => presetToDomain("12w", now, new Date(earliestMs)), [now, earliestMs]);
  const initialDomain: Domain =
    urlState.from && urlState.to
      ? { min: new Date(urlState.from + "T00:00:00").getTime(), max: new Date(urlState.to + "T00:00:00").getTime() }
      : urlState.preset
        ? presetToDomain(urlState.preset, now, new Date(earliestMs))
        : defaultDomain;

  // `domain` updates on every pan/zoom frame (drives the chart's live x-scale). `queryDomain`
  // only updates once a gesture settles — the series query keys off *that*, not `domain`,
  // or every pointermove would spawn a new TanStack Query cache entry/network round-trip.
  // Caught by a CPU-throttled pan perf test (p95 frame time spiked to 175ms before this fix,
  // from mid-gesture fetches; ~10ms after) — see PLAN.md's session 8 notes.
  const [domain, setDomain] = useState<Domain>(initialDomain);
  const [queryDomain, setQueryDomain] = useState<Domain>(initialDomain);
  const [plotWidthPx] = useState(600); // refined per-chart via ResizeObserver inside each chart; this seeds the initial fetch budget

  // Memoized so its object identity is stable across re-renders (it only ever depends on
  // earliestMs/now/queryDomain.min, not the live pan/zoom `domain`) — every chart below
  // threads this through useChartInteraction's dependency arrays, and a fresh object every
  // frame defeated their memoization (dropped frames in a CPU-throttled pan test).
  //
  // The `queryDomain.min` term matters on a metric switch: while the new metric's `allQuery`
  // is loading, `earliestMs` briefly falls back to "now - 84d", which can be *more recent*
  // than wherever the user had already panned to. Without this term, `fullDomain` would
  // briefly shrink past the user's current `domain`, and useChartInteraction's own
  // out-of-bounds correction effect would silently snap the view back to a ~12-week default —
  // a real, confirmed bug (switching metric while on a custom range produced a chart with the
  // x-scale and the actual fetched points pointing at two different windows, rendering a path
  // with coordinates thousands of pixels outside the viewBox). Using `queryDomain.min` (settled,
  // not live) rather than `domain.min` keeps this from recomputing every pan frame.
  const fullDomain: Domain = useMemo(
    () => ({ min: Math.min(earliestMs, now.getTime() - 7 * DAY_MS, queryDomain.min), max: now.getTime() }),
    [earliestMs, now, queryDomain.min],
  );

  // `initialDomain` above is computed from `earliestMs`, which falls back to "now - 84d" until
  // `allQuery` resolves with the metric's *real* earliest date — so a cold load of `?range=all`
  // (or `1y`/`6m`, anything wider than that 84-day fallback) would otherwise permanently stick
  // at the fallback span, since `useState`'s initializer only runs once. This effect re-derives
  // the domain from the URL's preset whenever the real `earliestMs` becomes known (on mount,
  // and again on a metric switch) — but only while still in preset mode (`urlState.preset` set,
  // i.e. the user hasn't panned/zoomed into a custom range since), so it never fights an
  // explicit user action. A real bug caught only by reading the chart's own aria-label after a
  // cold `?range=all` load, not by trusting the preset button's visual selected state.
  const lastAppliedEarliestMs = useRef<number | null>(null);
  useEffect(() => {
    if (lastAppliedEarliestMs.current === earliestMs) return;
    lastAppliedEarliestMs.current = earliestMs;
    if (!urlState.preset) return;
    const next = presetToDomain(urlState.preset, now, new Date(earliestMs));
    setDomain(next);
    setQueryDomain(next);
    // urlState/now are derived fresh every render and would make this effect fire every
    // render if included — only a real earliestMs change should re-trigger it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [earliestMs]);

  const commitToUrl = useCallback(
    (next: Domain, preset: RangePreset | null) => {
      setParams(
        (prev) =>
          writeChartUrlState(
            prev,
            preset ? { preset, from: null, to: null } : { preset: null, from: new Date(next.min).toISOString().slice(0, 10), to: new Date(next.max).toISOString().slice(0, 10) },
          ),
        { replace: true },
      );
    },
    [setParams],
  );

  const onDomainSettled = useCallback(
    (next: Domain) => {
      setQueryDomain(next);
      commitToUrl(next, null);
    },
    [commitToUrl],
  );

  const setMetric = useCallback(
    (value: TrendMetric) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("metric", value);
        return next;
      });
    },
    [setParams],
  );

  // The URL's own preset clears to null the moment the user pans/zooms off it (a custom
  // from/to takes over) — so using `urlState.preset ?? "12w"` for double-tap/Esc/the navigator
  // reset would always snap back to 12w after any pan, not "whatever preset was active before
  // that pan." This tracks the last *explicitly chosen* preset separately so reset means what
  // interaction spec #5 asks for.
  const [lastPreset, setLastPreset] = useState<RangePreset>(urlState.preset ?? "12w");

  const selectPreset = useCallback(
    (preset: RangePreset) => {
      const next = presetToDomain(preset, now, new Date(earliestMs));
      setDomain(next);
      setQueryDomain(next);
      setLastPreset(preset);
      commitToUrl(next, preset);
    },
    [now, earliestMs, commitToUrl],
  );

  const resetDomain = useCallback(() => selectPreset(lastPreset), [selectPreset, lastPreset]);

  const padded = padDomain(queryDomain, fullDomain);
  const points = quantizePoints(plotWidthPx);
  const seriesQuery = useQuery({
    queryKey: ["series", metric, padded.from, padded.to, points],
    queryFn: () => fetchSeries([metric], padded.from, padded.to, points),
    placeholderData: keepPreviousData,
  });
  const volumeQuery = useQuery({ queryKey: ["trends-volume-long"], queryFn: () => fetchVolume(104) });
  const memoryQuery = useQuery({ queryKey: ["memory"], queryFn: fetchMemory });

  const activePoints = seriesQuery.data?.series[metric]?.points ?? [];
  const annotations = useMemo(() => eventsToMarkers(memoryQuery.data?.events ?? []), [memoryQuery.data]);
  // Memoized: `allPoints` only changes when the metric's own full-history query resettles,
  // not on every pan/zoom frame — recomputing this ~600-point map every frame (TrendsPage
  // re-renders on every live domain change) showed up as real dropped frames in a
  // CPU-throttled pan test before this fix.
  const navigatorBackdrop = useMemo(
    () => allPoints.map((p) => ({ x: new Date(p.date + "T00:00:00").getTime(), y: p.value })),
    [allPoints],
  );

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <h1 className="text-lg font-semibold text-text-primary">Trends</h1>

      <MetricPicker metric={metric} onSelect={setMetric} />
      <RangePicker activePreset={urlState.preset} onSelect={selectPreset} />

      <Card title={activeMetric.label}>
        {seriesQuery.isLoading && activePoints.length === 0 ? (
          <Skeleton />
        ) : (
          <TrendLineChart
            points={activePoints}
            secondaryKey={metric === "weight" ? "smoothed" : undefined}
            formatValue={activeMetric.format}
            domain={domain}
            fullDomain={fullDomain}
            minSpanMs={7 * DAY_MS}
            onDomainChange={setDomain}
            onDomainSettled={onDomainSettled}
            onResetDomain={resetDomain}
            annotations={annotations}
            onPointTap={
              TAPPABLE_WORKOUT_METRICS.has(metric)
                ? (point) => {
                    if (point.activity_id != null) navigate(`/workouts/${point.activity_id}`);
                  }
                : undefined
            }
          />
        )}
        <div className="mt-3">
          <ChartNavigator
            fullDomain={fullDomain}
            viewDomain={domain}
            minSpan={7 * DAY_MS}
            onChange={setDomain}
            onChangeSettled={onDomainSettled}
            backdrop={navigatorBackdrop}
          />
        </div>
      </Card>

      <Card title="Weekly volume by zone">
        {volumeQuery.isLoading ? (
          <Skeleton />
        ) : (
          <WeeklyVolumeBars
            weeks={volumeQuery.data ?? []}
            domain={domain}
            fullDomain={fullDomain}
            minSpan={7 * DAY_MS}
            onDomainChange={setDomain}
            onDomainSettled={onDomainSettled}
            onResetDomain={resetDomain}
          />
        )}
      </Card>

      <PersonalBestsCard />
    </div>
  );
}

function Skeleton() {
  return <div className="h-40 animate-pulse rounded-md bg-surface-2" aria-hidden />;
}

// Extracted and memoized so these don't re-render on every pan/zoom frame — TrendsPage's
// `domain` state changes on every one of those, and without this split React would reconcile
// all 16 of these buttons each time too, real measured cost in a CPU-throttled pan test
// (the task's own 390px screenshots also showed the un-wrapped range row overflowing, fixed
// here by the same `flex-wrap` the metric row already had).
const MetricPicker = memo(function MetricPicker({ metric, onSelect }: { metric: TrendMetric; onSelect: (value: TrendMetric) => void }) {
  return (
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="Metric">
      {METRICS.map((m) => (
        <button
          key={m.value}
          type="button"
          role="tab"
          aria-selected={metric === m.value}
          onClick={() => onSelect(m.value)}
          className={`min-h-11 rounded-full border px-3.5 text-sm font-medium transition-colors ${
            metric === m.value
              ? "border-accent bg-accent text-accent-contrast"
              : "border-border bg-surface text-text-secondary hover:border-accent/40"
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
});

const RangePicker = memo(function RangePicker({ activePreset, onSelect }: { activePreset: RangePreset | null; onSelect: (preset: RangePreset) => void }) {
  return (
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="Range">
      {RANGE_PRESETS.map((r) => (
        <button
          key={r.value}
          type="button"
          role="tab"
          aria-selected={activePreset === r.value}
          onClick={() => onSelect(r.value)}
          className={`min-h-11 rounded-md border px-3.5 text-sm transition-colors ${
            activePreset === r.value ? "border-accent text-accent" : "border-border text-text-tertiary hover:text-text-secondary"
          }`}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
});

const PersonalBestsCard = memo(function PersonalBestsCard() {
  const pbsQuery = useQuery({ queryKey: ["pbs"], queryFn: fetchPbs });
  return <Card title="Personal bests">{pbsQuery.isLoading ? <Skeleton /> : pbsQuery.data ? <PbTable pbs={pbsQuery.data} /> : null}</Card>;
});
