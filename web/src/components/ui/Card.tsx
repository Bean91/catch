import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

export type CardTone = "default" | "raised" | "inset" | "accent";
/** Mobile-only glass material (DESIGN.md "Mobile glass"); inert on desktop. Omitted, the tone decides. */
export type CardMaterial = "glass" | "solid" | "subtle" | "none";

const MATERIAL: Record<CardMaterial, string> = { glass: "glass-secondary", solid: "glass-solid", subtle: "glass-subtle", none: "" };

const TONE: Record<CardTone, string> = {
  default: "border-border bg-surface shadow-[var(--highlight),var(--shadow-1)]",
  raised: "border-border-strong/70 bg-surface shadow-[var(--highlight),var(--shadow-2)]",
  inset: "border-border/70 bg-surface-2/60",
  accent: "border-accent/30 bg-[linear-gradient(160deg,var(--accent-soft),transparent_60%),var(--surface)] shadow-[var(--highlight),var(--shadow-1)]",
};

/**
 * The surface every section sits on. `title` is always an `h3` (tests and screen readers find sections by it); `eyebrow` is a small
 * label above it; `action` sits at the right of the title row. The root keeps `rounded-lg` (gym-offline's piece-photo spec finds a
 * card by that class). With `onClick` the whole card is a button. `material="solid"` is for a card holding a chart, map or table: on a
 * phone it stays near-opaque so gridlines and series colours sit on the surface they were validated against.
 */
export function Card({
  title,
  eyebrow,
  icon,
  action,
  children,
  onClick,
  tone = "default",
  material,
  padding = "md",
  className = "",
  testId,
}: {
  title?: ReactNode;
  eyebrow?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  onClick?: () => void;
  tone?: CardTone;
  material?: CardMaterial;
  padding?: "sm" | "md" | "none";
  className?: string;
  testId?: string;
}) {
  const Comp = onClick ? "button" : "div";
  return (
    <Comp
      onClick={onClick}
      data-testid={testId}
      data-tone={tone}
      className={cn(
        "w-full min-w-0 rounded-lg border text-left",
        TONE[tone],
        MATERIAL[material ?? (tone === "inset" ? "subtle" : "glass")],
        padding === "md" ? "p-4 sm:p-5" : padding === "sm" ? "p-3 sm:p-4" : "",
        onClick && "cursor-pointer transition-[border-color,transform] duration-150 hover:border-accent/40 active:scale-[0.995]",
        className,
      )}
    >
      {(title || action || eyebrow) && (
        <div className="mb-3.5 flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            {icon && (
              <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-2 text-text-secondary">
                {icon}
              </span>
            )}
            <div className="min-w-0">
              {eyebrow && <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">{eyebrow}</p>}
              {title && <h3 className="text-[0.9375rem] font-semibold leading-snug text-text-primary">{title}</h3>}
            </div>
          </div>
          {action}
        </div>
      )}
      {children}
    </Comp>
  );
}
