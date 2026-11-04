// Deliberately no red/"over" state anywhere (task's explicit "no shaming language" ask) —
// the fill just stops at 100% width and a small label states the raw numbers; going over or
// under a starting-point target is neither flagged nor colored differently.
export function MacroBar({ label, value, target, unit = "g" }: { label: string; value: number; target: number | null; unit?: string }) {
  const pct = target ? Math.min(100, (value / target) * 100) : 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-text-secondary">{label}</span>
        <span className="font-mono-nums text-text-primary">
          {Math.round(value)}
          {target != null && <span className="text-text-tertiary"> / {Math.round(target)}{unit}</span>}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2">
        <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: target ? `${pct}%` : "0%" }} />
      </div>
    </div>
  );
}
