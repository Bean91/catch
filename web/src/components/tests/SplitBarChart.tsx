import { formatSplit } from "../../lib/format";
import type { ActualSplit, PacingVsPlanRow } from "../../lib/types";

const WIDTH = 640;
const HEIGHT = 200;
const PAD = 28;

/** A simple, static actual-vs-target per-500m bar chart — deliberately not built on top of
 * ErgChart's pan/zoom machinery (useChartInteraction/Domain): a test is at most ~12 splits,
 * short enough that there's nothing to zoom into, and reusing that whole interaction stack
 * here would be a lot of plumbing for no real benefit. The full interactive stroke chart for
 * this same activity is still one tap away via the workout-detail link. */
export function SplitBarChart({ splits, vsPlan }: { splits: ActualSplit[]; vsPlan: PacingVsPlanRow[] | null }) {
  const valid = splits.filter((s) => s.actual_split_s != null);
  if (valid.length === 0) return <p className="text-sm text-text-tertiary">No split data.</p>;

  const targetBySplit = new Map((vsPlan ?? []).map((r) => [r.split_index, r.target_s]));
  const allValues = valid.flatMap((s) => [s.actual_split_s as number, ...(targetBySplit.has(s.split_index) ? [targetBySplit.get(s.split_index)!] : [])]);
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const range = max - min || 1;
  const plotH = HEIGHT - PAD * 2;
  // Faster (lower seconds) reads as a taller bar — same "faster = higher" convention ErgChart uses.
  const barH = (v: number) => ((max - v) / range) * plotH + 8;
  const barW = (WIDTH - PAD * 2) / valid.length;

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" role="img" aria-label="Actual split time per 500m, faster splits read taller">
      {valid.map((s, i) => {
        const x = PAD + i * barW;
        const target = targetBySplit.get(s.split_index);
        const h = barH(s.actual_split_s as number);
        return (
          <g key={s.split_index}>
            {target != null && (
              <line
                x1={x + 2}
                x2={x + barW - 2}
                y1={PAD + plotH - barH(target) + 8}
                y2={PAD + plotH - barH(target) + 8}
                stroke="var(--text-tertiary)"
                strokeDasharray="4 3"
                strokeWidth={1.5}
              />
            )}
            <rect x={x + 4} y={PAD + plotH - h + 8} width={barW - 8} height={h} rx={3} fill="var(--accent)" opacity={0.85} />
            <text x={x + barW / 2} y={HEIGHT - 6} textAnchor="middle" className="font-mono-nums fill-[var(--text-tertiary)] text-[10px]">
              {s.distance_m}m
            </text>
            <text x={x + barW / 2} y={PAD + plotH - h - 2} textAnchor="middle" className="font-mono-nums fill-[var(--text-primary)] text-[10px]">
              {formatSplit(s.actual_split_s)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
