// Deliberately no red/"over" state anywhere (task's explicit "no shaming language" ask) —
// the fill just stops at 100% width and a small label states the raw numbers; going over or
// under a starting-point target is neither flagged nor colored differently.
export function MacroBar({ label, value, target, unit = "g", color = "var(--accent)" }: { label: string; value: number; target: number | null; unit?: string; color?: string }) {
  const pct = target ? Math.min(100, (value / target) * 100) : 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between text-sm">
        <span className="flex items-center gap-1.5 text-text-secondary">
          <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: color }} />
          {label}
        </span>
        <span className="font-mono-nums text-text-primary">
          {Math.round(value)}
          {target != null && <span className="text-text-tertiary"> / {Math.round(target)}{unit}</span>}
        </span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out-expo motion-reduce:transition-none"
          style={{ width: target ? `${pct}%` : "0%", background: `linear-gradient(90deg, color-mix(in oklab, ${color} 55%, transparent), ${color})` }}
        />
      </div>
    </div>
  );
}
