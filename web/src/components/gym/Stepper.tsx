/** Big tap targets (task Part A.4) — a labeled number input flanked by +/- buttons, each at
 * least 44px. Direct typing still works (a stepper-only input would be slower for a lifter
 * who already knows the exact number). */
export function Stepper({
  label,
  value,
  onChange,
  step,
  min = 0,
  suffix,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step: number;
  min?: number;
  suffix?: string;
}) {
  const round = (v: number) => Math.round(v * 100) / 100;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-text-tertiary">{label}</span>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => onChange(round(Math.max(min, value - step)))}
          aria-label={`Decrease ${label}`}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-border text-lg font-semibold text-text-primary transition-colors hover:border-accent"
        >
          −
        </button>
        <input
          type="number"
          inputMode="decimal"
          aria-label={label}
          value={value}
          onChange={(e) => onChange(round(Math.max(min, Number(e.target.value) || 0)))}
          className="h-11 min-w-0 flex-1 rounded-md border border-border bg-bg text-center font-mono-nums text-lg text-text-primary"
        />
        {suffix && <span className="text-sm text-text-tertiary">{suffix}</span>}
        <button
          type="button"
          onClick={() => onChange(round(value + step))}
          aria-label={`Increase ${label}`}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-border text-lg font-semibold text-text-primary transition-colors hover:border-accent"
        >
          +
        </button>
      </div>
    </div>
  );
}
