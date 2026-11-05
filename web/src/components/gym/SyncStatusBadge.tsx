import type { SyncStatus } from "../../lib/gymSync";

/** Subtle by design (task Part A.1) — never a modal, never blocks logging. A pending count
 * alone ("2 sets to sync") rather than a raw "offline" label, since the set is never at
 * risk either way; only the *sync*, not the save, is pending. */
export function SyncStatusBadge({ status }: { status: SyncStatus }) {
  if (status.syncing) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-text-tertiary font-mono-nums">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
        Syncing…
      </span>
    );
  }
  if (status.pendingCount > 0) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-text-tertiary font-mono-nums">
        <span className="h-1.5 w-1.5 rounded-full bg-band-yellow" aria-hidden />
        {status.pendingCount} set{status.pendingCount === 1 ? "" : "s"} to sync
      </span>
    );
  }
  if (status.lastError) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-band-red-text font-mono-nums" title={status.lastError}>
        <span className="h-1.5 w-1.5 rounded-full bg-band-red" aria-hidden />
        Sync retrying
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-text-tertiary font-mono-nums">
      <span className="h-1.5 w-1.5 rounded-full bg-band-green" aria-hidden />
      Synced
    </span>
  );
}
