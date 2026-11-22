import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "../../lib/cn";

export type SegmentedOption<T extends string> = { value: T; label: ReactNode; testId?: string; ariaLabel?: string };

/**
 * One segmented control for every view/filter switch (replaces four hand-built styles). It is a `tablist` of `tab`s with
 * roving focus and arrow-key movement, so screen readers and existing tests that look for `role="tab"` keep working.
 * `size="sm"` is a 36px control for dense headers; the default is 44px.
 */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = "md",
  stretch = false,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: SegmentedOption<T>[];
  label: string;
  size?: "md" | "sm";
  stretch?: boolean;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    const next = (i + dir + options.length) % options.length;
    refs.current[next]?.focus();
    onChange(options[next].value);
  };
  return (
    <div
      role="tablist"
      aria-label={label}
      className={cn(
        "inline-flex max-w-full gap-1 overflow-x-auto rounded-lg border border-border bg-surface-2/70 p-1",
        stretch && "flex w-full",
        className,
      )}
    >
      {options.map((o, i) => {
        const selected = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-label={o.ariaLabel}
            tabIndex={selected ? 0 : -1}
            data-testid={o.testId}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-md px-3 font-medium transition-colors duration-150",
              size === "sm" ? "min-h-8 text-[13px]" : "min-h-9 text-sm",
              stretch && "flex-1",
              selected ? "bg-surface text-text-primary shadow-subtle ring-1 ring-border-strong" : "text-text-secondary hover:text-text-primary",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
