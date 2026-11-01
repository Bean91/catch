import * as Dialog from "@radix-ui/react-dialog";
import { lazy, Suspense, useState } from "react";
import type { TrendMetric, VitalTrend } from "../../lib/types";
import { Card } from "../ui/Card";
import { Sparkline } from "./Sparkline";

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

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className="w-full text-left" aria-label={`${title} details`}>
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
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 w-[min(94vw,640px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-5 shadow-xl focus:outline-none">
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
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
