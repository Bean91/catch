import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/**
 * One metric: a small label, the value in the mono figures face, its unit, and optional context (a delta, a baseline, a
 * sparkline). `accent` is a metric colour token name (e.g. "var(--metric-hr)") shown as a short bar beside the label — identity,
 * never meaning, so the label always carries the name too.
 */
export function StatTile({
  label,
  value,
  unit,
  sub,
  accent,
  size = "md",
  info,
  children,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  sub?: ReactNode;
  accent?: string;
  size?: "sm" | "md" | "lg";
  info?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="flex items-center gap-1.5 text-xs font-medium text-text-tertiary">
        {accent && <span aria-hidden className="h-2.5 w-1 rounded-full" style={{ background: accent }} />}
        <span className="min-w-0 truncate">{label}</span>
        {info}
      </div>
      <div className="mt-1 flex items-baseline gap-1">
        <span
          className={cn(
            "font-mono-nums font-semibold tracking-tight text-text-primary",
            size === "lg" ? "text-3xl" : size === "md" ? "text-xl" : "text-base",
          )}
        >
          {value}
        </span>
        {unit && <span className="text-xs text-text-tertiary">{unit}</span>}
      </div>
      {sub && <div className="mt-0.5 text-xs text-text-tertiary">{sub}</div>}
      {children}
    </div>
  );
}

/** A responsive grid of StatTiles with hairline dividers. */
export function StatGrid({ children, cols = "grid-cols-2 sm:grid-cols-3", className }: { children: ReactNode; cols?: string; className?: string }) {
  return <div className={cn("grid gap-x-4 gap-y-4", cols, className)}>{children}</div>;
}
