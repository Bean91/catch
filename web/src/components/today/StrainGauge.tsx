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
import { ModalContent } from "../ui/Sheet";

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
  const dailyActivityComponent = strain?.daily_activity;
  // The gauge fill splits into heart-rate/muscular/everyday segments — three opacities of the one accent, not a second hue
  // (DESIGN.md), always paired with the legend text. Session 32: each segment is that part's *share* of the day's one load sum, so
  // the three always add up to the number shown; nothing is added together in 0–21 space any more.
  const cardioValue = strain?.cardio?.value ?? 0;
  const muscularValue = strain?.muscular?.value ?? 0;
  const dailyValue = dailyActivityComponent?.value ?? 0;
  const hasSplit = hasValue && (cardioValue > 0 || muscularValue > 0 || dailyValue > 0);
  const pctOf = (share: number | undefined, part: number) =>
    Math.round((share ?? (value > 0 ? part / value : 0)) * 100);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className="h-full w-full text-left transition-transform duration-150 active:scale-[0.995]" aria-label="Strain breakdown">
          <Card className="h-full hover:border-accent/40" title="Strain today" action={strain && <BandBadge band={strain.band} label={bandLabel(strain.band)} />}>
            <div className="flex items-baseline gap-2">
              {hasValue ? (
                <CountUp value={value} decimals={1} className="text-[2.5rem] font-semibold leading-none tracking-tight text-text-primary" />
              ) : (
                <span className="font-mono-nums text-[2.5rem] font-semibold leading-none text-text-tertiary">—</span>
              )}
              <span className="text-sm text-text-tertiary font-mono-nums">/ {MAX}</span>
            </div>
            <div className="relative mt-4 h-3 w-full">
              <div className="absolute inset-0 overflow-hidden rounded-full bg-surface-2">
                {/* The target range as a quiet track segment, under the fill. */}
                <div aria-hidden className="absolute inset-y-0 bg-text-primary/[0.06]" style={{ left: `${(lo / MAX) * 100}%`, width: `${((hi - lo) / MAX) * 100}%` }} />
                {hasSplit ? (
                  <motion.div
                    className="absolute inset-y-0 left-0 flex overflow-hidden rounded-full"
                    initial={{ width: reduced ? `${pct}%` : "0%" }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: reduced ? 0 : 1, ease: [0.16, 1, 0.3, 1] }}
                  >
                    <div className="h-full bg-accent shadow-[0_0_12px_var(--accent-soft)]" style={{ width: `${(cardioValue / Math.max(value, 0.01)) * 100}%` }} />
                    <div className="h-full bg-accent/60" style={{ width: `${(muscularValue / Math.max(value, 0.01)) * 100}%` }} />
                    <div className="h-full bg-accent/30" style={{ width: `${(dailyValue / Math.max(value, 0.01)) * 100}%` }} />
                  </motion.div>
                ) : (
                  <motion.div
                    className="absolute inset-y-0 left-0 rounded-full bg-[linear-gradient(90deg,color-mix(in_oklab,var(--accent)_60%,transparent),var(--accent))]"
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
                  <span className="h-2 w-2 rounded-full bg-accent" aria-hidden /> Cardio {pctOf(strain?.cardio?.share, cardioValue)}%
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-accent/60" aria-hidden /> Muscular {pctOf(strain?.muscular?.share, muscularValue)}%
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-accent/30" aria-hidden /> Everyday movement {pctOf(dailyActivityComponent?.share, dailyValue)}%
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
      <ModalContent width="sm">
          <Dialog.Title className="text-lg font-semibold text-text-primary">Strain breakdown</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            {strain?.explanation ?? "No strain data for today yet."}
          </Dialog.Description>
          <div className="mt-4 flex flex-col gap-2">
            {sessionComponents.length > 0 || dailyActivityComponent ? (
              <>
                {sessionComponents.map((c, i) => {
                  const share = typeof c.share === "number" ? (c.share as number) : null;
                  const duplicate = c.duplicate_of != null;
                  return (
                    <div key={i} className="flex items-center justify-between rounded-md bg-surface-2 px-3 py-2 text-sm">
                      <div className="flex flex-col">
                        <span className="text-text-secondary">{String(c.title ?? "Session")}</span>
                        {duplicate && <span className="text-xs text-text-tertiary">Same time as another workout — counted once</span>}
                      </div>
                      <span className="font-mono-nums text-text-primary">
                        {/* A session's share of the day's load — shares add up to 100 % (session 32). */}
                        {share == null ? "—" : `${Math.round(share * 100)}%`}
                      </span>
                    </div>
                  );
                })}
                {dailyActivityComponent && (
                  <div className="flex items-center justify-between rounded-md bg-surface-2 px-3 py-2 text-sm">
                    <div className="flex flex-col">
                      <span className="text-text-secondary">Everyday movement</span>
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
                    <span className="font-mono-nums text-text-primary">{pctOf(dailyActivityComponent.share, dailyActivityComponent.value)}%</span>
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
        </ModalContent>
    </Dialog.Root>
  );
}
