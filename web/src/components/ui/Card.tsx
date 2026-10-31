import type { ReactNode } from "react";

export function Card({
  title,
  action,
  children,
  onClick,
  className = "",
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  onClick?: () => void;
  className?: string;
}) {
  const Comp = onClick ? "button" : "div";
  return (
    <Comp
      onClick={onClick}
      className={`w-full rounded-lg border border-border bg-surface p-4 text-left sm:p-5 ${
        onClick ? "cursor-pointer transition-colors hover:border-accent/40 focus-visible:outline-none" : ""
      } ${className}`}
    >
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h3 className="text-sm font-medium text-text-secondary">{title}</h3>}
          {action}
        </div>
      )}
      {children}
    </Comp>
  );
}
