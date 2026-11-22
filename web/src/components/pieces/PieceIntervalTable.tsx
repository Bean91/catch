import { formatDistance, formatDuration, formatSplit, splitUnitLabel } from "../../lib/format";
import { rateUnit, type PieceModality } from "../../lib/pieceSplits";
import type { PieceInterval, PieceIntervalSummary } from "../../lib/types";
import { WAP_EXPLAINER, WAP_UNIT } from "./MassPower";

const dash = "—";

/** Read-only intervals for a piece: a totals strip (work vs rest kept separate — rest is never
 * folded into the work figures), then one compact row per work interval with its rest shown as
 * a muted inset line beneath, so recovery reads as a different thing from effort. Every number
 * here is server-supplied (weighted averages included). */
export function PieceIntervalTable({
  intervals,
  summary,
  splitUnitM = 500,
  modality = "rowing_erg",
}: {
  intervals: PieceInterval[];
  summary: PieceIntervalSummary | null;
  splitUnitM?: number;
  modality?: PieceModality;
}) {
  const unit = splitUnitLabel(splitUnitM);
  // Session 34: the per-interval weight-adjusted column only when there is something to show (rowing + a suitable weigh-in).
  const showWap = intervals.some((r) => r.weight_adjusted_watts != null);
  return (
    <div data-testid="interval-table">
      {summary && (
        <dl className="grid grid-cols-3 gap-2 text-center text-xs">
          <div>
            <dt className="text-text-tertiary">Work</dt>
            <dd className="font-mono-nums text-text-primary">
              {formatDistance(summary.work_distance_m)} · {formatDuration(summary.work_duration_s)}
            </dd>
          </div>
          <div>
            <dt className="text-text-tertiary">Rest</dt>
            <dd className="font-mono-nums text-text-primary">{summary.rest_duration_s ? formatDuration(summary.rest_duration_s) : dash}</dd>
          </div>
          <div>
            <dt className="text-text-tertiary">Avg split {unit}</dt>
            <dd className="font-mono-nums text-text-primary">{formatSplit(summary.avg_split_s)}</dd>
          </div>
          <div>
            <dt className="text-text-tertiary">Avg watts</dt>
            <dd className="font-mono-nums text-text-primary">{summary.avg_watts != null ? Math.round(summary.avg_watts) : dash}</dd>
          </div>
          {summary.weight_adjusted_watts != null && (
            <div>
              <dt className="text-text-tertiary" title={WAP_EXPLAINER}>Weight-adjusted</dt>
              <dd className="font-mono-nums text-text-primary" data-testid="interval-summary-wap">
                {summary.weight_adjusted_watts.toFixed(2)} {WAP_UNIT}
              </dd>
            </div>
          )}
          <div>
            <dt className="text-text-tertiary">{modality === "bike" ? "Avg cadence" : "Avg rate"}</dt>
            <dd className="font-mono-nums text-text-primary">{summary.avg_rate != null ? Math.round(summary.avg_rate) : dash}</dd>
          </div>
          <div>
            <dt className="text-text-tertiary">HR avg / max</dt>
            <dd className="font-mono-nums text-text-primary">
              {summary.avg_hr != null ? Math.round(summary.avg_hr) : dash} / {summary.max_hr != null ? Math.round(summary.max_hr) : dash}
            </dd>
          </div>
        </dl>
      )}
      {summary && summary.complete_count < summary.count && (
        <p className="mt-1.5 text-xs text-text-tertiary">
          {summary.complete_count} of {summary.count} intervals have both distance and time; averages use only what's recorded.
        </p>
      )}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[320px] text-left text-xs">
          <thead className="text-text-tertiary">
            <tr>
              <th className="py-1 pr-2 font-normal">#</th>
              <th className="py-1 pr-2 font-normal">Work</th>
              <th className="py-1 pr-2 font-normal">Time</th>
              <th className="py-1 pr-2 font-normal">Split {unit}</th>
              <th className="py-1 pr-2 font-normal">W</th>
              {showWap && <th className="py-1 pr-2 font-normal" title={WAP_EXPLAINER}>{WAP_UNIT}</th>}
              <th className="py-1 pr-2 font-normal">{rateUnit(modality)}</th>
              <th className="py-1 font-normal">HR</th>
            </tr>
          </thead>
          {intervals.map((r, i) => (
            <tbody key={r.id ?? i} className="font-mono-nums text-text-primary">
              <tr className="border-t border-border/60">
                <td className="py-1.5 pr-2 text-text-tertiary">{i + 1}</td>
                <td className="py-1.5 pr-2">{r.target_type === "distance" ? formatDistance(r.work_distance_m) : formatDuration(r.work_duration_s)}</td>
                <td className="py-1.5 pr-2">{r.work_duration_s ? formatDuration(r.work_duration_s) : dash}</td>
                <td className="py-1.5 pr-2">{formatSplit(r.split_s ?? null)}</td>
                <td className="py-1.5 pr-2">{r.avg_watts != null ? Math.round(r.avg_watts) : dash}</td>
                {showWap && <td className="py-1.5 pr-2">{r.weight_adjusted_watts != null ? r.weight_adjusted_watts.toFixed(1) : dash}</td>}
                <td className="py-1.5 pr-2">{r.avg_rate != null ? Math.round(r.avg_rate) : dash}</td>
                <td className="py-1.5">{r.avg_hr != null ? Math.round(r.avg_hr) : dash}</td>
              </tr>
              {r.rest_duration_s ? (
                <tr className="text-text-tertiary" data-testid="rest-row">
                  <td />
                  <td colSpan={showWap ? 7 : 6} className="pb-1.5 italic">
                    rest {formatDuration(r.rest_duration_s)}
                  </td>
                </tr>
              ) : null}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  );
}
