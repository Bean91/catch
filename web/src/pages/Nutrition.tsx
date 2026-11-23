import { useQuery, useQueryClient } from "@tanstack/react-query";
import { buttonClass } from "../components/ui/Button";
import { Notice } from "../components/ui/Notice";
import { PageHeader } from "../components/ui/PageHeader";
import { Segmented } from "../components/ui/Segmented";
import { dayLabel } from "../lib/dates";
import { lazy, Suspense, useState, useSyncExternalStore } from "react";
import { AddFoodDialog } from "../components/nutrition/AddFoodDialog";
import { MacroBar } from "../components/nutrition/MacroBar";
import { MealSection } from "../components/nutrition/MealSection";
import { WeekView } from "../components/nutrition/WeekView";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { CardSkeleton } from "../components/ui/Skeleton";
import { copyDayLogs, fetchDaySummary, fetchWeekSummary } from "../lib/api";
import { localDateString } from "../lib/format";
import { activeTimeZone, subscribeActiveZone } from "../lib/localTime";
import { MEALS, type Meal } from "../lib/types";

import { useVisionAvailable } from "../lib/useVisionAvailable";

const PhotoEstimateDialog = lazy(() => import("../components/nutrition/PhotoEstimateDialog").then((m) => ({ default: m.PhotoEstimateDialog })));

function shiftLocalDate(dateStr: string, days: number): string {
  const d = new Date(dateStr + "T00:00:00");
  d.setDate(d.getDate() + days);
  return localDateString(d);
}

function defaultMealForNow(): Meal {
  const hour = new Date().getHours();
  if (hour < 10) return "breakfast";
  if (hour < 15) return "lunch";
  if (hour < 20) return "dinner";
  return "snack";
}

export function NutritionPage() {
  const [view, setView] = useState<"day" | "week">("day");
  // Follow "today" (which moves when the account's zone loads, or at midnight) until the athlete picks a day themselves; the
  // first render can run before /api/me has set the account zone, and freezing that day showed "Jump to today" on today.
  useSyncExternalStore(subscribeActiveZone, activeTimeZone);
  const [picked, setPicked] = useState<string | null>(null);
  const [addMeal, setAddMeal] = useState<Meal | null>(null);
  const [photoOpen, setPhotoOpen] = useState(false);
  const queryClient = useQueryClient();

  const today = localDateString();
  const date = picked ?? today;
  const setDate = (next: string | ((d: string) => string)) => {
    const value = typeof next === "function" ? next(date) : next;
    setPicked(value === today ? null : value);
  };
  const yesterday = shiftLocalDate(date, -1);

  const daySummary = useQuery({ queryKey: ["nutrition-day", date], queryFn: () => fetchDaySummary(date) });
  const weekSummary = useQuery({
    queryKey: ["nutrition-week", shiftLocalDate(date, -6), date],
    queryFn: () => fetchWeekSummary(shiftLocalDate(date, -6), date),
  });
  // Hidden rather than merely erroring on tap — the photo-estimate entry point itself is absent
  // unless the active AI provider is set up and can read images, not just a backend 422.
  const photoEstimateAvailable = useVisionAvailable();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["nutrition-day"] });
    queryClient.invalidateQueries({ queryKey: ["nutrition-week"] });
  };

  const copyYesterday = async (meal: Meal) => {
    await copyDayLogs(yesterday, date, meal);
    invalidate();
  };

  const nowIso = () => {
    const d = new Date();
    if (date !== today) {
      // Logging onto a non-today day: keep the current time-of-day but move the calendar date,
      // so "add breakfast for yesterday" doesn't land on today (the server's own default).
      const picked = new Date(date + "T00:00:00");
      d.setFullYear(picked.getFullYear(), picked.getMonth(), picked.getDate());
    }
    return d.toISOString();
  };

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        eyebrow="Health"
        title="Nutrition"
        actions={
          <Segmented
            label="View"
            size="sm"
            value={view}
            onChange={setView}
            options={[
              { value: "day", label: "Day" },
              { value: "week", label: "Week" },
            ]}
          />
        }
      />

      {view === "day" ? (
        <>
          <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface/60 p-1">
            <button
              type="button"
              onClick={() => setDate((d) => shiftLocalDate(d, -1))}
              aria-label="Previous day"
              className="flex min-h-11 min-w-11 items-center justify-center rounded-md text-xl text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary"
            >
              ‹
            </button>
            <div className="flex flex-col items-center">
              <span className="text-sm font-semibold text-text-primary">{date === today ? "Today" : dayLabel(date)}</span>
              {date !== today && (
                <button type="button" onClick={() => setDate(today)} className="text-xs text-accent">
                  Jump to today
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={() => setDate((d) => shiftLocalDate(d, 1))}
              aria-label="Next day"
              disabled={date >= today}
              className="flex min-h-11 min-w-11 items-center justify-center rounded-md text-xl text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary disabled:opacity-30"
            >
              ›
            </button>
          </div>

          {weekSummary.data?.under_fuelling.flag && (
            <Notice tone="accent">{weekSummary.data.under_fuelling.explanation}</Notice>
          )}

          {daySummary.isLoading ? (
            <CardSkeleton lines={4} />
          ) : daySummary.isError || !daySummary.data ? (
            <ErrorState message="Couldn't load this day." onRetry={() => daySummary.refetch()} />
          ) : (
            <>
              <Card title="Today's intake vs. targets">
                <div className="flex flex-col gap-3">
                  <MacroBar label="Calories" value={daySummary.data.intake.kcal} target={daySummary.data.targets.kcal_target} unit="kcal" color="var(--accent)" />
                  <MacroBar label="Protein" value={daySummary.data.intake.protein} target={daySummary.data.targets.protein_g} color="var(--metric-rate)" />
                  <MacroBar label="Carbs" value={daySummary.data.intake.carbs} target={daySummary.data.targets.carb_g} color="var(--metric-power)" />
                  <MacroBar label="Fat" value={daySummary.data.intake.fat} target={daySummary.data.targets.fat_g} color="var(--metric-pace)" />
                </div>
                <p className="mt-3 text-xs text-text-tertiary">
                  {daySummary.data.targets.protein_g == null
                    ? daySummary.data.targets.explanation
                    : "Starting points, based on your training load — adjust with a coach or dietitian."}
                </p>
                {photoEstimateAvailable && (
                  <button type="button" onClick={() => setPhotoOpen(true)} className={`mt-4 ${buttonClass("subtle", "sm")}`}>
                    <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round">
                      <path d="M3 7.5A1.5 1.5 0 014.5 6h2l1.2-1.8h4.6L13.5 6h2A1.5 1.5 0 0117 7.5v7a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 013 14.5z" />
                      <circle cx="10" cy="11" r="2.8" />
                    </svg>
                    Estimate a meal from a photo
                  </button>
                )}
              </Card>

              <Card title="Meals">
                <div className="flex flex-col gap-4">
                  {MEALS.map((meal) => (
                    <MealSection
                      key={meal}
                      meal={meal}
                      logs={daySummary.data!.logs.filter((l) => l.meal === meal)}
                      onAdd={() => setAddMeal(meal)}
                      onChanged={invalidate}
                      onCopyYesterday={() => copyYesterday(meal)}
                      canCopyYesterday
                    />
                  ))}
                </div>
              </Card>
            </>
          )}
        </>
      ) : weekSummary.isLoading ? (
        <CardSkeleton lines={5} />
      ) : weekSummary.isError || !weekSummary.data ? (
        <ErrorState message="Couldn't load this week." onRetry={() => weekSummary.refetch()} />
      ) : (
        <WeekView week={weekSummary.data} proteinTargetG={daySummary.data?.targets.protein_g ?? null} />
      )}

      {addMeal && (
        <AddFoodDialog
          open
          meal={addMeal}
          ts={nowIso()}
          onClose={() => setAddMeal(null)}
          onLogged={invalidate}
        />
      )}

      <Suspense fallback={null}>
        {photoOpen && (
          <PhotoEstimateDialog open defaultMeal={defaultMealForNow()} ts={nowIso()} onClose={() => setPhotoOpen(false)} onLogged={invalidate} />
        )}
      </Suspense>

      <p className="text-center text-xs text-text-tertiary">
        Contains data from{" "}
        <a href="https://world.openfoodfacts.org" target="_blank" rel="noreferrer" className="underline">
          Open Food Facts
        </a>
        , available under the{" "}
        <a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noreferrer" className="underline">
          Open Database License
        </a>
        .
      </p>
    </div>
  );
}
