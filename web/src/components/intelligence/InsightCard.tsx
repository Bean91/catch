import { useState } from "react";
import { EmptyState } from "../ui/EmptyState";
import type { EvidenceItem, TrainingInsight } from "../../lib/types";

function EvidenceList({ evidence }: { evidence: EvidenceItem[] }) {
  return (
    <ul className="mt-2 flex flex-col gap-1 rounded-md border border-border bg-surface-2 p-2.5 text-xs text-text-secondary">
      {evidence.map((e, i) => (
        <li key={i} className="font-mono-nums">
          {e.label}: {typeof e.value === "object" ? JSON.stringify(e.value) : String(e.value)}
          <span className="ml-1 text-text-tertiary">({e.source})</span>
        </li>
      ))}
    </ul>
  );
}

/** Each insight is expandable to show the data behind it — the same open/chevron toggle
 * ToolCallChip.tsx already uses, rendering a formatted list rather than raw JSON. */
function InsightRow({ insight }: { insight: TrainingInsight }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-border pt-3 first:border-t-0 first:pt-0">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full min-h-11 items-start justify-between gap-2 text-left">
        <span>
          <span className="block text-sm font-medium text-text-primary">{insight.title}</span>
          <span className="block text-sm text-text-secondary">{insight.body}</span>
        </span>
        <svg viewBox="0 0 24 24" fill="none" className={`mt-1 h-3 w-3 flex-shrink-0 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden>
          <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && <EvidenceList evidence={insight.evidence} />}
    </div>
  );
}

export function InsightsList({ insights }: { insights: TrainingInsight[] }) {
  if (insights.length === 0) {
    return <EmptyState message="No recurring patterns identified yet — check back as more data comes in." />;
  }
  return (
    <div className="flex flex-col gap-3">
      {insights.map((i) => (
        <InsightRow key={i.id} insight={i} />
      ))}
    </div>
  );
}
