import type { IntervalSummary } from "../../lib/types";
import { formatNumber, formatPercent, formatSplit } from "../../lib/format";

export function IntervalTable({
  intervals,
  hoveredInterval,
  onHoverInterval,
}: {
  intervals: Record<string, IntervalSummary>;
  hoveredInterval?: number | null;
  onHoverInterval?: (index: number | null) => void;
}) {
  const sorted = Object.entries(intervals).sort((a, b) => Number(a[0]) - Number(b[0]));

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
                  <span className={s.drift_vs_rep1_pct > 1 ? "text-band-red-text" : "text-text-secondary"}>
                    {s.drift_vs_rep1_pct > 0 ? "+" : ""}
                    {formatPercent(s.drift_vs_rep1_pct, 1)}
                  </span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
