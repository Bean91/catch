import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "framer-motion";
import { useState } from "react";
import type { Recovery } from "../../lib/types";
import { bandLabel } from "../../lib/format";
import { useReducedMotion } from "../../lib/useReducedMotion";
import { BandBadge } from "../ui/Badge";
import { CountUp } from "../ui/CountUp";
import { EmptyState } from "../ui/EmptyState";
import { Waterline } from "../ui/Waterline";

const BAND_COLOR: Record<string, string> = {
  green: "var(--band-green)",
  yellow: "var(--band-yellow)",
  red: "var(--band-red)",
  calibrating: "var(--band-calibrating)",
  insufficient_data: "var(--band-calibrating)",
};

const METRIC_LABEL: Record<string, string> = {
  hrv: "HRV",
  resting_hr: "Resting heart rate",
  sleep: "Sleep vs need",
  prior_strain: "Yesterday's strain",
};

const SIZE = 180;
const STROKE = 14;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function RecoveryRing({ recovery }: { recovery: Recovery | null }) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  const band = recovery?.band ?? "calibrating";
  const color = BAND_COLOR[band] ?? BAND_COLOR.calibrating;
  const value = recovery?.value ?? 0;
  const hasValue = recovery != null && recovery.value != null;
  const offset = CIRCUMFERENCE * (1 - value / 100);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="flex h-full w-full flex-col items-center justify-center gap-3 rounded-lg border border-border bg-surface p-5 transition-colors hover:border-accent/40"
          aria-label="Recovery details"
        >
          <div className="relative" style={{ width: SIZE, height: SIZE }}>
            <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="-rotate-90">
              <circle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={RADIUS}
                fill="none"
                stroke="var(--surface-2)"
                strokeWidth={STROKE}
              />
              <motion.circle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={RADIUS}
                fill="none"
                stroke={color}
                strokeWidth={STROKE}
                strokeLinecap="round"
                strokeDasharray={CIRCUMFERENCE}
                initial={{ strokeDashoffset: reduced ? offset : CIRCUMFERENCE }}
                animate={{ strokeDashoffset: offset }}
                transition={{ duration: reduced ? 0 : 1.1, ease: [0.16, 1, 0.3, 1] }}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              {hasValue ? (
                <>
                  <CountUp value={value} decimals={0} suffix="%" className="text-4xl font-semibold text-text-primary" />
                </>
              ) : (
                <span className="font-mono-nums text-lg font-medium text-text-tertiary">—</span>
              )}
              <span className="mt-1 text-xs uppercase tracking-wide text-text-tertiary">Recovery</span>
            </div>
          </div>
          <BandBadge band={band} label={band === "calibrating" ? "Calibrating" : bandLabel(band)} />
          <Waterline />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 w-[min(92vw,420px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-5 shadow-xl focus:outline-none">
          <Dialog.Title className="text-base font-semibold text-text-primary">Recovery breakdown</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            {recovery?.explanation ?? "Need at least 7 nights of HRV history before a baseline exists."}
          </Dialog.Description>
          <div className="mt-4 flex flex-col gap-2">
            {recovery?.components && recovery.components.length > 0 ? (
              recovery.components.map((c, i) => (
                <div key={i} className="flex items-center justify-between rounded-md bg-surface-2 px-3 py-2 text-sm">
                  <span className="text-text-secondary">{METRIC_LABEL[c.metric as string] ?? String(c.metric)}</span>
                  <span className="font-mono-nums text-text-primary">
                    {c.value == null ? "—" : `${Math.round(c.value as number)}`}
                  </span>
                </div>
              ))
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
