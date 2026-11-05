import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "framer-motion";
import { useState } from "react";
import type { Strain } from "../../lib/types";
import { bandLabel } from "../../lib/format";
import { useReducedMotion } from "../../lib/useReducedMotion";
import { BandBadge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { CountUp } from "../ui/CountUp";
import { EmptyState } from "../ui/EmptyState";

const MAX = 21;

function isSessionComponent(c: Record<string, unknown>): boolean {
  return "canonical_id" in c;
}

export function StrainGauge({
  strain,
  targetRange,
  dailyActivity,
}: {
  strain: Strain | null;
  targetRange: [number, number];
  dailyActivity?: { steps: number | null; active_kcal: number | null } | null;
}) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  const value = strain?.value ?? 0;
  const hasValue = strain != null && strain.value != null;
  const pct = (value / MAX) * 100;
  const [lo, hi] = targetRange;
  const sessionComponents = (strain?.components ?? []).filter(isSessionComponent);
  const dailyActivityComponent = strain?.daily_activity as
    | { value: number; steps: number | null; active_kcal: number | null }
    | undefined;
  // Session 14 (see PLAN.md Part C.4): the gauge fill splits into cardio/muscular/daily
  // segments — three opacities of the one accent, not a second hue, per DESIGN.md's "no
  // other component introduces a new hue" rule; always paired with the legend text below.
  const cardioValue = strain?.cardio?.value ?? 0;
  const muscularValue = strain?.muscular?.value ?? 0;
  const dailyValue = dailyActivityComponent?.value ?? 0;
  const hasSplit = hasValue && (cardioValue > 0 || muscularValue > 0 || dailyValue > 0);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className="w-full text-left" aria-label="Strain breakdown">
          <Card title="Strain today" action={strain && <BandBadge band={strain.band} label={bandLabel(strain.band)} />}>
            <div className="flex items-baseline gap-2">
              {hasValue ? (
                <CountUp value={value} decimals={1} className="text-3xl font-semibold text-text-primary" />
              ) : (
                <span className="font-mono-nums text-3xl font-semibold text-text-tertiary">—</span>
              )}
              <span className="text-sm text-text-tertiary font-mono-nums">/ {MAX}</span>
            </div>
            <div className="relative mt-4 h-3 w-full">
              <div className="absolute inset-0 overflow-hidden rounded-full bg-surface-2">
                {hasSplit ? (
                  <motion.div
                    className="absolute inset-y-0 left-0 flex overflow-hidden rounded-full"
                    initial={{ width: reduced ? `${pct}%` : "0%" }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: reduced ? 0 : 1, ease: [0.16, 1, 0.3, 1] }}
                  >
                    <div className="h-full bg-accent" style={{ width: `${(cardioValue / Math.max(value, 0.01)) * 100}%` }} />
                    <div className="h-full bg-accent/60" style={{ width: `${(muscularValue / Math.max(value, 0.01)) * 100}%` }} />
                    <div className="h-full bg-accent/30" style={{ width: `${(dailyValue / Math.max(value, 0.01)) * 100}%` }} />
                  </motion.div>
                ) : (
                  <motion.div
                    className="absolute inset-y-0 left-0 rounded-full bg-accent"
                    initial={{ width: reduced ? `${pct}%` : "0%" }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: reduced ? 0 : 1, ease: [0.16, 1, 0.3, 1] }}
                  />
                )}
              </div>
              {/* Target-range boundary ticks sit above the fill (not a translucent band under
                  it) so they stay visible even once the fill passes through or past the
                  target range. */}
              <div
                className="absolute -top-1 -bottom-1 w-0.5 rounded-full bg-text-primary/70"
                style={{ left: `${(lo / MAX) * 100}%` }}
                aria-hidden
              />
              <div
                className="absolute -top-1 -bottom-1 w-0.5 rounded-full bg-text-primary/70"
                style={{ left: `${(hi / MAX) * 100}%` }}
                aria-hidden
              />
            </div>
            <div className="mt-2 flex justify-between text-xs text-text-tertiary">
              <span>0</span>
              <span>
                target {lo}–{hi}
              </span>
              <span>{MAX}</span>
            </div>
            {hasSplit && (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-tertiary font-mono-nums">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-accent" aria-hidden /> Cardio {cardioValue.toFixed(1)}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-accent/60" aria-hidden /> Muscular {muscularValue.toFixed(1)}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-accent/30" aria-hidden /> Daily activity {dailyValue.toFixed(1)}
                </span>
              </div>
            )}
            {dailyActivity && (dailyActivity.steps != null || dailyActivity.active_kcal != null) && (
              <div className="mt-3 flex gap-4 text-xs text-text-tertiary font-mono-nums">
                {dailyActivity.steps != null && <span>{dailyActivity.steps.toLocaleString()} steps</span>}
                {dailyActivity.active_kcal != null && <span>{Math.round(dailyActivity.active_kcal)} active kcal</span>}
              </div>
            )}
          </Card>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-5 shadow-xl focus:outline-none">
          <Dialog.Title className="text-base font-semibold text-text-primary">Strain breakdown</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            {strain?.explanation ?? "No strain data for today yet."}
          </Dialog.Description>
          <div className="mt-4 flex flex-col gap-2">
            {sessionComponents.length > 0 || dailyActivityComponent ? (
              <>
                {sessionComponents.map((c, i) => (
                  <div key={i} className="flex items-center justify-between rounded-md bg-surface-2 px-3 py-2 text-sm">
                    <span className="text-text-secondary">{String(c.title ?? "Session")}</span>
                    <span className="font-mono-nums text-text-primary">
                      {c.value == null ? "—" : `${(c.value as number).toFixed(1)}`}
                      {hasValue && c.value != null && (
                        <span className="ml-1 text-text-tertiary">
                          ({Math.round(((c.value as number) / value) * 100)}%)
                        </span>
                      )}
                    </span>
                  </div>
                ))}
                {dailyActivityComponent && (
                  <div className="flex items-center justify-between rounded-md bg-surface-2 px-3 py-2 text-sm">
                    <div className="flex flex-col">
                      <span className="text-text-secondary">Daily activity</span>
                      {(dailyActivityComponent.steps != null || dailyActivityComponent.active_kcal != null) && (
                        <span className="text-xs text-text-tertiary font-mono-nums">
                          {dailyActivityComponent.steps != null && `${dailyActivityComponent.steps.toLocaleString()} steps`}
                          {dailyActivityComponent.steps != null && dailyActivityComponent.active_kcal != null && " · "}
                          {dailyActivityComponent.active_kcal != null && `${Math.round(dailyActivityComponent.active_kcal)} kcal`}
                          {" "}
                          (non-exercise)
                        </span>
                      )}
                    </div>
                    <span className="font-mono-nums text-text-primary">
                      {dailyActivityComponent.value.toFixed(1)}
                      {hasValue && value > 0 && (
                        <span className="ml-1 text-text-tertiary">
                          ({Math.round((dailyActivityComponent.value / value) * 100)}%)
                        </span>
                      )}
                    </span>
                  </div>
                )}
              </>
            ) : (
              <EmptyState message="No components scored yet." />
            )}
          </div>
          <Dialog.Close asChild>
            <button
              type="button"
              className="mt-4 min-h-11 w-full rounded-md border border-border text-sm font-medium text-text-primary transition-colors hover:border-accent"
            >
              Close
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
