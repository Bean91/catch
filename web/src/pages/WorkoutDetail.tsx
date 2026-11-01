import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchErgStrokes, fetchSettings, fetchWorkoutDetail } from "../lib/api";
import { activityTypeLabel, bandLabel, categoryLabel, formatDistance, formatDuration, formatShortDate, formatSplit } from "../lib/format";
import type { Domain } from "../lib/useChartInteraction";
import { ErgChart } from "../components/charts/ErgChart";
import { IntervalTable } from "../components/workouts/IntervalTable";
import { NotesBox } from "../components/workouts/NotesBox";
import { TechniqueGrid } from "../components/workouts/TechniqueGrid";
import { ZoneTable } from "../components/workouts/ZoneTable";
import { BandBadge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";

function quantizePoints(plotWidthPx: number): number {
  return Math.min(2000, Math.max(200, Math.ceil((plotWidthPx * 2) / 100) * 100));
}

function padDomain(domain: Domain, full: Domain): { min: number; max: number } {
  const span = domain.max - domain.min;
  return { min: Math.max(full.min, domain.min - span), max: Math.min(full.max, domain.max + span) };
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-text-tertiary">{label}</div>
      <div className="font-mono-nums text-base font-medium text-text-primary">{value}</div>
    </div>
  );
}

export function WorkoutDetailPage() {
  const { id } = useParams();
  const activityId = Number(id);

  const { data: workout, isLoading, isError, refetch } = useQuery({
    queryKey: ["workout", activityId],
    queryFn: () => fetchWorkoutDetail(activityId),
    enabled: Number.isFinite(activityId),
  });

  const isRowing = workout?.category === "erg" || workout?.category === "on_water";
  const hasStrokes = workout?.source === "concept2";

  // Full-resolution fetch, once: technique/interval_summary are always computed server-side
  // over every stroke regardless of `points` (tests/test_api_erg_downsample.py), so this one
  // call also supplies the stable interval table and technique cards — only the chart's own
  // `strokes` array needs re-fetching per zoom level, below.
  const { data: fullStrokesData } = useQuery({
    queryKey: ["erg-strokes-full", activityId],
    queryFn: () => fetchErgStrokes(activityId),
    enabled: !!workout && isRowing && hasStrokes,
  });

  // Memoized for the same reason Trends.tsx's fullDomain is — a stable object identity across
  // pan/zoom re-renders, since every chart below threads this through useChartInteraction's
  // dependency arrays.
  const fullDomain: Domain | null = useMemo(
    () => (fullStrokesData ? { min: 0, max: Math.max(...fullStrokesData.strokes.map((s) => s.distance_cum ?? 0), 1) } : null),
    [fullStrokesData],
  );
  // `domain` updates every pan/zoom frame (live x-scale); `queryDomain` only updates once a
  // gesture settles, which is what the stroke-window query keys off — same split as
  // Trends.tsx/Body.tsx, for the same reason (a CPU-throttled pan perf test caught
  // mid-gesture refetches spiking frame time otherwise).
  const [domain, setDomain] = useState<Domain | null>(null);
  const [queryDomain, setQueryDomain] = useState<Domain | null>(null);
  const effectiveDomain = domain ?? fullDomain ?? { min: 0, max: 1 };
  const effectiveQueryDomain = queryDomain ?? fullDomain ?? { min: 0, max: 1 };
  const resetDomain = () => {
    setDomain(fullDomain);
    setQueryDomain(fullDomain);
  };
  const onDomainSettled = (next: Domain) => setQueryDomain(next);

  const padded = fullDomain ? padDomain(effectiveQueryDomain, fullDomain) : null;
  const points = quantizePoints(640);
  const { data: windowedStrokesData } = useQuery({
    queryKey: ["erg-strokes-window", activityId, padded?.min, padded?.max, points],
    queryFn: () => fetchErgStrokes(activityId, { points, distanceMin: padded!.min, distanceMax: padded!.max }),
    enabled: !!padded,
    placeholderData: keepPreviousData,
  });

  const [hoveredInterval, setHoveredInterval] = useState<number | null>(null);

  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <CardSkeleton lines={1} />
        <CardSkeleton lines={3} />
      </div>
    );
  }

  if (isError || !workout) {
    return <ErrorState message="Couldn't load this workout." onRetry={() => refetch()} />;
  }

  const avgSplit = isRowing && workout.duration && workout.distance ? (workout.duration / workout.distance) * 500 : null;

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/workouts" className="text-sm text-text-tertiary transition-colors hover:text-text-secondary">
          ← Workouts
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold text-text-primary">{activityTypeLabel(workout.type)}</h1>
          <span className="text-sm text-text-tertiary">{categoryLabel(workout.category)}</span>
        </div>
        <p className="text-sm text-text-tertiary">{workout.start ? formatShortDate(workout.start) : "—"}</p>
      </div>

      <Card>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          <Stat label="Distance" value={formatDistance(workout.distance)} />
          <Stat label="Time" value={formatDuration(workout.duration)} />
          {avgSplit && <Stat label="Avg split" value={`${formatSplit(avgSplit)}/500m`} />}
          {workout.avg_power != null && <Stat label="Watts" value={workout.avg_power.toFixed(0)} />}
          {workout.avg_hr != null && <Stat label="Avg HR" value={workout.avg_hr.toFixed(0)} />}
          {workout.drag_factor != null && <Stat label="Drag factor" value={String(workout.drag_factor)} />}
        </div>
        {workout.strain && (
          <div className="mt-4 flex items-center gap-2 border-t border-border pt-3">
            <span className="text-xs text-text-tertiary">Strain</span>
            <BandBadge band={workout.strain.band} label={bandLabel(workout.strain.band)} />
            {workout.strain.value != null && <span className="font-mono-nums text-sm text-text-primary">{workout.strain.value.toFixed(1)}</span>}
          </div>
        )}
      </Card>

      {isRowing && hasStrokes && fullStrokesData && fullDomain && (
        <>
          <Card title="Split, watts & rate over distance">
            <ErgChart
              strokes={windowedStrokesData?.strokes ?? fullStrokesData.strokes}
              maxHr={settings?.max_hr ?? null}
              hrPct={settings?.zones.hr_pct ?? {}}
              domain={effectiveDomain}
              fullDomain={fullDomain}
              onDomainChange={setDomain}
              onDomainSettled={onDomainSettled}
              onResetDomain={resetDomain}
              hoveredInterval={hoveredInterval}
              onHoverInterval={setHoveredInterval}
            />
          </Card>
          <Card title="Intervals">
            <IntervalTable intervals={fullStrokesData.interval_summary} hoveredInterval={hoveredInterval} onHoverInterval={setHoveredInterval} />
          </Card>
          {Object.entries(fullStrokesData.technique_by_interval)
            .sort((a, b) => Number(a[0]) - Number(b[0]))
            .map(([idx, technique]) => (
              <Card key={idx} title={Object.keys(fullStrokesData.technique_by_interval).length > 1 ? `Technique — rep ${Number(idx) + 1}` : "Technique"}>
                <TechniqueGrid technique={technique} />
              </Card>
            ))}
        </>
      )}

      {isRowing && !hasStrokes && (
        <Card title="Zones">
          <p className="mb-3 text-xs text-text-tertiary">
            No per-stroke data for this Garmin-only session — split/watts/rate charts and the interval table need a Concept2 (PM5) sync.
          </p>
          <ZoneTable zones={workout.zones} currentZone={workout.hr_zone} />
        </Card>
      )}

      {workout.category === "other" && (
        <Card title="HR zones">
          <ZoneTable zones={workout.zones} currentZone={workout.hr_zone} />
        </Card>
      )}

      {workout.local_date && <NotesBox date={workout.local_date} />}
    </div>
  );
}
