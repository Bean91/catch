import { formatDuration, formatShortDate, formatSplit } from "../../lib/format";
import type { BodyMassPower, ErgTestSummary, PacingAnalysis } from "../../lib/types";
import { Card } from "../ui/Card";
import { StatTile } from "../ui/StatTile";
import { SplitBarChart } from "./SplitBarChart";

/** Test and piece detail share this: the split chart, the three segments, and the even-split reading. */
export function PacingCard({ pacing, planStyle }: { pacing: PacingAnalysis; planStyle?: string | null }) {
  return (
    <Card material="solid" title="Pacing">
      <SplitBarChart splits={pacing.splits} vsPlan={pacing.vs_plan} />
      <div className="mt-4 grid grid-cols-3 gap-3 rounded-md bg-surface-2/60 p-3">
        <StatTile size="sm" label="Start" value={formatSplit(pacing.segments.start)} />
        <StatTile size="sm" label="Middle 1000" value={formatSplit(pacing.segments.middle_1000)} />
        <StatTile size="sm" label="Sprint" value={formatSplit(pacing.segments.sprint)} />
      </div>
      <div className="mt-3 flex flex-col gap-1 text-sm text-text-secondary">
        <span>
          Even split: <span className="font-mono-nums text-text-primary">{formatSplit(pacing.even_split_s)}</span>
          {pacing.deviation_from_even_pct != null && <> ({pacing.deviation_from_even_pct.toFixed(1)}% spread)</>}
        </span>
        {pacing.worst_split_vs_even && (
          <span>
            Slowest: split {pacing.worst_split_vs_even.split_index}, {pacing.worst_split_vs_even.seconds_lost_vs_even.toFixed(1)}s slower than even.
          </span>
        )}
      </div>
      {planStyle && <p className="mt-2 text-xs text-text-tertiary">Dashed line is the saved {planStyle.replace(/_/g, " ")} plan.</p>}
    </Card>
  );
}

/** Then and now, side by side, with the change in time stated in words. */
export function CompareCard({ title, earlier, nowDate, nowDurationS }: { title: string; earlier: ErgTestSummary & BodyMassPower; nowDate: string | null | undefined; nowDurationS: number | null | undefined }) {
  const delta = earlier.duration_s != null && nowDurationS != null ? nowDurationS - earlier.duration_s : null;
  return (
    <Card title={title}>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4">
        <StatTile size="md" label={earlier.date ? formatShortDate(earlier.date) : "Earlier"} value={formatDuration(earlier.duration_s)} />
        <span aria-hidden className="text-lg text-text-tertiary">→</span>
        <StatTile size="md" label={nowDate ? formatShortDate(nowDate) : "This one"} value={formatDuration(nowDurationS ?? null)} />
      </div>
      {delta != null && delta !== 0 && (
        <p className="mt-3 text-sm text-text-secondary">
          {Math.abs(delta).toFixed(1)}s {delta < 0 ? "faster" : "slower"} than that one.
        </p>
      )}
    </Card>
  );
}
