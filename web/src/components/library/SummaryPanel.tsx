import { formatClock, formatMetres, formatMinutesOrHours } from "../../lib/duration";
import type { TemplateSummary } from "../../lib/types";

// Every figure comes from the server. Where the server says a total can't be known, this says so
// rather than leaving a gap that looks like zero.
export function SummaryPanel({ summary }: { summary: TemplateSummary }) {
  const total = summary.total_duration_s;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm" data-testid="template-summary">
      <div>
        <dt className="text-text-tertiary">Total time</dt>
        <dd className="font-mono-nums text-text-primary" data-testid="summary-total">
          {total != null ? formatMinutesOrHours(total) : "Not set"}
        </dd>
        <dd className="text-xs text-text-tertiary">
          {total == null
            ? "A distance block has no duration until you set a split or watts target."
            : summary.duration_basis === "estimated"
              ? "Estimated from your split or watts target."
              : "Exact."}
        </dd>
      </div>
      <div>
        <dt className="text-text-tertiary">Work distance</dt>
        <dd className="font-mono-nums text-text-primary">{summary.work_distance_m != null ? formatMetres(summary.work_distance_m) : "—"}</dd>
      </div>
      <div>
        <dt className="text-text-tertiary">Work</dt>
        <dd className="font-mono-nums text-text-primary">{summary.work_duration_s != null ? formatClock(summary.work_duration_s) : "—"}</dd>
      </div>
      <div>
        <dt className="text-text-tertiary">Rest</dt>
        <dd className="font-mono-nums text-text-primary">{summary.rest_duration_s ? formatClock(summary.rest_duration_s) : "—"}</dd>
      </div>
      {summary.work_rest_ratio != null && (
        <div>
          <dt className="text-text-tertiary">Work : rest</dt>
          <dd className="font-mono-nums text-text-primary">{summary.work_rest_ratio.toFixed(1)} : 1</dd>
        </div>
      )}
      {Object.keys(summary.zone_minutes).length > 0 && (
        <div className="col-span-2">
          <dt className="text-text-tertiary">Minutes in each zone (work only)</dt>
          <dd className="font-mono-nums text-text-primary">
            {Object.entries(summary.zone_minutes)
              .map(([z, m]) => `${z} ${Math.round(m)}`)
              .join(" · ")}
          </dd>
        </div>
      )}
      {summary.strength_exercise_count > 0 && (
        <div>
          <dt className="text-text-tertiary">Exercises</dt>
          <dd className="font-mono-nums text-text-primary">{summary.strength_exercise_count}</dd>
        </div>
      )}
    </dl>
  );
}
