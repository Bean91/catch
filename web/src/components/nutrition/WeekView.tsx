import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import { formatShortDate } from "../../lib/format";
import type { WeekSummary } from "../../lib/types";

// Neutral bars only — intake and expenditure are shown side by side so the athlete can read
// the relationship themselves; nothing here colors a day red or "over" (task's explicit
// no-shaming rule applies here as much as to the day view).
export function WeekView({ week, proteinTargetG }: { week: WeekSummary; proteinTargetG: number | null }) {
  const loggedDays = week.days.filter((d) => d.has_log);
  const maxKcal = Math.max(1, ...week.days.map((d) => Math.max(d.intake_kcal, d.expenditure_kcal ?? 0)));

  return (
    <div className="flex flex-col gap-4">
      {week.under_fuelling.flag && (
        <Card className="border-accent/40">
          <p className="text-sm text-text-primary">{week.under_fuelling.explanation}</p>
        </Card>
      )}

      <Card title="Energy in vs. out">
        {loggedDays.length === 0 ? (
          <EmptyState message="No logged days yet this week." />
        ) : (
          <div className="flex flex-col gap-3">
            {week.days.map((d) => (
              <div key={d.date} className="flex items-center gap-3">
                <span className="w-16 shrink-0 text-xs text-text-tertiary">{formatShortDate(d.date)}</span>
                <div className="flex flex-1 flex-col gap-1">
                  <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: d.has_log ? `${Math.min(100, (d.intake_kcal / maxKcal) * 100)}%` : "0%" }}
                    />
                  </div>
                  {d.expenditure_kcal != null && (
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2/60">
                      <div className="h-full rounded-full bg-text-tertiary/50" style={{ width: `${Math.min(100, (d.expenditure_kcal / maxKcal) * 100)}%` }} />
                    </div>
                  )}
                </div>
                <span className="w-20 shrink-0 text-right font-mono-nums text-xs text-text-tertiary">
                  {d.has_log ? `${Math.round(d.intake_kcal)}` : "—"}
                  {d.expenditure_kcal != null ? ` / ${Math.round(d.expenditure_kcal)}` : ""}
                </span>
              </div>
            ))}
            <p className="text-xs text-text-tertiary">Solid bar = intake. Thin bar below = Garmin's total burn for that day.</p>
          </div>
        )}
      </Card>

      <Card title="Protein consistency">
        {loggedDays.length === 0 ? (
          <EmptyState message="No logged days yet this week." />
        ) : (
          <div className="flex flex-col gap-3">
            {week.days.map((d) => (
              <div key={d.date} className="flex items-center gap-3">
                <span className="w-16 shrink-0 text-xs text-text-tertiary">{formatShortDate(d.date)}</span>
                <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: d.has_log && proteinTargetG ? `${Math.min(100, (d.protein / proteinTargetG) * 100)}%` : "0%" }}
                  />
                </div>
                <span className="w-20 shrink-0 text-right font-mono-nums text-xs text-text-tertiary">{d.has_log ? `${Math.round(d.protein)}g` : "—"}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
