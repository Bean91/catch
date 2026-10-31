export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex min-h-16 items-center justify-center rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-text-tertiary">
      {message}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex min-h-16 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-band-red/40 px-4 py-6 text-center text-sm text-text-secondary">
      <span>{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent"
        >
          Retry
        </button>
      )}
    </div>
  );
}
