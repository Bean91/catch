import type { VitalTrend } from "../../lib/types";
import { Card } from "../ui/Card";
import { Sparkline } from "./Sparkline";

export function VitalsCard({
  title,
  unit,
  decimals = 0,
  trend,
}: {
  title: string;
  unit: string;
  decimals?: number;
  trend: VitalTrend;
}) {
  return (
    <Card title={title}>
      <div className="flex items-baseline gap-1">
        <span className="font-mono-nums text-3xl font-semibold text-text-primary">
          {trend.today != null ? trend.today.toFixed(decimals) : "—"}
        </span>
        <span className="text-sm text-text-tertiary">{unit}</span>
      </div>
      {trend.baseline_band && (
        <p className="mt-1 text-xs text-text-tertiary font-mono-nums">
          baseline {trend.baseline_band.baseline.toFixed(decimals)} ({trend.baseline_band.low.toFixed(decimals)}–
          {trend.baseline_band.high.toFixed(decimals)})
        </p>
      )}
      <div className="mt-3">
        <Sparkline points={trend.sparkline_14d} baselineBand={trend.baseline_band} />
      </div>
    </Card>
  );
}
