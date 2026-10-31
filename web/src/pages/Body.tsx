import { useQuery } from "@tanstack/react-query";
import { fetchBody, fetchTrends } from "../lib/api";
import { formatNumber } from "../lib/format";
import { TrendLineChart } from "../components/charts/TrendLineChart";
import { Sparkline } from "../components/today/Sparkline";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";

export function BodyPage() {
  const weightQuery = useQuery({ queryKey: ["trends", "weight"], queryFn: () => fetchTrends("weight") });
  const wPerKgQuery = useQuery({ queryKey: ["trends", "w_per_kg"], queryFn: () => fetchTrends("w_per_kg") });
  const bodyQuery = useQuery({ queryKey: ["body"], queryFn: () => fetchBody() });

  const readings = bodyQuery.data ?? [];
  const latest = readings[readings.length - 1];
  const fatSpark = readings.map((r) => ({ date: r.ts.slice(0, 10), value: r.fat_pct }));
  const muscleSpark = readings.map((r) => ({ date: r.ts.slice(0, 10), value: r.muscle_kg }));

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <h1 className="text-lg font-semibold text-text-primary">Body</h1>

      <Card title="Weight">
        {weightQuery.isLoading ? (
          <div className="h-40 animate-pulse rounded-md bg-surface-2" aria-hidden />
        ) : weightQuery.data && weightQuery.data.length > 0 ? (
          <>
            <TrendLineChart
              points={weightQuery.data}
              secondary={weightQuery.data.map((p) => ({ date: p.date, value: p.smoothed ?? null }))}
              formatValue={(v) => `${v.toFixed(1)}kg`}
            />
            <p className="mt-2 text-xs text-text-tertiary">
              Solid = raw readings. Dashed = 7-day smoothed (a single-day outlier doesn't move it).
            </p>
          </>
        ) : (
          <EmptyState message="No weight data synced yet (needs Withings OAuth)." />
        )}
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="Body fat %">
          {latest?.fat_pct != null ? (
            <>
              <div className="font-mono-nums text-3xl font-semibold text-text-primary">{formatNumber(latest.fat_pct, 1)}%</div>
              <div className="mt-3">
                <Sparkline points={fatSpark} baselineBand={null} />
              </div>
            </>
          ) : (
            <EmptyState message="No body-fat data yet." />
          )}
        </Card>
        <Card title="Muscle mass">
          {latest?.muscle_kg != null ? (
            <>
              <div className="font-mono-nums text-3xl font-semibold text-text-primary">{formatNumber(latest.muscle_kg, 1)}kg</div>
              <div className="mt-3">
                <Sparkline points={muscleSpark} baselineBand={null} />
              </div>
            </>
          ) : (
            <EmptyState message="No muscle-mass data yet." />
          )}
        </Card>
      </div>

      <Card title="W/kg over time">
        {wPerKgQuery.isLoading ? (
          <div className="h-40 animate-pulse rounded-md bg-surface-2" aria-hidden />
        ) : wPerKgQuery.data && wPerKgQuery.data.length > 0 ? (
          <TrendLineChart points={wPerKgQuery.data} formatValue={(v) => v.toFixed(2)} />
        ) : (
          <EmptyState message="No erg power + weight pairing yet." />
        )}
      </Card>
    </div>
  );
}
