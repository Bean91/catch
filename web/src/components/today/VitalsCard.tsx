import * as Dialog from "@radix-ui/react-dialog";
import { lazy, Suspense, useState } from "react";
import type { TrendMetric, VitalTrend } from "../../lib/types";
import { Card } from "../ui/Card";
import { Sparkline } from "./Sparkline";
import { trendMetricColor } from "../../lib/metricColors";
import { ModalContent } from "../ui/Sheet";

const ExpandedTrendChart = lazy(() => import("./ExpandedTrendChart"));

export function VitalsCard({
  title,
  unit,
  decimals = 0,
  trend,
  metric,
}: {
  title: string;
  unit: string;
  decimals?: number;
  trend: VitalTrend;
  metric: TrendMetric;
}) {
  const [open, setOpen] = useState(false);
  const formatValue = (v: number) => `${v.toFixed(decimals)}${unit}`;
  const color = trendMetricColor(metric);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className="h-full w-full text-left transition-transform duration-150 active:scale-[0.995]" aria-label={`${title} details`}>
          <Card className="h-full hover:border-accent/40" title={title} action={<span aria-hidden className="h-2 w-2 rounded-full" style={{ background: color, boxShadow: `0 0 0 4px color-mix(in oklab, ${color} 20%, transparent)` }} />}>
            <div className="flex items-baseline gap-1">
              <span className="font-mono-nums text-[2rem] font-semibold leading-none tracking-tight text-text-primary">
                {trend.today != null ? trend.today.toFixed(decimals) : "—"}
              </span>
              <span className="text-sm text-text-tertiary">{unit}</span>
            </div>
            {trend.baseline_band && (
              <p className="mt-1.5 text-xs text-text-tertiary font-mono-nums">
                baseline {trend.baseline_band.baseline.toFixed(decimals)} ({trend.baseline_band.low.toFixed(decimals)}–
                {trend.baseline_band.high.toFixed(decimals)})
              </p>
            )}
            <div className="mt-3">
              <Sparkline points={trend.sparkline_14d} baselineBand={trend.baseline_band} color={color} label={`${title}, last 14 days`} format={formatValue} />
            </div>
          </Card>
        </button>
      </Dialog.Trigger>
      <ModalContent width="xl">
          <div className="mb-3 flex items-center justify-between">
            <Dialog.Title className="text-sm font-medium text-text-secondary">{title}</Dialog.Title>
            <Dialog.Close
              aria-label="Close"
              className="flex items-center justify-center rounded-md text-text-tertiary hover:text-text-secondary"
              style={{ width: "var(--touch-target)", height: "var(--touch-target)" }}
            >
              ✕
            </Dialog.Close>
          </div>
          {open && (
            <Suspense fallback={<div className="h-56 animate-pulse rounded-md bg-surface-2" aria-hidden />}>
              <ExpandedTrendChart metric={metric} formatValue={formatValue} />
            </Suspense>
          )}
        </ModalContent>
    </Dialog.Root>
  );
}
