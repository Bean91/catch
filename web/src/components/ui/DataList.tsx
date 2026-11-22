import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

/** Label/value pairs as a real `<dl>`: a grid of small label over value, or `rows` for a two-column list. */
export function DefinitionList({
  items,
  layout = "grid",
  cols = "grid-cols-2 sm:grid-cols-3",
  mono = true,
  className,
}: {
  items: { label: ReactNode; value: ReactNode; key?: string }[];
  layout?: "grid" | "rows";
  cols?: string;
  mono?: boolean;
  className?: string;
}) {
  if (layout === "rows") {
    return (
      <dl className={cn("divide-y divide-border/70 text-sm", className)}>
        {items.map((it, i) => (
          <div key={it.key ?? i} className="flex min-w-0 items-baseline justify-between gap-4 py-2">
            <dt className="min-w-0 text-text-secondary">{it.label}</dt>
            <dd className={cn("min-w-0 text-right text-text-primary", mono && "font-mono-nums")}>{it.value}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <dl className={cn("grid gap-x-4 gap-y-3 text-sm", cols, className)}>
      {items.map((it, i) => (
        <div key={it.key ?? i} className="min-w-0">
          <dt className="text-xs text-text-tertiary">{it.label}</dt>
          <dd className={cn("mt-0.5 text-text-primary", mono && "font-mono-nums font-medium")}>{it.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A table that scrolls sideways inside itself (never the page), with a quiet header row and mono numeric cells. */
export function DataTable({ children, className, minWidth, label }: { children: ReactNode; className?: string; minWidth?: string; label?: string }) {
  return (
    <div className={cn("-mx-1 overflow-x-auto px-1", className)} role={label ? "region" : undefined} aria-label={label} tabIndex={label ? 0 : undefined}>
      <table
        className="w-full border-separate border-spacing-0 text-sm [&_tbody_tr:hover]:bg-surface-2/60 [&_tbody_tr:last-child_td]:border-b-0 [&_td]:border-b [&_td]:border-border/60 [&_td]:px-2.5 [&_td]:py-2 [&_th]:border-b [&_th]:border-border [&_th]:px-2.5 [&_th]:pb-2 [&_th]:text-left [&_th]:text-xs [&_th]:font-medium [&_th]:text-text-tertiary"
        style={minWidth ? { minWidth } : undefined}
      >
        {children}
      </table>
    </div>
  );
}
