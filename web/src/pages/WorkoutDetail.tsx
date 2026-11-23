import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BackLink } from "../components/ui/PageHeader";
import { padDomain, quantizePoints } from "../lib/chartFetch";
import { useCallback, useMemo, useState } from "react";
import { nearestIndex } from "../components/charts/core";
import { useParams } from "react-router-dom";
import { alignPiece, fetchWorkoutPlanComparison, fetchActivitySamples, importConcept2Intervals, fetchErgStrokes, fetchPieces, fetchWorkoutDetail, patchActivity, revertActivityField, splitActivity, undoMerge } from "../lib/api";
import { bandLabel, categoryLabel, formatDistance, formatDuration, formatShortDate, formatSplit } from "../lib/format";
import type { Domain } from "../lib/useChartInteraction";
import type { EditableActivityField, SportFamily, Stroke } from "../lib/types";
import { ErgChart } from "../components/charts/ErgChart";
import { HrChart, type PieceBand } from "../components/charts/HrChart";
import { GpsSection } from "../components/gps/GpsSection";
import { WeatherChips } from "../components/gps/WeatherCard";
import { AddPieceDialog } from "../components/pieces/AddPieceDialog";
import { TechniqueNotesCard } from "../components/coaching/TechniqueNotesCard";
import { PlanComparisonView } from "../components/calendar/PlanComparisonView";
import { PieceCard } from "../components/pieces/PieceCard";
import { IntervalTable } from "../components/workouts/IntervalTable";
import { NotesBox } from "../components/workouts/NotesBox";
import { TechniqueGrid } from "../components/workouts/TechniqueGrid";
import { ZoneBar } from "../components/workouts/ZoneBar";
import { ZoneTable } from "../components/workouts/ZoneTable";
import { Badge, BandBadge } from "../components/ui/Badge";
import { Button, buttonClass } from "../components/ui/Button";
import { controlClass, controlSkin } from "../components/ui/Field";
import { InfoTip } from "../components/ui/InfoTip";
import { Segmented } from "../components/ui/Segmented";
import { StatTile } from "../components/ui/StatTile";
import { Histogram } from "../components/charts/Histogram";
import { ScatterPlot } from "../components/charts/ScatterPlot";
import { METRIC_COLOR } from "../lib/metricColors";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { addDays } from "../lib/dates";
import { formatInstantTime } from "../lib/localTime";




const SPORT_FAMILIES: SportFamily[] = ["rowing", "cycling", "running", "strength", "other"];
const PROVENANCE_LABELS: Record<string, string> = { garmin: "Garmin watch", peloton: "Peloton", concept2: "Concept2 PM5", apple_health: "Apple Health", health_connect: "Health Connect" };

export function WorkoutDetailPage() {
  const { id } = useParams();
  const canonicalId = Number(id);
  const queryClient = useQueryClient();

  const { data: workout, isLoading, isError, refetch } = useQuery({
    queryKey: ["workout", canonicalId],
    queryFn: () => fetchWorkoutDetail(canonicalId),
    enabled: Number.isFinite(canonicalId),
  });

  const isRowing = workout?.category === "erg" || workout?.category === "on_water";
  const planComparison = useQuery({
    queryKey: ["workout-plan-comparison", canonicalId],
    queryFn: () => fetchWorkoutPlanComparison(canonicalId),
    enabled: !!workout,
  });
  const linkedPlan = planComparison.data && "planned_id" in planComparison.data ? planComparison.data : null;
  // Strokes are tied to a *raw* Concept2 source record, never the canonical id — pick the
  // first concept2 member, if any (session 8/12 — see PLAN.md).
  const concept2Source = workout?.sources.find((s) => s.source === "concept2");
  const hasStrokes = !!concept2Source;
  const strokesActivityId = concept2Source?.activity_id;

  const { data: fullStrokesData } = useQuery({
    queryKey: ["erg-strokes-full", strokesActivityId],
    queryFn: () => fetchErgStrokes(strokesActivityId!),
    enabled: !!workout && isRowing && hasStrokes && !!strokesActivityId,
  });

  const fullDomain: Domain | null = useMemo(
    // A loop, not Math.max(...spread): a long session's stroke array can exceed the engine's argument limit.
    () => (fullStrokesData ? { min: 0, max: fullStrokesData.strokes.reduce((m, s) => Math.max(m, s.distance_cum ?? 0), 1) } : null),
    [fullStrokesData],
  );
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
    queryKey: ["erg-strokes-window", strokesActivityId, padded?.min, padded?.max, points],
    queryFn: () => fetchErgStrokes(strokesActivityId!, { points, distanceMin: padded!.min, distanceMax: padded!.max }),
    enabled: !!padded && !!strokesActivityId,
    placeholderData: keepPreviousData,
  });

  const [hoveredInterval, setHoveredInterval] = useState<number | null>(null);


  // --- HR graph (task Part E.8) --------------------------------------------
  // Two queries, like the erg strokes above: one unwindowed fetch for everything that's
  // stable regardless of zoom (summary chips, zones, label, laps, n_samples), and a second,
  // re-fetched-per-zoom one for just the chart's own point array — "full resolution when
  // zoomed in" needs the backend's start_s/end_s window, not only a wider on-screen domain
  // over the same fixed 800-point sample.
  const { data: samples } = useQuery({
    queryKey: ["activity-samples", canonicalId],
    queryFn: () => fetchActivitySamples(canonicalId, { points: 800 }),
    enabled: !!workout && workout.has_samples,
  });
  // The chart's x is elapsed seconds; n_samples equals that for 1 Hz recordings, and the last point's elapsed time covers any that
  // aren't, so the full range never cuts a recording short.
  const hrFullDomain: Domain | null = samples?.has_data
    ? { min: 0, max: Math.max(samples.n_samples, samples.points[samples.points.length - 1]?.elapsed_s ?? 0, 1) }
    : null;
  const [hrDomain, setHrDomain] = useState<Domain | null>(null);
  const [hrQueryDomain, setHrQueryDomain] = useState<Domain | null>(null);
  const effectiveHrDomain = hrDomain ?? hrFullDomain ?? { min: 0, max: 1 };
  const effectiveHrQueryDomain = hrQueryDomain ?? hrFullDomain ?? { min: 0, max: 1 };
  const resetHrDomain = () => {
    setHrDomain(hrFullDomain);
    setHrQueryDomain(hrFullDomain);
  };
  const onHrDomainSettled = (next: Domain) => setHrQueryDomain(next);
  const [overlayChoice, setOverlay] = useState<"none" | "power" | "cadence" | null>(null);
  // A recording with no heart rate opens on whichever channel it does have.
  const overlay = overlayChoice ?? (samples?.has_data && samples.has_hr === false ? (samples.has_power ? "power" : "cadence") : "none");

  const hrPadded = hrFullDomain ? padDomain(effectiveHrQueryDomain, hrFullDomain) : null;
  const hrPoints = quantizePoints(640);
  const { data: windowedSamples } = useQuery({
    queryKey: ["activity-samples-window", canonicalId, hrPadded?.min, hrPadded?.max, hrPoints],
    queryFn: () => fetchActivitySamples(canonicalId, { points: hrPoints, startS: Math.floor(hrPadded!.min), endS: Math.ceil(hrPadded!.max) }),
    enabled: !!hrPadded && samples?.has_data,
    placeholderData: keepPreviousData,
  });
  const chartPoints = windowedSamples?.has_data ? windowedSamples.points : samples?.has_data ? samples.points : [];

  // --- Shared cursor between the HR chart (elapsed time) and the erg chart (distance), session 36 ---------------------------
  // Only when the stroke list and the HR chart's timeline are the same recording (or, on a combined workout, a part whose offset
  // is known). A watch and a PM5 started at different moments, and their clocks are never assumed to agree.
  const syncOffset = useMemo(() => {
    if (!samples?.has_data || strokesActivityId == null) return null;
    if (samples.recording_activity_id === strokesActivityId) return 0;
    if (samples.combined) return samples.member_offsets?.[String(strokesActivityId)] ?? null;
    return null;
  }, [samples, strokesActivityId]);
  const strokeAxis = useMemo(() => {
    const rows = (fullStrokesData?.strokes ?? []).filter((st) => st.distance_cum != null && st.t_cum != null);
    return { d: rows.map((st) => st.distance_cum as number), t: rows.map((st) => st.t_cum as number) };
  }, [fullStrokesData]);
  const [hrHoverFromErg, setHrHoverFromErg] = useState<number | null>(null);
  const [ergHoverFromHr, setErgHoverFromHr] = useState<number | null>(null);
  const onErgHover = useCallback(
    (d: number | null) => setHrHoverFromErg(d == null || syncOffset == null || !strokeAxis.d.length ? null : strokeAxis.t[nearestIndex(strokeAxis.d, d)] + syncOffset),
    [syncOffset, strokeAxis],
  );
  const onHrHover = useCallback(
    (e: number | null) => setErgHoverFromHr(e == null || syncOffset == null || !strokeAxis.t.length ? null : strokeAxis.d[nearestIndex(strokeAxis.t, e - syncOffset)]),
    [syncOffset, strokeAxis],
  );

  // --- Pieces (session 17 — see PLAN.md, the task called itself "session 13") -----------
  const { data: pieces } = useQuery({
    queryKey: ["pieces", canonicalId],
    queryFn: () => fetchPieces(canonicalId),
    enabled: !!workout,
  });
  const [addPieceOpen, setAddPieceOpen] = useState(false);
  const [selectedPieceId, setSelectedPieceId] = useState<number | null>(null);
  const effectiveSelectedPieceId = selectedPieceId ?? pieces?.[0]?.id ?? null;
  // Session 33: a piece window is stored relative to its own recording; on a merged workout the chart's timeline starts at the
  // first recording, so each window is shifted by its recording's offset (all zero for an ordinary workout).
  const memberOffsets: Record<string, number> = samples?.has_data ? (samples.member_offsets ?? {}) : {};
  const offsetFor = (activityId: number | null) => (activityId != null ? (memberOffsets[String(activityId)] ?? 0) : 0);
  const pieceBands: PieceBand[] = (pieces ?? [])
    .filter((p) => p.window_start_s != null && p.window_end_s != null)
    .map((p) => ({ id: p.id, startS: (p.window_start_s as number) + offsetFor(p.window_activity_id), endS: (p.window_end_s as number) + offsetFor(p.window_activity_id) }));
  const importIntervals = useMutation({
    mutationFn: (activityId: number) => importConcept2Intervals(canonicalId, activityId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pieces", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["workout", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["interval-comparisons"] });
    },
  });
  const alignMutation = useMutation({
    mutationFn: ({ pieceId, startS }: { pieceId: number; startS: number }) => {
      const piece = pieces?.find((p) => p.id === pieceId);
      const activityId = piece?.window_activity_id ?? undefined;
      return alignPiece(pieceId, activityId, Math.max(0, startS - offsetFor(activityId ?? null)));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pieces", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["workout", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["activity-samples", canonicalId] });
    },
  });

  // --- Editing (task Part C) ------------------------------------------------
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  const patch = useMutation({
    mutationFn: (p: Parameters<typeof patchActivity>[1]) => patchActivity(canonicalId, p),
    onSuccess: (updated) => queryClient.setQueryData(["workout", canonicalId], updated),
  });
  const revert = useMutation({
    mutationFn: (field: EditableActivityField) => revertActivityField(canonicalId, field),
    onSuccess: (updated) => queryClient.setQueryData(["workout", canonicalId], updated),
  });
  const split = useMutation({
    mutationFn: (activityId: number) => splitActivity(activityId),
    // The mutation's return value is the *new*, split-off canonical — never write it into
    // this page's own ["workout", canonicalId] cache (that would show the wrong activity's
    // data under this id). Invalidate instead so this page refetches its own, now-smaller
    // canonical for real.
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workout", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["workouts"] });
    },
  });

  const [confirmUndoMerge, setConfirmUndoMerge] = useState(false);
  const undoMergeMutation = useMutation({
    mutationFn: () => undoMerge(canonicalId),
    onSuccess: () => {
      setConfirmUndoMerge(false);
      queryClient.invalidateQueries({ queryKey: ["workout", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["workouts"] });
      queryClient.invalidateQueries({ queryKey: ["pieces", canonicalId] });
      queryClient.invalidateQueries({ queryKey: ["activity-samples", canonicalId] });
    },
  });

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
        <BackLink to="/workouts">Workouts</BackLink>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {editingTitle ? (
            <input
              autoFocus
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={() => {
                setEditingTitle(false);
                if (titleDraft && titleDraft !== workout.title) patch.mutate({ title: titleDraft });
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                if (e.key === "Escape") setEditingTitle(false);
              }}
              className={controlSkin + " w-auto min-h-11 min-w-0"}
            />
          ) : (
            <h1
              className="min-w-0 wrap-anywhere cursor-text text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]"
              onClick={() => {
                setTitleDraft(workout.title ?? "");
                setEditingTitle(true);
              }}
              title="Tap to rename"
            >
              {workout.title ?? "Workout"}
            </h1>
          )}
          <Badge tone="outline">{categoryLabel(workout.category)}</Badge>
          {workout.overrides.title && (
            <button type="button" onClick={() => revert.mutate("title")} className="text-xs text-text-tertiary underline hover:text-text-secondary">
              revert to source
            </button>
          )}
        </div>
        <p className="text-sm text-text-tertiary">
          {workout.local_date ? formatShortDate(workout.local_date) : workout.start ? formatShortDate(workout.start, workout.local_tz) : "—"}
          {workout.start && <span className="ml-2 font-mono-nums">{formatInstantTime(workout.start, workout.local_tz)}</span>}
          {workout.session_label && <span className="ml-2">{workout.session_label}</span>}
          {workout.exclude_from_totals && <span className="ml-2 text-text-tertiary">(excluded from totals)</span>}
        </p>
        {workout.recorded_local_date && (
          <ChangeDay
            recorded={workout.recorded_local_date}
            current={workout.local_date ?? workout.recorded_local_date}
            overridden={workout.overrides.local_date != null}
            onChange={(day) => (day === workout.recorded_local_date ? revert.mutate("local_date") : patch.mutate({ local_date: day }))}
            busy={patch.isPending || revert.isPending}
          />
        )}
      </div>

      <Card tone="raised">
        <div className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 lg:grid-cols-6">
          <StatTile size="lg" label="Distance" value={formatDistance(workout.distance)} />
          <StatTile size="lg" label="Time" value={formatDuration(workout.duration)} />
          {avgSplit && <StatTile size="lg" label="Avg split" value={formatSplit(avgSplit)} unit="/500m" accent={METRIC_COLOR.pace} />}
          {workout.avg_power != null && <StatTile size="lg" label="Power" value={workout.avg_power.toFixed(0)} unit="W" accent={METRIC_COLOR.power} />}
          {workout.avg_hr != null && <StatTile size="lg" label="Avg HR" value={workout.avg_hr.toFixed(0)} unit="bpm" accent={METRIC_COLOR.hr} />}
          {workout.avg_cadence != null && <StatTile size="lg" label={workout.sport_family === "cycling" ? "Cadence" : "Rate"} value={workout.avg_cadence.toFixed(0)} unit={workout.sport_family === "cycling" ? "rpm" : "spm"} accent={METRIC_COLOR.rate} />}
        </div>
        {workout.strain && (
          <div className="mt-4 flex items-center gap-2 border-t border-border pt-3">
            <span className="text-xs text-text-tertiary">Strain</span>
            <BandBadge band={workout.strain.band} label={bandLabel(workout.strain.band)} />
            {workout.strain.value != null && <span className="font-mono-nums text-sm text-text-primary">{workout.strain.value.toFixed(1)}</span>}
            {workout.strain_method?.includes("estimated") && <span className="text-xs text-text-tertiary">(estimated FTP)</span>}
          </div>
        )}
        <WeatherChips canonicalId={canonicalId} enabled={!!workout.has_track} />
        {(workout.zones?.hr || workout.zones?.power) && (
          <div className="mt-4 flex flex-col gap-3 border-t border-border pt-3">
            {workout.zones?.hr && (
              <div>
                <p className="mb-1 text-xs text-text-tertiary">Time in zone — heart rate</p>
                <ZoneBar zones={workout.zones.hr} height={10} showLegend />
              </div>
            )}
            {/* Part E.5: erg/bike also compute a power-zone reading, shown alongside HR so
                both are visible even though session_label only used the higher-intensity one. */}
            {workout.zones?.power && (
              <div>
                <p className="mb-1 text-xs text-text-tertiary">Time in zone — power</p>
                <ZoneBar zones={workout.zones.power} height={10} showLegend />
              </div>
            )}
          </div>
        )}
      </Card>

      {linkedPlan && (
        <Card title="Planned and done" eyebrow={linkedPlan.planned.title} testId="planned-and-done">
          <PlanComparisonView data={linkedPlan} showWorkoutLink={false} />
        </Card>
      )}

      {samples?.has_data && (
        <Card title={samples.has_hr === false ? "Power and cadence" : "Heart rate"}>
          {samples.has_hr === false && <p className="mb-3 text-sm text-text-tertiary">No heart rate was recorded — this recording has {samples.has_power ? "power" : "cadence"} only.</p>}
          {samples.has_hr !== false && <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile size="sm" label="Average" value={Math.round(samples.avg_hr ?? 0)} unit="bpm" accent={METRIC_COLOR.hr} />
            <StatTile size="sm" label="Max" value={samples.max_hr_observed ?? "—"} unit="bpm" />
            <StatTile size="sm" label="Min" value={samples.min_hr_observed ?? "—"} unit="bpm" />
            {samples.hr_recovery.session_end != null && (
              <StatTile
                size="sm"
                label="Recovery (60s)"
                value={samples.hr_recovery.session_end.toFixed(0)}
                unit="bpm"
                info={<InfoTip label="heart-rate recovery">How far your heart rate fell in the 60 seconds after the session ended. A bigger drop usually means fitter, fresher, or both.</InfoTip>}
              />
            )}
          </div>}
          {(samples.gaps ?? 0) > 0 && <p className="mb-2 text-xs text-text-tertiary">The line breaks where the sensor dropped out — nothing is filled in.</p>}
          {samples.trimmed_tail_s > 0 && <p className="mb-2 text-xs text-text-tertiary">Watch left running {Math.round(samples.trimmed_tail_s)}s — greyed out, excluded above.</p>}
          {samples.zones?.hr && (
            <div className="mb-3">
              <ZoneBar zones={samples.zones.hr} height={8} showLegend />
            </div>
          )}
          {(samples.points.some((p) => p.power != null) || samples.points.some((p) => p.cadence != null)) && (
            <Segmented
              label="Overlay"
              size="sm"
              className="mb-3"
              value={overlay}
              onChange={setOverlay}
              options={[
                ...(samples.has_hr === false ? [] : [{ value: "none" as const, label: "HR only" }]),
                { value: "power", label: "+ Power" },
                { value: "cadence", label: "+ Cadence" },
              ]}
            />
          )}
          <HrChart
            points={chartPoints}
            allPoints={samples.points}
            zonesConfig={samples.zones_config}
            maxHrSetting={samples.max_hr_setting}
            avgHr={samples.avg_hr}
            laps={samples.laps}
            trimmedTailS={samples.trimmed_tail_s}
            overlay={overlay}
            domain={effectiveHrDomain}
            fullDomain={hrFullDomain ?? { min: 0, max: 1 }}
            onDomainChange={setHrDomain}
            onDomainSettled={onHrDomainSettled}
            onResetDomain={resetHrDomain}
            pieceBands={pieceBands}
            selectedPieceId={effectiveSelectedPieceId}
            onPieceDragEnd={(pieceId, startS) => alignMutation.mutate({ pieceId, startS })}
            externalHoverX={hrHoverFromErg}
            onHoverXChange={onHrHover}
          />
        </Card>
      )}
      {workout.has_samples && samples && !samples.has_data && (
        <Card title="Heart rate">
          <p className="text-sm text-text-tertiary">No heart-rate data for this activity.</p>
        </Card>
      )}

      <GpsSection canonicalId={canonicalId} category={workout.category} hasTrack={!!workout.has_track} sportFamily={workout.sport_family} />

      <Card
        title="Pieces"
        action={
          <Button size="sm" variant="subtle" onClick={() => setAddPieceOpen(true)}>
            Add piece
          </Button>
        }
      >
        {workout?.concept2_interval_activity_id != null && !pieces?.some((p) => p.has_intervals && p.concept2_activity_id === workout.concept2_interval_activity_id) && (
          <button
            type="button"
            disabled={importIntervals.isPending}
            onClick={() => importIntervals.mutate(workout.concept2_interval_activity_id!)}
            className={buttonClass("secondary", "sm", "mb-2")}
          >
            {importIntervals.isPending ? "Importing…" : "Import intervals from Concept2"}
          </button>
        )}
        {importIntervals.isError && <p className="mb-2 text-xs text-band-red-text">Couldn't import — this result has no interval data.</p>}
        {pieces == null || pieces.length === 0 ? (
          <p className="text-sm text-text-tertiary">No pieces yet — a 2k inside this session, say.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {pieces.map((p) => (
              <div key={p.id} onClick={() => setSelectedPieceId(p.id)} className={p.id === effectiveSelectedPieceId ? "rounded-md ring-2 ring-accent/40" : undefined}>
                <PieceCard piece={p} canonicalId={canonicalId} />
              </div>
            ))}
            {pieceBands.length > 0 && <p className="text-xs text-text-tertiary">Tap a piece to select it, then drag its band's edge on the heart-rate chart above to re-align.</p>}
          </div>
        )}
      </Card>
      <AddPieceDialog
        open={addPieceOpen}
        onClose={() => setAddPieceOpen(false)}
        canonicalId={canonicalId}
        defaultModality={workout?.sport_family === "cycling" ? "bike" : "rowing_erg"}
        onSaved={() => setAddPieceOpen(false)}
      />

      <TechniqueNotesCard canonicalId={canonicalId} date={workout?.local_date ?? null} pieces={(pieces ?? []).map((p) => ({ id: p.id, label: `Piece ${p.piece_type}` }))} />

      {isRowing && hasStrokes && fullStrokesData && fullDomain && (
        <>
          <Card title="Split, watts & rate over distance">
            <ErgChart
              strokes={windowedStrokesData?.strokes ?? fullStrokesData.strokes}
              hrBoundsBpm={workout.zones_config?.hr_basis?.bounds_bpm ?? {}}
              domain={effectiveDomain}
              fullDomain={fullDomain}
              onDomainChange={setDomain}
              onDomainSettled={onDomainSettled}
              onResetDomain={resetDomain}
              hoveredInterval={hoveredInterval}
              onHoverInterval={setHoveredInterval}
              externalHoverX={ergHoverFromHr}
              onHoverXChange={onErgHover}
            />
            {samples?.has_data && (
              <p className="mt-2 text-xs text-text-tertiary" data-testid="chart-sync-note">
                {syncOffset != null
                  ? "Linked to the heart-rate chart above: pointing at one shows the same moment on the other. The distance axis is rowing time only — rest isn't on it."
                  : "Not linked to the heart-rate chart: that chart is from another device's recording, and the two clocks can't be matched exactly."}
              </p>
            )}
          </Card>
          <StrokeAnalysis strokes={fullStrokesData.strokes} />
          <Card title="Intervals">
            <IntervalTable intervals={fullStrokesData.interval_summary} consistency={fullStrokesData.interval_consistency} hoveredInterval={hoveredInterval} onHoverInterval={setHoveredInterval} />
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
          <ZoneTable zones={workout.zones_config} currentZone={workout.hr_zone} />
        </Card>
      )}

      {workout.category === "other" && (
        <Card title="HR zones">
          <ZoneTable zones={workout.zones_config} currentZone={workout.hr_zone} />
        </Card>
      )}

      {workout.category === "strength" && (
        <>
          {workout.muscular_by_muscle && Object.keys(workout.muscular_by_muscle).length > 0 && (
            <Card title="Muscular load">
              <ul className="flex flex-col gap-1.5">
                {Object.entries(workout.muscular_by_muscle)
                  .sort((a, b) => b[1] - a[1])
                  .map(([muscle, value]) => (
                    <li key={muscle} className="flex items-center justify-between text-sm">
                      <span className="capitalize text-text-secondary">{muscle}</span>
                      <span className="font-mono-nums text-text-primary">{Math.round(value)} AU</span>
                    </li>
                  ))}
              </ul>
            </Card>
          )}
          <Card title="Sets">
            {!workout.strength_sets || workout.strength_sets.length === 0 ? (
              <p className="text-sm text-text-tertiary">No sets logged for this session.</p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {workout.strength_sets.map((s) => (
                  <li key={s.client_id} className="flex items-center justify-between rounded-md bg-surface-2 px-3 py-2 text-sm">
                    <span className="text-text-secondary">
                      {s.reps} reps{s.set_type !== "working" ? ` (${s.set_type})` : ""}
                      {!s.is_confirmed && <span className="ml-2 text-xs text-band-yellow">unconfirmed — imported from Garmin</span>}
                    </span>
                    <span className="flex items-center gap-2 font-mono-nums text-text-primary">
                      {s.effective_load_kg != null ? `${Math.round(s.effective_load_kg * 10) / 10}kg` : "—"}
                      {s.is_rep_pr && <Badge tone="accent">PR</Badge>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}

      <Card title="Your notes" eyebrow="Details">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs font-medium text-text-secondary" htmlFor="wd-sport">
              Sport
            </label>
            <select
              id="wd-sport"
              value={workout.sport_family}
              onChange={(e) => patch.mutate({ sport_family: e.target.value as SportFamily })}
              className={`${controlClass} w-auto`}
            >
              {SPORT_FAMILIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            {workout.overrides.sport_family && (
              <button type="button" onClick={() => revert.mutate("sport_family")} className="text-xs text-text-tertiary underline">
                revert
              </button>
            )}

            <label className="ml-4 flex items-center gap-2 text-sm text-text-secondary">
              <input
                type="checkbox"
                checked={workout.exclude_from_totals}
                onChange={(e) => patch.mutate({ exclude_from_totals: e.target.checked })}
                className="h-5 w-5 accent-accent"
              />
              Exclude from totals
            </label>
          </div>

          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-text-secondary" htmlFor="wd-tags">
              Tags (comma-separated)
            </label>
            <input
              id="wd-tags"
              defaultValue={workout.tags.join(", ")}
              onBlur={(e) =>
                patch.mutate({ tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })
              }
              placeholder="race, test, technique, cross-training"
              className={`${controlClass} flex-1`}
            />
          </div>

          <div>
            <label className="text-xs font-medium text-text-secondary" htmlFor="wd-notes">
              Notes (this workout)
            </label>
            <textarea
              id="wd-notes"
              defaultValue={workout.notes ?? ""}
              onBlur={(e) => patch.mutate({ notes: e.target.value })}
              placeholder="How did it feel?"
              rows={2}
              className={`${controlClass} mt-1 resize-none py-2.5`}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="min-w-0">
              <label className="text-xs font-medium text-text-secondary" htmlFor="wd-conditions">
                Conditions (your words)
              </label>
              <input
                id="wd-conditions"
                defaultValue={workout.conditions ?? ""}
                onBlur={(e) => e.target.value !== (workout.conditions ?? "") && patch.mutate({ conditions: e.target.value })}
                placeholder="e.g. headwind, hot gym, choppy"
                maxLength={300}
                className={`${controlClass} mt-1 min-w-0`}
              />
            </div>
            <div className="min-w-0">
              <label className="text-xs font-medium text-text-secondary" htmlFor="wd-equipment">
                Equipment
              </label>
              <input
                id="wd-equipment"
                defaultValue={workout.equipment ?? ""}
                onBlur={(e) => e.target.value !== (workout.equipment ?? "") && patch.mutate({ equipment: e.target.value })}
                placeholder="e.g. club 1x, drag 125, own blades"
                maxLength={300}
                className={`${controlClass} mt-1 min-w-0`}
              />
            </div>
          </div>
          <p className="text-xs text-text-tertiary">Notes, conditions, equipment, tags and RPE are yours — kept apart from what the devices measured, and searchable from Workouts.</p>

          <div className="flex items-center gap-3">
            <label className="text-xs font-medium text-text-secondary" htmlFor="wd-rpe">
              RPE (this workout)
            </label>
            <input
              id="wd-rpe"
              type="range"
              min={0}
              max={10}
              step={1}
              value={workout.rpe ?? 0}
              onChange={(e) => patch.mutate({ rpe: Number(e.target.value) })}
              className="w-32 accent-accent"
            />
            <span className="font-mono-nums w-6 text-sm text-text-primary">{workout.rpe ?? "—"}</span>
            {workout.overrides.rpe != null && (
              <button type="button" onClick={() => revert.mutate("rpe")} className="text-xs text-text-tertiary underline">
                revert
              </button>
            )}
          </div>

          <div>
            {workout.merge && (
              <div className="mb-3 rounded-md border border-accent/30 bg-accent-soft p-3 text-sm" data-testid="merged-workout">
                <p className="text-text-primary">
                  Merged from {workout.merge.merged_workouts ?? "several"} workouts ({workout.merge.recordings} recording{workout.merge.recordings === 1 ? "" : "s"}). Times and
                  distances are added; anything recorded twice counts once.
                </p>
                {workout.merge.can_undo && !confirmUndoMerge && (
                  <button type="button" onClick={() => setConfirmUndoMerge(true)} className={buttonClass("secondary", "md", "mt-2")}>
                    Undo merge
                  </button>
                )}
                {confirmUndoMerge && (
                  <div role="group" aria-label="Confirm undo merge" className="mt-2 rounded-md border border-border p-3">
                    <p className="text-sm text-text-secondary">
                      Each workout comes back separately, with its own recordings, edits, pieces, plan link and notes. Edits made to the merged workout stay on the
                      earliest one.
                    </p>
                    <div className="mt-2 flex gap-2">
                      <button type="button" onClick={() => setConfirmUndoMerge(false)} className={buttonClass("secondary", "md", "flex-1")}>
                        Keep merged
                      </button>
                      <button
                        type="button"
                        disabled={undoMergeMutation.isPending}
                        onClick={() => undoMergeMutation.mutate()}
                        className={buttonClass("primary", "md", "flex-1")}
                      >
                        {undoMergeMutation.isPending ? "Undoing…" : "Undo merge"}
                      </button>
                    </div>
                    {undoMergeMutation.isError && <p role="alert" className="mt-2 text-sm text-band-red-text">Couldn't undo — nothing was changed.</p>}
                  </div>
                )}
              </div>
            )}
            <p className="mb-2 text-xs text-text-tertiary">Sources — which record each metric came from. Edits never push back to Garmin.</p>
            <ul className="flex flex-col gap-1">
              {workout.sources.map((s) => (
                <li key={s.activity_id} className="flex flex-wrap items-center gap-2 text-xs text-text-secondary">
                  <span className="font-medium text-text-primary">{PROVENANCE_LABELS[s.provenance] ?? s.provenance}</span>
                  {s.origin_app && <span className="text-text-tertiary">recorded by {s.origin_app}</span>}
                  <span className="text-text-tertiary">({s.type ?? "unknown type"})</span>
                  {Object.entries(workout.field_sources)
                    .filter(([, src]) => src === `${s.source}:${s.external_id}`)
                    .map(([field]) => (
                      <span key={field} className="rounded bg-surface-2 px-1.5 py-0.5 text-text-tertiary">
                        {field}
                      </span>
                    ))}
                  {workout.sources.length > 1 && (
                    <button
                      type="button"
                      disabled={split.isPending}
                      onClick={() => split.mutate(s.activity_id)}
                      className="text-text-tertiary underline hover:text-text-secondary"
                    >
                      split off
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>

      {workout.local_date && <NotesBox date={workout.local_date} />}
    </div>
  );
}


/** Session 32 "Change day": for the rare workout a device filed on the wrong day (a watch still on home time). Only the day before
 * or after the recorded one; the workout's time never changes, and the days' scores are recomputed. */
function ChangeDay({ recorded, current, overridden, onChange, busy }: { recorded: string; current: string; overridden: boolean; onChange: (day: string) => void; busy: boolean }) {
  const options = [addDays(recorded, -1), recorded, addDays(recorded, 1)];
  return (
    <label className="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-tertiary">
      Counts on
      <select
        aria-label="Day this workout counts on"
        value={current}
        disabled={busy}
        onChange={(e) => onChange(e.target.value)}
        className={controlSkin + " w-auto min-h-11"}
      >
        {options.map((d) => (
          <option key={d} value={d}>
            {formatShortDate(d)}
            {d === recorded ? " (recorded)" : ""}
          </option>
        ))}
      </select>
      {overridden && <span>changed by you</span>}
    </label>
  );
}


/** How the session's strokes were spread: share of strokes at each split, and split against stroke rate. Uses the full stroke list
 * (not the chart's downsampled window), so every stroke counts once. */
function StrokeAnalysis({ strokes }: { strokes: Stroke[] }) {
  const { splits, pairs } = useMemo(() => {
    const splits: number[] = [];
    const pairs: { x: number; y: number }[] = [];
    for (const s of strokes) {
      if (s.pace_500m != null && s.pace_500m > 60 && s.pace_500m < 300) {
        splits.push(s.pace_500m);
        if (s.stroke_rate != null && s.stroke_rate > 10) pairs.push({ x: s.stroke_rate, y: s.pace_500m });
      }
    }
    return { splits, pairs };
  }, [strokes]);
  if (splits.length < 20) return null;
  return (
    <Card title="Stroke analysis" eyebrow={`${splits.length} strokes`}>
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <p className="mb-1 text-xs font-medium text-text-secondary">Share of strokes at each split</p>
          <Histogram values={splits} format={formatSplit} color={METRIC_COLOR.pace} ariaLabel="Distribution of split per stroke" />
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-text-secondary">Split against stroke rate</p>
          <ScatterPlot
            points={pairs}
            xLabel="Stroke rate (spm)"
            yLabel="Split /500m (faster is higher)"
            formatX={(v) => `${Math.round(v)}`}
            formatY={formatSplit}
            yAxis="seconds"
            invertY
            color={METRIC_COLOR.rate}
            ariaLabel={`Split against stroke rate for ${pairs.length} strokes`}
          />
        </div>
      </div>
    </Card>
  );
}
