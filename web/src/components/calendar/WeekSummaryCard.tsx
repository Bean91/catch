import { Card } from "../ui/Card";
import type { PlanWeekSummary, PlanPhase } from "../../lib/types";
import { formatMinutes, phaseKindLabel, ZONES } from "./labels";

function Bar({ label, planned, completed, target, unit }: { label: string; planned: number; completed: number; target: number | null; unit: "min" | "n" }) {
  const max = Math.max(planned, completed, target ?? 0, 1);
  const fmt = (v: number) => (unit === "min" ? formatMinutes(v) : String(Math.round(v * 10) / 10));
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-text-secondary">{label}</span>
        <span className="font-mono-nums text-text-primary">
          {fmt(completed)} <span className="text-text-tertiary">of {fmt(planned)} planned</span>
        </span>
      </div>
      {/* Neutral bars only — nothing is coloured as ahead/behind. The dashed marker is the target. */}
      <div className="relative h-2 rounded-full bg-surface-2" role="img" aria-label={`${label}: ${fmt(completed)} completed, ${fmt(planned)} planned${target != null ? `, target ${fmt(target)}` : ""}`}>
        <div className="absolute inset-y-0 left-0 rounded-full border border-accent/50 bg-accent/10" style={{ width: `${(planned / max) * 100}%` }} />
        <div className="absolute inset-y-0 left-0 rounded-full bg-text-secondary/70" style={{ width: `${(completed / max) * 100}%` }} />
        {target != null && <div className="absolute -inset-y-0.5 w-0 border-l-2 border-dashed border-text-tertiary" style={{ left: `${(target / max) * 100}%` }} />}
      </div>
    </div>
  );
}

export function PhaseBanner({ phase }: { phase: PlanPhase }) {
  return (
    <div data-testid="phase-banner" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm">
      <span className="font-medium text-text-primary">{phase.name}</span>
      <span className="text-text-tertiary">{phaseKindLabel(phase.kind)}</span>
      {phase.coach_approved && (
        <span className="rounded-full border border-border px-2 py-0.5 text-xs text-text-secondary">
          {phase.edited_since_approval ? "Coach-approved · edited since" : "Coach-approved"}
        </span>
      )}
    </div>
  );
}

export function WeekSummaryCard({ s }: { s: PlanWeekSummary }) {
  const t = s.targets;
  return (
    <Card title="This week: planned and completed" className="" >
      <div className="flex flex-col gap-3" data-testid="week-summary">
        <Bar label="Time" planned={s.planned.minutes} completed={s.completed.minutes} target={t.minutes} unit="min" />
        <Bar label="Sessions" planned={s.planned.sessions} completed={s.completed.sessions} target={t.sessions} unit="n" />
        {(t.strength_sessions != null || s.planned.strength_sessions > 0 || s.completed.strength_sessions > 0) && (
          <Bar label="Strength sessions" planned={s.planned.strength_sessions} completed={s.completed.strength_sessions} target={t.strength_sessions} unit="n" />
        )}
        <p className="text-xs text-text-tertiary">
          Planned figures are intentions; only completed workouts count as training. Targets from {t.source === "phase" ? "the current phase" : "your settings"}.
          {s.planned.skipped_sessions > 0 ? ` ${s.planned.skipped_sessions} skipped.` : ""}
        </p>
        {t.zone_pct && Object.keys(t.zone_pct).length > 0 && (
          <div className="text-sm text-text-secondary" data-testid="zone-targets">
            <p className="mb-1 font-medium text-text-primary">Intensity split</p>
            {!s.completed.zones_available && <p className="text-xs text-text-tertiary">No completed training to compare yet this week.</p>}
            <ul className="grid grid-cols-1 gap-0.5">
              {ZONES.filter((z) => t.zone_pct?.[z]).map((z) => {
                const b = t.zone_pct![z];
                const actual = s.completed.zone_pct[z];
                return (
                  <li key={z} className="flex justify-between">
                    <span>{z}</span>
                    <span className="font-mono-nums">
                      {actual != null ? `${actual}%` : "—"} <span className="text-text-tertiary">target {b.min != null ? `≥${b.min}%` : ""}
                      {b.min != null && b.max != null ? " " : ""}
                      {b.max != null ? `≤${b.max}%` : ""}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {s.review_flags.length > 0 && (
          <ul className="flex flex-col gap-2" data-testid="review-flags">
            {s.review_flags.map((f) => (
              <li key={f.week_start} className="rounded-md border border-border bg-surface-2 p-3 text-sm text-text-secondary">
                <span className="mb-1 block text-xs font-medium text-text-primary">Worth a look</span>
                {f.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
