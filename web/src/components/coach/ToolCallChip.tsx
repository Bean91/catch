import { useState } from "react";

export function ToolCallChip({
  label,
  output,
  isError,
  pending,
}: {
  label: string;
  output: unknown;
  isError: boolean;
  pending: boolean;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="my-1 max-w-full">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={pending}
        className={`inline-flex min-h-8 items-center gap-1.5 rounded-full border px-3 text-xs transition-colors ${
          isError
            ? "border-band-red/40 text-band-red-text"
            : "border-border text-text-tertiary hover:border-accent/40 hover:text-text-secondary"
        }`}
      >
        <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${pending ? "animate-pulse bg-accent" : isError ? "bg-band-red" : "bg-text-tertiary"}`} />
        {label}
        {!pending && (
          <svg viewBox="0 0 24 24" fill="none" className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden>
            <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>
      {open && !pending && (
        <pre className="font-mono-nums mt-1.5 max-h-64 overflow-auto rounded-md border border-border bg-surface-2 p-2.5 text-xs text-text-secondary">
          {JSON.stringify(output, null, 2)}
        </pre>
      )}
    </div>
  );
}
