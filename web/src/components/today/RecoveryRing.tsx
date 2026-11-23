import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import type { Recovery } from "../../lib/types";
import { bandLabel } from "../../lib/format";
import { useReducedMotion } from "../../lib/useReducedMotion";
import { BandBadge } from "../ui/Badge";
import { CountUp } from "../ui/CountUp";
import { EmptyState } from "../ui/EmptyState";
import { useSvgId } from "../charts/core";
import { ModalContent } from "../ui/Sheet";
import { buttonClass } from "../ui/Button";

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
  checkin: "Morning check-in",
};

const SOURCE_LABEL: Record<string, string> = { garmin: "Garmin", whoop: "Whoop", apple_health: "Apple Health", health_connect: "Health Connect", catch: "Catch", you: "You" };

const SIZE = 184;
const STROKE = 12;
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
  const gradId = useSvgId("recovery-arc");

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="group relative flex h-full w-full flex-col items-center justify-center gap-3 overflow-hidden rounded-lg border border-border bg-surface p-5 shadow-[var(--highlight),var(--shadow-1)] transition-[border-color,transform] duration-150 hover:border-accent/40 active:scale-[0.995]"
          aria-label="Recovery details"
        >
          {/* A soft wash of the band's colour behind the ring — the one place a status colour tints a surface. */}
          <span aria-hidden className="pointer-events-none absolute inset-0 opacity-70" style={{ background: `radial-gradient(70% 55% at 50% 42%, color-mix(in oklab, ${color} 16%, transparent), transparent 72%)` }} />
          <span className="relative self-start text-[0.9375rem] font-semibold text-text-primary">Recovery</span>
          <div className="relative" style={{ width: SIZE, height: SIZE }}>
            <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="-rotate-90">
              <defs>
                <linearGradient id={gradId} x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor={`color-mix(in oklab, ${color} 55%, white)`} />
                  <stop offset="100%" stopColor={color} />
                </linearGradient>
              </defs>
              <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke="var(--surface-2)" strokeWidth={STROKE} />
              <circle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={RADIUS}
                fill="none"
                stroke={`url(#${gradId})`}
                strokeWidth={STROKE}
                strokeLinecap="round"
                strokeDasharray={CIRCUMFERENCE}
                strokeDashoffset={offset}
                className={reduced ? undefined : "ring-draw"}
                style={{ ["--from" as string]: CIRCUMFERENCE, filter: `drop-shadow(0 0 6px color-mix(in oklab, ${color} 45%, transparent))` }}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              {hasValue ? (
                <CountUp value={value} decimals={0} suffix="%" className="text-[2.75rem] font-semibold leading-none tracking-tight text-text-primary" />
              ) : (
                <span className="font-mono-nums text-lg font-medium text-text-tertiary">—</span>
              )}
              <span className="mt-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-text-tertiary">score</span>
            </div>
          </div>
          <span className="relative">
            <BandBadge band={band} label={band === "calibrating" ? "Calibrating" : bandLabel(band)} />
          </span>
        </button>
      </Dialog.Trigger>
      <ModalContent width="sm">
          <Dialog.Title className="text-lg font-semibold text-text-primary">Recovery breakdown</Dialog.Title>
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
          {recovery?.calibration && (
            <p data-testid="recovery-calibration" className="mt-3 text-sm text-text-secondary">
              {recovery.calibration.status === "calibrated"
                ? `Baseline ready — ${recovery.calibration.nights} nights of HRV.`
                : `Calibrating — ${recovery.calibration.nights} of ${recovery.calibration.required} nights of HRV so far.`}
            </p>
          )}
          {recovery?.data_availability && (
            <div className="mt-3" data-testid="recovery-availability">
              <h3 className="text-xs font-medium uppercase tracking-wide text-text-tertiary">What this score used</h3>
              <ul className="mt-1.5 flex flex-col gap-1.5">
                {recovery.data_availability.map((a) => (
                  <li key={a.signal} className="flex items-start justify-between gap-3 text-sm">
                    <span className="text-text-secondary">
                      {a.label}
                      {!a.in_score && <span className="text-text-tertiary"> · shown, not scored</span>}
                    </span>
                    <span className="text-right text-text-primary">
                      {a.available ? `✓ ${a.source ? (SOURCE_LABEL[a.source] ?? a.source) : "today"}` : "— none today"}
                      {a.baseline_nights != null && a.baseline_needed != null && (
                        <span className="block text-xs text-text-tertiary">
                          {a.baseline_nights}/{a.baseline_needed} nights
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {recovery?.baseline_mixed_sources && recovery.baseline_mixed_sources.length > 0 && (
            <p data-testid="recovery-mixed" className="mt-3 rounded-md bg-surface-2 px-3 py-2 text-xs text-text-secondary">
              The last week of this baseline mixes devices (Garmin and Whoop measure HRV differently), so today's comparison is less exact until a
              week of one source builds up.
            </p>
          )}
          <Dialog.Close asChild>
            <button
              type="button"
              className={buttonClass("secondary", "md", "mt-4 w-full")}
            >
              Close
            </button>
          </Dialog.Close>
        </ModalContent>
    </Dialog.Root>
  );
}
