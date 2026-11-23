import { Link } from "react-router-dom";
import type { LbEntry } from "../../lib/types";
import { VerificationBadge } from "./VerificationBadge";

/** One public result. Every field shown here is in the server's public serializer — nothing is derived or looked up in the browser. */
export function EntryRow({ entry, onReport }: { entry: LbEntry; onReport?: (entry: LbEntry) => void }) {
  return (
    <li
      data-testid={`entry-${entry.entry_id}`}
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5 ${entry.is_you ? "border-accent/50 bg-surface-2" : "border-border bg-surface"}`}
    >
      {entry.rank !== undefined && (
        <span
          className={`font-mono-nums flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
            entry.rank != null && entry.rank <= 3 ? "bg-accent-soft text-accent ring-1 ring-accent/40" : "text-text-secondary"
          }`}
          aria-label={`Rank ${entry.rank}`}
        >
          {entry.rank}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link to={`/leaderboards/athletes/${entry.athlete_id}`} className="truncate text-sm font-medium text-text-primary hover:underline">
            {entry.name}
          </Link>
          {entry.is_you && <span className="text-xs font-medium text-accent">You</span>}
          <VerificationBadge state={entry.verification} />
        </div>
        <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-text-tertiary">
          {entry.age_label && (
            <span>
              {entry.age_label}
              {entry.age_provenance ? ` (${entry.age_provenance})` : ""}
            </span>
          )}
          {entry.weight_class && <span>{entry.weight_class}</span>}
          {entry.date_label && <span>{entry.date_label}</span>}
          {entry.note && <span className="italic">“{entry.note}”</span>}
        </p>
      </div>
      <div className="text-right">
        <p className="font-mono-nums text-sm font-semibold text-text-primary">{entry.result}</p>
        {entry.split_500m && <p className="font-mono-nums text-xs text-text-tertiary">{entry.split_500m} /500m</p>}
      </div>
      {onReport && !entry.is_you && (
        <button type="button" onClick={() => onReport(entry)} data-testid={`report-${entry.entry_id}`} className="min-h-11 px-2 text-xs font-medium text-text-secondary underline underline-offset-2">
          Report
        </button>
      )}
    </li>
  );
}
