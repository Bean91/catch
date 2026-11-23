import type { IntervalConsistency, IntervalSummary } from "../../lib/types";
import { formatDuration, formatNumber, formatPercent, formatSplit } from "../../lib/format";

export function IntervalTable({
  intervals,
  consistency,
  hoveredInterval,
  onHoverInterval,
}: {
  intervals: Record<string, IntervalSummary>;
  consistency?: IntervalConsistency | null;
  hoveredInterval?: number | null;
  onHoverInterval?: (index: number | null) => void;
}) {
  const sorted = Object.entries(intervals).sort((a, b) => Number(a[0]) - Number(b[0]));
  const anyRest = sorted.some(([, s]) => s.rest_s != null);

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-sm">
        <thead>
          <tr className="text-left text-xs text-text-tertiary">
            <th className="py-1 font-normal">Rep</th>
            <th className="py-1 font-normal">Split</th>
            <th className="py-1 font-normal">Rate</th>
            <th className="py-1 font-normal">Watts</th>
            <th className="py-1 font-normal">HR</th>
            <th className="py-1 font-normal">Drift vs rep 1</th>
            {anyRest && <th className="py-1 font-normal">Rest after</th>}
          </tr>
        </thead>
        <tbody>
          {sorted.map(([idx, s]) => (
            <tr
              key={idx}
              className={`text-text-primary ${hoveredInterval === Number(idx) ? "bg-surface-2" : ""}`}
              onPointerEnter={() => onHoverInterval?.(Number(idx))}
              onPointerLeave={() => onHoverInterval?.(null)}
            >
              <td className="py-1.5 font-mono-nums">{Number(idx) + 1}</td>
              <td className="py-1.5 font-mono-nums">{s.avg_split_500m != null ? `${formatSplit(s.avg_split_500m)}/500m` : "—"}</td>
              <td className="py-1.5 font-mono-nums">{s.avg_stroke_rate != null ? formatNumber(s.avg_stroke_rate) : "—"}</td>
              <td className="py-1.5 font-mono-nums">{s.avg_watts != null ? formatNumber(s.avg_watts) : "—"}</td>
              <td className="py-1.5 font-mono-nums">{s.avg_hr != null ? formatNumber(s.avg_hr) : "—"}</td>
              <td className="py-1.5 font-mono-nums">
                {s.drift_vs_rep1_pct != null ? (
                  <span className="text-text-secondary">
                    {s.drift_vs_rep1_pct > 0 ? "+" : ""}
                    {formatPercent(s.drift_vs_rep1_pct, 1)}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              {anyRest && <td className="py-1.5 font-mono-nums italic text-text-tertiary">{s.rest_s != null ? formatDuration(s.rest_s) : "—"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {consistency && (consistency.split_cv_pct != null || consistency.watts_cv_pct != null) && (
        <p className="mt-2 text-xs text-text-secondary" data-testid="interval-consistency">
          Across {consistency.reps} reps:{" "}
          {consistency.split_spread_s != null && <>fastest and slowest split {formatNumber(consistency.split_spread_s, 1)} s apart</>}
          {consistency.split_cv_pct != null && <> · split varied {formatNumber(consistency.split_cv_pct, 1)}%</>}
          {consistency.watts_cv_pct != null && <> · watts varied {formatNumber(consistency.watts_cv_pct, 1)}%</>}
          {consistency.fade_pct != null && <> · last rep {formatNumber(Math.abs(consistency.fade_pct), 1)}% {consistency.fade_pct > 0 ? "slower" : "faster"} than the first</>}.
        </p>
      )}
      <p className="mt-1 text-xs text-text-tertiary">
        Split is worked out from each rep's time and distance; rate, watts and heart rate are averages of what the PM5 recorded stroke by stroke. Variation is the standard deviation as a share of the average.
      </p>
    </div>
  );
}
