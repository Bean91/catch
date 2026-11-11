import { formatSplit } from "../../lib/format";
import type { IntervalComparisonBucket } from "../../lib/types";
import { EmptyState } from "../ui/EmptyState";

/** Session 19: interval sessions compared only against sessions of the same structure
 * ("4x500m/r60"), by weighted-average split. Confidence is plain text, same as the rest of
 * Training intelligence (DESIGN.md) — no colored badge. */
export function IntervalComparisonCard({ buckets }: { buckets: IntervalComparisonBucket[] }) {
  if (buckets.length === 0) {
    return <EmptyState message="No interval sessions yet — log a piece with intervals and it will be compared against future sessions of the same structure." />;
  }
  return (
    <div className="flex flex-col gap-3" data-testid="interval-comparisons">
      {buckets.map((b) => (
        <div key={b.bucket_label} className="border-t border-border pt-3 first:border-t-0 first:pt-0">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm font-medium text-text-primary">{b.bucket_label}</span>
            <span className="text-xs text-text-tertiary">
              {b.n_points} session{b.n_points === 1 ? "" : "s"} · confidence {b.confidence.replace("_", " ")}
            </span>
          </div>
          {b.recent && (
            <dl className="mt-1.5 grid grid-cols-3 gap-2 text-xs">
              <div>
                <dt className="text-text-tertiary">Best</dt>
                <dd className="font-mono-nums text-text-primary">{formatSplit(b.best?.value)}</dd>
              </div>
              <div>
                <dt className="text-text-tertiary">Typical</dt>
                <dd className="font-mono-nums text-text-primary">{formatSplit(b.typical?.value)}</dd>
              </div>
              <div>
                <dt className="text-text-tertiary">Recent</dt>
                <dd className="font-mono-nums text-text-primary">
                  {formatSplit(b.recent.value)}
                  {b.delta_vs_typical_pct != null && <span className="ml-1 text-text-tertiary">({b.delta_vs_typical_pct > 0 ? "+" : ""}{b.delta_vs_typical_pct.toFixed(1)}%)</span>}
                </dd>
              </div>
            </dl>
          )}
          {b.note && <p className="mt-1 text-xs text-text-tertiary">{b.note}</p>}
        </div>
      ))}
    </div>
  );
}
