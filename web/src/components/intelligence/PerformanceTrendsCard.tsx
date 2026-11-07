import { useState } from "react";
import { PieceTrendMiniChart } from "../charts/PieceTrendMiniChart";
import { EmptyState } from "../ui/EmptyState";
import type { PerformanceTrendBucket } from "../../lib/types";

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
