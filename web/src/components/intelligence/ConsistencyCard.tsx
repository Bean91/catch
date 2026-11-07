import { formatPercent } from "../../lib/format";
import { BandBadge } from "../ui/Badge";
import type { TrainingConsistency } from "../../lib/types";

const BAND_LABELS: Record<string, string> = {
  on_target: "On target",
  below_target: "Below target",
  well_below_target: "Well below target",
  insufficient_data: "Not enough data",
};

/** Same self-contained shape as today/IllnessCard.tsx: a Card-level status badge, an
 * explanation paragraph, and a derived "Signals: ..." line. */
export function ConsistencyCard({ consistency }: { consistency: TrainingConsistency }) {
  const signals: string[] = [];
  if (consistency.rest_days > 0) signals.push(`${consistency.rest_days} rest day(s)`);
  if (consistency.concentrated_block) signals.push("training unusually concentrated on a couple of days");
  if (consistency.strength_sessions > 0) signals.push(`${consistency.strength_sessions} strength session(s)`);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm text-text-primary">
          {consistency.sessions_completed} of {consistency.sessions_target} sessions
          {consistency.pct_of_target != null && <span className="text-text-tertiary"> ({formatPercent(consistency.pct_of_target * 100)})</span>}
        </p>
        <BandBadge band={consistency.band} label={BAND_LABELS[consistency.band] ?? consistency.band} />
      </div>
      <p className="text-sm text-text-secondary">{consistency.explanation}</p>
      {signals.length > 0 && <p className="mt-2 text-xs text-text-tertiary">Signals: {signals.join(", ")}.</p>}
    </div>
  );
}
