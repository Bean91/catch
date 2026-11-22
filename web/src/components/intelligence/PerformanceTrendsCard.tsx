import { useState } from "react";
import { PieceTrendMiniChart } from "../charts/PieceTrendMiniChart";
import { EmptyState } from "../ui/EmptyState";
import type { PerformanceTrendBucket } from "../../lib/types";
import { WAP_EXPLAINER, WAP_UNIT } from "../pieces/MassPower";

function BucketRow({ bucket }: { bucket: PerformanceTrendBucket }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-border pt-3 first:border-t-0 first:pt-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full min-h-11 items-center justify-between text-left"
      >
        <span className="text-sm font-medium text-text-primary">{bucket.bucket_label}</span>
        <span className="flex items-center gap-2 text-xs text-text-tertiary">
          {bucket.n_points} piece(s)
          <svg viewBox="0 0 24 24" fill="none" className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden>
            <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </button>
      {open && (
        <div className="mt-2">
          <PieceTrendMiniChart bucket={bucket} />
          <p className="mt-1 text-xs text-text-tertiary">{bucket.trend.explanation}</p>
          {(bucket.best?.weight_adjusted_watts != null || bucket.recent?.weight_adjusted_watts != null) && (
            <dl className="mt-2 grid grid-cols-2 gap-2 text-xs" data-testid={`trend-wap-${bucket.bucket_label}`}>
              {(["best", "recent"] as const).map((k) => {
                const p = bucket[k];
                return (
                  <div key={k}>
                    <dt className="text-text-tertiary">{k === "best" ? "Best" : "Most recent"} · weight-adjusted</dt>
                    <dd className="font-mono-nums text-text-primary">
                      {p?.weight_adjusted_watts != null ? `${p.weight_adjusted_watts.toFixed(2)} ${WAP_UNIT}` : "—"}
                      {p?.avg_watts != null && <span className="text-text-secondary"> · {Math.round(p.avg_watts)} W</span>}
                    </dd>
                  </div>
                );
              })}
              <p className="col-span-2 text-text-tertiary">{WAP_EXPLAINER} Each effort uses its own day's weigh-in.</p>
            </dl>
          )}
        </div>
      )}
    </div>
  );
}

export function PerformanceTrendsCard({ buckets }: { buckets: PerformanceTrendBucket[] }) {
  if (buckets.length === 0) {
    return <EmptyState message="No confirmed tests or pieces yet — add one from the Test Center to see trends here." />;
  }
  return (
    <div className="flex flex-col gap-3">
      {buckets.map((b) => (
        <BucketRow key={b.bucket_label} bucket={b} />
      ))}
    </div>
  );
}
