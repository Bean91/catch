import type { SleepLastNight } from "../../lib/types";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";

function hours(seconds: number | null): string {
  if (seconds == null) return "—";
  return (seconds / 3600).toFixed(1);
}

// Sleep stages are a magnitude breakdown, not a status — deliberately kept off the
// green/yellow/red band palette (those are reserved for recovery/strain/load signals).
// Deep/REM/Light form one accent-hue depth ramp; Awake is a separate neutral (it isn't
// "lighter sleep," it's a different category) so it never gets mistaken for a 4th depth.
const STAGES: { key: keyof SleepLastNight; label: string; color: string }[] = [
  { key: "deep_seconds", label: "Deep", color: "var(--accent)" },
  { key: "rem_seconds", label: "REM", color: "color-mix(in oklab, var(--accent) 68%, transparent)" },
  { key: "light_seconds", label: "Light", color: "color-mix(in oklab, var(--accent) 32%, transparent)" },
  { key: "awake_seconds", label: "Awake", color: "var(--text-tertiary)" },
];

export function SleepCard({ sleep }: { sleep: SleepLastNight | null }) {
  if (!sleep || sleep.seconds == null) {
    return (
      <Card title="Sleep last night">
        <EmptyState message="No sleep data synced yet." />
      </Card>
    );
  }

  const total = sleep.seconds;
  const stageTotal = STAGES.reduce((sum, s) => sum + ((sleep[s.key] as number | null) ?? 0), 0);

  return (
    <Card title="Sleep last night">
      <div className="flex items-baseline gap-2">
        <span className="font-mono-nums text-3xl font-semibold text-text-primary">{hours(sleep.seconds)}h</span>
        <span className="text-sm text-text-tertiary">of {hours(sleep.need_seconds)}h need</span>
        {sleep.score != null && (
          <span className="ml-auto rounded-full bg-surface-2 px-2.5 py-1 text-xs font-medium text-text-secondary">
            score {sleep.score}
          </span>
        )}
      </div>
      {stageTotal > 0 && (
        <div className="mt-4">
          <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-2">
            {STAGES.map((s) => {
              const v = (sleep[s.key] as number | null) ?? 0;
              const pct = (v / total) * 100;
              return pct > 0 ? <div key={s.key} style={{ width: `${pct}%`, background: s.color }} /> : null;
            })}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-tertiary">
            {STAGES.map((s) => {
              const v = (sleep[s.key] as number | null) ?? 0;
              if (v <= 0) return null;
              return (
                <span key={s.key} className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                  {s.label} {(v / 3600).toFixed(1)}h
                </span>
              );
            })}
          </div>
        </div>
      )}
    </Card>
  );
}
