import { useQuery } from "@tanstack/react-query";
import { fetchSeries, fetchTests } from "../../lib/api";
import { addDays, todayISO } from "../../lib/dates";
import { formatTimeTenths } from "../../lib/format";
import { METRIC_COLOR } from "../../lib/metricColors";
import { MiniLineChart } from "../charts/MiniLineChart";
import { Card } from "../ui/Card";
import { ErrorState } from "../ui/EmptyState";
import { Skeleton } from "../ui/Skeleton";

/**
 * A year of progression: the 2k each hard effort implies (an estimate, drawn as a line) with confirmed 2k tests as rings over it
 * (the measured results — actual against predicted), and weight-adjusted power on its own chart (its own axis and unit).
 */
export function ProgressionCard() {
  const to = todayISO();
  const from = addDays(to, -365);
  const series = useQuery({ queryKey: ["series", "predicted_2k,weight_adjusted_watts", from, to, 120], queryFn: () => fetchSeries(["predicted_2k", "weight_adjusted_watts"], from, to, 120) });
  const tests = useQuery({ queryKey: ["tests", "2000m"], queryFn: () => fetchTests("2000m") });
  const implied = (series.data?.series.predicted_2k?.points ?? []).map((p) => ({ date: p.date, value: p.value }));
  const wap = (series.data?.series.weight_adjusted_watts?.points ?? []).map((p) => ({ date: p.date, value: p.value }));
  const measured = (tests.data ?? []).filter((t) => t.kind === "test" && t.date && t.duration_s != null && t.date >= from).map((t) => ({ date: t.date as string, value: t.duration_s }));

  return (
    <Card material="solid" title="Progression" eyebrow="Last 12 months">
      {series.isLoading ? (
        <Skeleton className="h-[180px] w-full" />
      ) : series.isError ? (
        <ErrorState message="Couldn't load your progression." onRetry={() => series.refetch()} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <p className="mb-1 text-xs font-medium text-text-secondary">2k implied by each hard effort {measured.length > 0 && <span className="text-text-tertiary">· rings are measured 2k tests</span>}</p>
            <MiniLineChart points={implied} markers={measured} markerLabel="Measured 2k" color={METRIC_COLOR.pace} format={formatTimeTenths} axis="seconds" invert label="Implied 2k" />
          </div>
          <div>
            <p className="mb-1 text-xs font-medium text-text-secondary">Weight-adjusted power (W/kg²ᐟ³)</p>
            <MiniLineChart points={wap} color={METRIC_COLOR.power} format={(v) => v.toFixed(1)} label="Weight-adjusted power" />
          </div>
        </div>
      )}
    </Card>
  );
}
