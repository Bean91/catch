import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "../../lib/cn";

export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="-ml-1 inline-flex min-h-9 items-center gap-1 self-start rounded-md px-1 text-sm font-medium text-text-tertiary transition-colors hover:text-text-primary"
    >
      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M12 5l-5 5 5 5" />
      </svg>
      {children}
    </Link>
  );
}

/**
 * Every page's title block: optional back link and eyebrow, the page's one `h1`, a subtitle, and actions that wrap below the
 * title on a narrow phone rather than squeezing it (text-wrap.spec at 320px). `compact` keeps the block to one line's height
 * where a chart below must not move (Trends: charts.spec's bottom-nav check).
 */
export function PageHeader({
  title,
  eyebrow,
  subtitle,
  back,
  actions,
  compact = false,
  titleClassName,
  className,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  subtitle?: ReactNode;
  back?: { to: string; label: string };
  actions?: ReactNode;
  compact?: boolean;
  titleClassName?: string;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-col gap-1", className)}>
      {back && <BackLink to={back.to}>{back.label}</BackLink>}
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          {eyebrow && <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.09em] text-accent">{eyebrow}</p>}
          <h1
            className={cn(
              "min-w-0 font-semibold tracking-tight text-text-primary wrap-anywhere",
              compact ? "text-xl leading-tight" : "text-2xl leading-tight sm:text-[1.75rem]",
              titleClassName,
            )}
          >
            {title}
          </h1>
          {subtitle && <div className="mt-1 text-sm text-text-secondary">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

/** A section heading between a page title and its cards (the h2 the pages were missing). */
export function SectionHeader({ title, action, description, id }: { title: ReactNode; action?: ReactNode; description?: ReactNode; id?: string }) {
  return (
    <div className="mt-2 flex flex-wrap items-end justify-between gap-x-3 gap-y-1">
      <div className="min-w-0">
        <h2 id={id} className="text-base font-semibold text-text-primary">
          {title}
        </h2>
        {description && <p className="mt-0.5 text-sm text-text-tertiary">{description}</p>}
      </div>
      {action}
    </div>
  );
}
