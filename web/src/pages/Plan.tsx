import { useQueries, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { PhaseSheet } from "../components/calendar/PhaseSheet";
import { formatMinutes, phaseKindLabel } from "../components/calendar/labels";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { CardSkeleton } from "../components/ui/Skeleton";
import { fetchPhases, fetchPlanWeekSummary } from "../lib/api";
import { addDays, todayISO, weekRangeLabel, weekStart } from "../lib/dates";
import { formatShortDate } from "../lib/format";
import type { PlanPhase } from "../lib/types";

export function PlanPage() {
  const today = todayISO();
  const [sheet, setSheet] = useState<{ open: boolean; existing: PlanPhase | null }>({ open: false, existing: null });
  const phases = useQuery({ queryKey: ["phases"], queryFn: fetchPhases });
  const start = addDays(weekStart(today), -14);
  const weeks = Array.from({ length: 7 }, (_, i) => addDays(start, i * 7));
  const summaries = useQueries({ queries: weeks.map((w) => ({ queryKey: ["plan-weeks", w], queryFn: () => fetchPlanWeekSummary(w) })) });
  const flags = summaries.flatMap((s) => s.data?.review_flags ?? []).filter((f, i, a) => a.findIndex((x) => x.week_start === f.week_start) === i);
  const maxMin = Math.max(1, ...summaries.map((s) => Math.max(s.data?.planned.minutes ?? 0, s.data?.completed.minutes ?? 0, s.data?.targets.minutes ?? 0)));

  return (
    <div className="flex flex-col gap-4">
      <Link to="/calendar" className="inline-flex min-h-11 items-center text-sm text-text-secondary">
        ← Calendar
      </Link>
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-text-primary">Training plan</h1>
        <button type="button" onClick={() => setSheet({ open: true, existing: null })} className="min-h-11 rounded-full bg-accent px-4 text-sm font-medium text-accent-contrast">
          + Phase
        </button>
      </div>

      <Card title="Phases">
        {phases.isError ? (
          <ErrorState message="Couldn't load phases." onRetry={() => phases.refetch()} />
        ) : !phases.data ? (
          <CardSkeleton lines={2} />
        ) : phases.data.phases.length === 0 ? (
          <p className="text-sm text-text-tertiary">
            No phases yet. A phase is a block of weeks with its own goals and weekly targets — add one when you want the weekly numbers to be compared to something.
          </p>
        ) : (
          <ul className="flex flex-col gap-2" data-testid="phase-list">
            {phases.data.phases.map((p) => {
              const current = p.start_date <= today && today <= p.end_date;
              return (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => setSheet({ open: true, existing: p })}
                    className={`flex min-h-11 w-full flex-col gap-0.5 rounded-md border p-3 text-left ${current ? "border-accent/50 bg-accent/5" : "border-border"}`}
                  >
                    <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-text-primary">
                      {p.name}
                      {current && <span className="rounded-full border border-accent/30 px-2 py-0.5 text-xs font-normal text-accent">Now</span>}
                      {p.coach_approved && (
                        <span className="rounded-full border border-border px-2 py-0.5 text-xs font-normal text-text-secondary">
                          {p.edited_since_approval ? "Coach-approved · edited since" : "Coach-approved"}
                        </span>
                      )}
                    </span>
                    <span className="text-xs text-text-tertiary">
                      {phaseKindLabel(p.kind)} · {formatShortDate(p.start_date)} – {formatShortDate(p.end_date)}
                      {p.target_minutes_per_week ? ` · ${formatMinutes(p.target_minutes_per_week)}/week` : ""}
                    </span>
                    {p.goals && <span className="text-xs text-text-secondary">{p.goals}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card title="Weeks: planned and completed time">
        <ul className="flex flex-col gap-3" data-testid="plan-weeks">
          {weeks.map((w, i) => {
            const s = summaries[i].data;
            return (
              <li key={w} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between text-sm">
                  <span className={w === weekStart(today) ? "font-medium text-text-primary" : "text-text-secondary"}>
                    {weekRangeLabel(w)}
                    {w === weekStart(today) ? " · this week" : ""}
                  </span>
                  <span className="font-mono-nums text-text-secondary">{s ? `${formatMinutes(s.completed.minutes)} / ${formatMinutes(s.planned.minutes)}` : "…"}</span>
                </div>
                <div className="relative h-2 rounded-full bg-surface-2" role="img" aria-label={s ? `${formatMinutes(s.completed.minutes)} completed of ${formatMinutes(s.planned.minutes)} planned` : "loading"}>
                  {s && (
                    <>
                      <div className="absolute inset-y-0 left-0 rounded-full border border-accent/50 bg-accent/10" style={{ width: `${(s.planned.minutes / maxMin) * 100}%` }} />
                      <div className="absolute inset-y-0 left-0 rounded-full bg-text-secondary/70" style={{ width: `${(s.completed.minutes / maxMin) * 100}%` }} />
                      {s.targets.minutes != null && <div className="absolute -inset-y-0.5 border-l-2 border-dashed border-text-tertiary" style={{ left: `${(s.targets.minutes / maxMin) * 100}%` }} />}
                    </>
                  )}
                </div>
                {s && (
                  <p className="text-xs text-text-tertiary">
                    {s.completed.sessions} of {s.planned.sessions} sessions · strength {s.completed.strength_sessions} of {s.planned.strength_sessions}
                    {s.phase ? ` · ${s.phase.name}` : ""}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-xs text-text-tertiary">Filled bar: completed. Outlined bar: planned. Dashed line: weekly target. Planned time is an intention, not training done.</p>
      </Card>

      {flags.length > 0 && (
        <Card title="Worth a look">
          <ul className="flex flex-col gap-2" data-testid="review-flags">
            {flags.map((f) => (
              <li key={f.week_start} className="rounded-md border border-border bg-surface-2 p-3 text-sm text-text-secondary">
                {f.message}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <PhaseSheet open={sheet.open} onOpenChange={(o) => setSheet((s) => ({ ...s, open: o }))} existing={sheet.existing} defaultStart={weekStart(today)} />
    </div>
  );
}
