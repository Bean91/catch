import type { SleepLastNight } from "../../lib/types";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import { StackedBar } from "../charts/StackedBar";

function hours(seconds: number | null): string {
  if (seconds == null) return "—";
  return (seconds / 3600).toFixed(1);
}

// Sleep stages are a magnitude breakdown, not a status — deliberately kept off the
// green/yellow/red band palette (those are reserved for recovery/strain/load signals).
// Deep/REM/Light form one accent-hue depth ramp; Awake is a separate neutral (it isn't
// "lighter sleep," it's a different category) so it never gets mistaken for a 4th depth.
const STAGES: { key: keyof SleepLastNight; label: string; color: string }[] = [
  { key: "deep_seconds", label: "Deep", color: "var(--metric-sleep)" },
  { key: "rem_seconds", label: "REM", color: "color-mix(in oklab, var(--metric-sleep) 66%, var(--surface-2))" },
  { key: "light_seconds", label: "Light", color: "color-mix(in oklab, var(--metric-sleep) 36%, var(--surface-2))" },
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
          <StackedBar
            height={10}
            legend
            segments={STAGES.map((st) => ({ key: st.key, label: st.label, value: (sleep[st.key] as number | null) ?? 0, color: st.color, detail: `${(((sleep[st.key] as number | null) ?? 0) / 3600).toFixed(1)}h` }))}
            summary={`Sleep stages: ${STAGES.map((st) => `${st.label} ${(((sleep[st.key] as number | null) ?? 0) / 3600).toFixed(1)} hours`).join(", ")}`}
          />
        </div>
      )}
    </Card>
  );
}
