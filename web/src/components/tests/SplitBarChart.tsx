import { formatSplit } from "../../lib/format";
import { METRIC_COLOR } from "../../lib/metricColors";
import type { ActualSplit, PacingVsPlanRow } from "../../lib/types";
import { Legend } from "../charts/core";
import { ValueBars } from "../charts/ValueBars";

/** Actual split per 500m, faster reading taller, with the plan's target as a dashed tick — static on purpose (a test is at most ~12
 * splits; nothing to zoom into). The full interactive stroke chart for this activity is one tap away on workout detail. */
export function SplitBarChart({ splits, vsPlan }: { splits: ActualSplit[]; vsPlan: PacingVsPlanRow[] | null }) {
  const valid = splits.filter((s) => s.actual_split_s != null);
  if (valid.length === 0) return <p className="text-sm text-text-tertiary">No split data.</p>;
  const targetBySplit = new Map((vsPlan ?? []).map((r) => [r.split_index, r.target_s]));
  const hasTargets = valid.some((s) => targetBySplit.has(s.split_index));
  return (
    <div>
      <ValueBars
        bars={valid.map((s) => ({ key: s.split_index, label: `${s.distance_m}m`, value: s.actual_split_s as number, target: targetBySplit.get(s.split_index) ?? null }))}
        format={formatSplit}
        axis="seconds"
        invert
        color={METRIC_COLOR.pace}
        ariaLabel={`Actual split time per 500m, faster splits read taller: ${valid.map((s) => `${s.distance_m}m ${formatSplit(s.actual_split_s)}`).join(", ")}`}
      />
      <Legend className="mt-1" items={[{ label: "Split /500m", color: METRIC_COLOR.pace, style: "block" }, ...(hasTargets ? [{ label: "Target", color: "var(--text-primary)", style: "dash" as const }] : [])]} />
    </div>
  );
}
