import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchPbs, fetchTrends, fetchVolume } from "../lib/api";
import { rangeToFromTo, rangeToWeeks, type TrendRange } from "../lib/dateRanges";
import { formatTimeTenths } from "../lib/format";
import type { TrendMetric } from "../lib/types";
import { TrendLineChart } from "../components/charts/TrendLineChart";
import { WeeklyVolumeBars } from "../components/charts/WeeklyVolumeBars";
import { PbTable } from "../components/workouts/PbTable";
import { Card } from "../components/ui/Card";

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

const RANGES: { value: TrendRange; label: string }[] = [
  { value: "4w", label: "4w" },
  { value: "12w", label: "12w" },
  { value: "season", label: "Season" },
  { value: "all", label: "All" },
];

export function TrendsPage() {
  const [metric, setMetric] = useState<TrendMetric>("recovery");
  const [range, setRange] = useState<TrendRange>("12w");
  const { from, to } = rangeToFromTo(range);
  const activeMetric = METRICS.find((m) => m.value === metric)!;

  const trendQuery = useQuery({
    queryKey: ["trends", metric, range],
    queryFn: () => fetchTrends(metric, from, to),
  });
  const volumeQuery = useQuery({
    queryKey: ["trends-volume", range],
    queryFn: () => fetchVolume(rangeToWeeks(range)),
  });
  const pbsQuery = useQuery({ queryKey: ["pbs"], queryFn: fetchPbs });

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <h1 className="text-lg font-semibold text-text-primary">Trends</h1>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Metric">
        {METRICS.map((m) => (
          <button
            key={m.value}
            type="button"
            role="tab"
            aria-selected={metric === m.value}
            onClick={() => setMetric(m.value)}
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

      <div className="flex gap-2" role="tablist" aria-label="Range">
        {RANGES.map((r) => (
          <button
            key={r.value}
            type="button"
            role="tab"
            aria-selected={range === r.value}
            onClick={() => setRange(r.value)}
            className={`min-h-11 rounded-md border px-3.5 text-sm transition-colors ${
              range === r.value ? "border-accent text-accent" : "border-border text-text-tertiary hover:text-text-secondary"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>

      <Card title={activeMetric.label}>
        {trendQuery.isLoading ? (
          <Skeleton />
        ) : (
          <TrendLineChart points={trendQuery.data ?? []} formatValue={activeMetric.format} />
        )}
      </Card>

      <Card title="Weekly volume by zone">
        {volumeQuery.isLoading ? <Skeleton /> : <WeeklyVolumeBars weeks={volumeQuery.data ?? []} />}
      </Card>

      <Card title="Personal bests">
        {pbsQuery.isLoading ? <Skeleton /> : pbsQuery.data ? <PbTable pbs={pbsQuery.data} /> : null}
      </Card>
    </div>
  );
}

function Skeleton() {
  return <div className="h-40 animate-pulse rounded-md bg-surface-2" aria-hidden />;
}
