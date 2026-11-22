import type { ReactNode } from "react";

/**
 * Nothing to show yet. `message` alone is the compact one-line version every page already uses; `title`/`action` make it a
 * fuller invitation where the next step is obvious ("Plan a session").
 */
export function EmptyState({ message, title, action, icon }: { message: ReactNode; title?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex min-h-16 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border-strong/70 bg-surface-2/30 px-4 py-6 text-center text-sm text-text-tertiary">
      {icon && (
        <span aria-hidden className="mb-1 flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-text-secondary">
          {icon}
        </span>
      )}
      {title && <p className="font-medium text-text-primary">{title}</p>}
      <span className="max-w-sm">{message}</span>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/** Something failed. The message's parent element also holds Retry (settings-perf.spec relies on that shape). */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex min-h-16 flex-col items-center justify-center gap-3 rounded-md border border-band-red/30 bg-band-red/5 px-4 py-6 text-center text-sm text-text-secondary">
      <span className="flex min-w-0 max-w-full items-center gap-2 wrap-anywhere">
        <span aria-hidden className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-band-red/15 text-[11px] font-semibold text-band-red-text">
          !
        </span>
        {message}
      </span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="min-h-11 rounded-md border border-border bg-surface-2 px-4 text-sm font-medium text-text-primary transition-colors hover:border-border-strong hover:bg-surface-3"
        >
          Retry
        </button>
      )}
    </div>
  );
}
