import { cn } from "../../lib/cn";

/** A shimmering placeholder; reduced motion freezes the shimmer (index.css), leaving a quiet block. */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "animate-shimmer rounded-md bg-[linear-gradient(90deg,var(--surface-2)_25%,var(--surface-3)_50%,var(--surface-2)_75%)] bg-[length:200%_100%]",
        className,
      )}
    />
  );
}

export function CardSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="w-full rounded-lg border border-border bg-surface p-4 shadow-[var(--highlight),var(--shadow-1)] sm:p-5" aria-busy="true" aria-label="Loading">
      <Skeleton className="mb-4 h-3.5 w-28" />
      <Skeleton className="mb-3 h-8 w-36" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={cn("mb-2 h-3", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

/** A chart-shaped placeholder at the chart's own height, so nothing jumps when the data arrives. */
export function ChartSkeleton({ height = 220 }: { height?: number }) {
  return <div style={{ height }}><Skeleton className="h-full w-full rounded-md" /></div>;
}
