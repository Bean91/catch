import { cn } from "../../lib/cn";

/** An On/Off switch that says "On"/"Off" as a word beside the track (DESIGN.md: never colour alone). */
export function Switch({
  checked,
  onChange,
  label,
  disabled,
  testId,
  showWord = true,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
  testId?: string;
  showWord?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      data-testid={testId}
      onClick={() => onChange(!checked)}
      className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-md px-1 text-sm font-medium text-text-secondary disabled:opacity-45"
    >
      <span
        aria-hidden
        className={cn(
          "relative inline-flex h-6 w-10 items-center rounded-full border transition-colors duration-150",
          checked ? "border-accent bg-accent" : "border-border-strong bg-surface-3",
        )}
      >
        <span
          className={cn(
            "absolute h-4.5 w-4.5 rounded-full shadow-subtle transition-transform duration-150 ease-out",
            checked ? "translate-x-[18px] bg-accent-contrast" : "translate-x-[3px] bg-text-secondary",
          )}
        />
      </span>
      {showWord && <span className="w-7 text-left">{checked ? "On" : "Off"}</span>}
    </button>
  );
}
