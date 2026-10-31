import { motion } from "framer-motion";
import type { Strain } from "../../lib/types";
import { bandLabel } from "../../lib/format";
import { useReducedMotion } from "../../lib/useReducedMotion";
import { BandBadge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { CountUp } from "../ui/CountUp";

const MAX = 21;

export function StrainGauge({ strain, targetRange }: { strain: Strain | null; targetRange: [number, number] }) {
  const reduced = useReducedMotion();
  const value = strain?.value ?? 0;
  const hasValue = strain != null && strain.value != null;
  const pct = (value / MAX) * 100;
  const [lo, hi] = targetRange;

  return (
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
          <motion.div
            className="absolute inset-y-0 left-0 rounded-full bg-accent"
            initial={{ width: reduced ? `${pct}%` : "0%" }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: reduced ? 0 : 1, ease: [0.16, 1, 0.3, 1] }}
          />
        </div>
        {/* Target-range boundary ticks sit above the fill (not a translucent band under it) so
            they stay visible even once the fill passes through or past the target range. */}
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
    </Card>
  );
}
