import { NavLink } from "react-router-dom";
import { cn } from "../../lib/cn";

/** A row of related destinations under a page header. It scrolls inside itself on a phone instead of wrapping into a wall. */
export function PillNav({ items, label, className }: { items: { to: string; label: string; testId?: string }[]; label: string; className?: string }) {
  return (
    <nav aria-label={label} className={cn("-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0", className)}>
      <ul className="flex w-max gap-2 sm:w-auto sm:flex-wrap">
        {items.map((it) => (
          <li key={it.to}>
            <NavLink
              to={it.to}
              end
              data-testid={it.testId}
              className={({ isActive }) =>
                cn(
                  "inline-flex min-h-9 items-center rounded-full border px-3.5 text-[13px] font-medium transition-colors",
                  isActive ? "border-accent/50 bg-accent-soft text-accent" : "glass-subtle border-border bg-surface text-text-secondary hover:border-border-strong hover:text-text-primary",
                )
              }
            >
              {it.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
