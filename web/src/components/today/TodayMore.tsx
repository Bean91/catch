import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fetchPbs, fetchPlanWeekSummary, fetchRecommendations, fetchSeries, fetchVolume, fetchWorkouts } from "../../lib/api";
import { addDays, todayISO, weekStart } from "../../lib/dates";
import { formatDistance, formatDuration, formatShortDate, formatSplit } from "../../lib/format";
import { ZONE_NAMES } from "../../lib/types";
import { CalendarHeatmap } from "../charts/CalendarHeatmap";
import { PlanBar } from "../charts/PlanBar";
import { ValueBars } from "../charts/ValueBars";
import { formatMinutes } from "../calendar/labels";
import { WorkoutRow } from "../workouts/WorkoutRow";
import { Card } from "../ui/Card";
import { EmptyState, ErrorState } from "../ui/EmptyState";
import { Skeleton } from "../ui/Skeleton";

/**
 * The dashboard's second half (session 35), loaded as its own chunk after the readiness hero so the eager bundle doesn't grow. Every
 * card has its own query, skeleton and error state, so one slow endpoint never holds up the rest.
 */
export default function TodayMore() {
  return (
    <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
      <ThisWeekCard />
      <ConsistencyCard />
      <RecentTrainingCard />
      <div className="flex flex-col gap-4 lg:gap-5">
        <TopInsightCard />
        <PbsCard />
      </div>
    </div>
  );
}

function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

function ThisWeekCard() {
  const week = weekStart(todayISO());
  const plan = useQuery({ queryKey: ["plan-week", week], queryFn: () => fetchPlanWeekSummary(week) });
  const volume = useQuery({ queryKey: ["volume", 8], queryFn: () => fetchVolume(8) });
  const bars = useMemo(
    () =>
      (volume.data ?? []).map((w) => ({
        key: w.week_start,
        label: formatShortDate(w.week_start).replace(/^(\w+) /, "$1 "),
        title: `Week of ${formatShortDate(w.week_start)}`,
        value: ZONE_NAMES.reduce((a, z) => a + w.zones[z], 0) / 3600,
        emphasis: w.week_start === week,
      })),
    [volume.data, week],
  );
  const s = plan.data;
  return (
    <Card material="solid" title="This week" action={<Link to="/calendar" className="text-sm font-medium text-accent hover:underline">Plan</Link>}>
      {plan.isLoading ? (
        <Loading rows={2} />
      ) : plan.isError || !s ? (
        <ErrorState message="Couldn't load this week's plan." onRetry={() => plan.refetch()} />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-mono-nums text-2xl font-semibold text-text-primary">{formatMinutes(s.completed.minutes)}</span>
            <span className="text-sm text-text-tertiary">
              of {formatMinutes(s.planned.minutes)} planned · {s.completed.sessions} of {s.planned.sessions} sessions
            </span>
          </div>
          <PlanBar
            planned={s.planned.minutes}
            completed={s.completed.minutes}
            target={s.targets.minutes}
            max={Math.max(s.planned.minutes, s.completed.minutes, s.targets.minutes ?? 0)}
            label={`${formatMinutes(s.completed.minutes)} completed of ${formatMinutes(s.planned.minutes)} planned this week`}
          />
        </div>
      )}
      <div className="mt-4 border-t border-border pt-3">
        <p className="mb-1 text-xs font-medium text-text-tertiary">Training hours, last 8 weeks</p>
        {volume.isLoading ? (
          <Skeleton className="h-[130px] w-full" />
        ) : volume.isError ? (
          <ErrorState message="Couldn't load training volume." onRetry={() => volume.refetch()} />
        ) : bars.every((b) => b.value === 0) ? (
          <EmptyState message="No training recorded in the last 8 weeks." />
        ) : (
          <ValueBars bars={bars} format={(v) => `${v.toFixed(v < 10 ? 1 : 0)}h`} zeroBased height={130} showValues={false} ariaLabel={`Weekly training hours: ${bars.map((b) => `${b.title} ${b.value.toFixed(1)} hours`).join(", ")}`} />
        )}
      </div>
    </Card>
  );
}

function ConsistencyCard() {
  const to = todayISO();
  const from = addDays(weekStart(to), -7 * 25);
  const q = useQuery({ queryKey: ["series", "strain", from, to, 200], queryFn: () => fetchSeries(["strain"], from, to, 200) });
  const days = useMemo(() => {
    const out: Record<string, number | null> = {};
    for (const p of q.data?.series.strain?.points ?? []) out[p.date] = p.value;
    return out;
  }, [q.data]);
  return (
    <Card material="solid" title="Consistency" action={<Link to="/trends?metric=strain" className="text-sm font-medium text-accent hover:underline">Trends</Link>}>
      {q.isLoading ? (
        <Skeleton className="h-[150px] w-full" />
      ) : q.isError ? (
        <ErrorState message="Couldn't load your training history." onRetry={() => q.refetch()} />
      ) : (
        <>
          <CalendarHeatmap days={days} weeks={26} format={(v) => `strain ${v.toFixed(1)}`} label="Daily strain, last 26 weeks" />
          <p className="mt-2 text-xs text-text-tertiary">Each square is a day, shaded by that day's strain. Outlined squares had none.</p>
        </>
      )}
    </Card>
  );
}

function RecentTrainingCard() {
  const q = useQuery({ queryKey: ["workouts-recent"], queryFn: () => fetchWorkouts({}) });
  const items = q.data?.items.slice(0, 4) ?? [];
  return (
    <Card title="Recent training" action={<Link to="/workouts" className="text-sm font-medium text-accent hover:underline">All</Link>}>
      {q.isLoading ? (
        <Loading rows={4} />
      ) : q.isError ? (
        <ErrorState message="Couldn't load recent workouts." onRetry={() => q.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState message="No workouts yet — connect a source in Settings." />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((w) => (
            <li key={w.id}>
              <WorkoutRow workout={w} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const PB_ORDER = ["500m", "2000m", "6000m", "60min"];

function PbsCard() {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["pbs"], queryFn: fetchPbs });
  const entries = PB_ORDER.map((k) => [k, q.data?.[k] ?? null] as const);
  return (
    <Card title="Personal bests" action={<Link to="/tests" className="text-sm font-medium text-accent hover:underline">Test center</Link>}>
      {q.isLoading ? (
        <Loading rows={2} />
      ) : q.isError ? (
        <ErrorState message="Couldn't load personal bests." onRetry={() => q.refetch()} />
      ) : (
        <ul className="grid grid-cols-2 gap-2">
          {entries.map(([key, e]) => {
            const href = e == null ? null : e.piece_id != null ? `/tests/piece/${e.piece_id}` : `/workouts/${e.activity_id}`;
            const timed = key.endsWith("min");
            const main = e == null ? "—" : timed ? formatDistance(e.distance_m) : formatDuration(e.duration_s);
            const content = (
              <>
                <span className="text-xs font-medium text-text-tertiary">{key}</span>
                <span className="font-mono-nums text-lg font-semibold text-text-primary">{main}</span>
                <span className="text-xs text-text-tertiary">
                  {e?.pace_s_per_500 != null ? `${formatSplit(e.pace_s_per_500)}/500m` : "No result yet"}
                  {e?.date ? ` · ${formatShortDate(e.date)}` : ""}
                </span>
              </>
            );
            return (
              <li key={key} className="min-w-0">
                {href ? (
                  <button type="button" onClick={() => navigate(href)} className="flex w-full flex-col items-start gap-0.5 rounded-md border border-border bg-surface-2/50 p-3 text-left transition-colors hover:border-accent/40">
                    {content}
                  </button>
                ) : (
                  <div className="flex flex-col gap-0.5 rounded-md border border-dashed border-border p-3">{content}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function TopInsightCard() {
  const q = useQuery({ queryKey: ["recommendations"], queryFn: () => fetchRecommendations("active") });
  const top = q.data?.[0] ?? null;
  if (q.isLoading) return <Skeleton className="h-28 w-full rounded-lg" />;
  if (q.isError || !top) return null;
  return (
    <Card tone="accent" eyebrow="Training intelligence" title={top.title} action={<Link to="/trends/intelligence" className="shrink-0 text-sm font-medium text-accent hover:underline">More</Link>}>
      <p className="text-sm text-text-secondary">{top.body}</p>
      <p className="mt-2 text-xs text-text-tertiary">Confidence: {top.confidence.replace("_", " ")}</p>
    </Card>
  );
}
