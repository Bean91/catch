/**
 * Planned versus completed on one track (calendar week summary, the training plan's weeks). Deliberately neutral — nothing is coloured
 * as ahead or behind (DESIGN.md "Session states, no shaming"): planned is an outlined accent track, completed a filled bar over it,
 * and a target is a dashed marker. The spoken label carries every number.
 */
export function PlanBar({ planned, completed, target, max, label, height = 8 }: { planned: number; completed: number; target?: number | null; max: number; label: string; height?: number }) {
  const m = Math.max(max, 1);
  const pct = (v: number) => `${Math.min((v / m) * 100, 100)}%`;
  return (
    <div className="relative rounded-full bg-surface-2" style={{ height }} role="img" aria-label={label}>
      <div className="absolute inset-y-0 left-0 rounded-full border border-accent/45 bg-accent-soft" style={{ width: pct(planned) }} />
      <div className="absolute inset-y-0 left-0 rounded-full bg-[linear-gradient(90deg,color-mix(in_oklab,var(--accent)_70%,transparent),var(--accent))]" style={{ width: pct(completed) }} />
      {target != null && <div className="absolute -inset-y-1 w-0 border-l-2 border-dashed border-text-secondary" style={{ left: pct(target) }} />}
    </div>
  );
}
