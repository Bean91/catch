import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { alignPiece, fetchActivitySamples, importConcept2Intervals, fetchErgStrokes, fetchPieces, fetchSettings, fetchWorkoutDetail, patchActivity, revertActivityField, splitActivity } from "../lib/api";
import { bandLabel, categoryLabel, formatDistance, formatDuration, formatShortDate, formatSplit } from "../lib/format";
import type { Domain } from "../lib/useChartInteraction";
import type { EditableActivityField, SportFamily } from "../lib/types";
import { ErgChart } from "../components/charts/ErgChart";
import { HrChart, type PieceBand } from "../components/charts/HrChart";
import { AddPieceDialog } from "../components/pieces/AddPieceDialog";
import { PieceCard } from "../components/pieces/PieceCard";
import { IntervalTable } from "../components/workouts/IntervalTable";
import { NotesBox } from "../components/workouts/NotesBox";
import { TechniqueGrid } from "../components/workouts/TechniqueGrid";
import { ZoneBar } from "../components/workouts/ZoneBar";
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

const SPORT_FAMILIES: SportFamily[] = ["rowing", "cycling", "running", "strength", "other"];
const PROVENANCE_LABELS: Record<string, string> = { garmin: "Garmin watch", peloton: "Peloton", concept2: "Concept2 PM5" };

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
    () => (fullStrokesData ? { min: 0, max: Math.max(...fullStrokesData.strokes.map((s) => s.distance_cum ?? 0), 1) } : null),
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

  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });

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
  const hrFullDomain: Domain | null = samples?.has_data ? { min: 0, max: Math.max(samples.n_samples, 1) } : null;
  const [hrDomain, setHrDomain] = useState<Domain | null>(null);
  const [hrQueryDomain, setHrQueryDomain] = useState<Domain | null>(null);
  const effectiveHrDomain = hrDomain ?? hrFullDomain ?? { min: 0, max: 1 };
  const effectiveHrQueryDomain = hrQueryDomain ?? hrFullDomain ?? { min: 0, max: 1 };
  const resetHrDomain = () => {
    setHrDomain(hrFullDomain);
    setHrQueryDomain(hrFullDomain);
  };
  const onHrDomainSettled = (next: Domain) => setHrQueryDomain(next);
  const [overlay, setOverlay] = useState<"none" | "power" | "cadence">("none");

  const hrPadded = hrFullDomain ? padDomain(effectiveHrQueryDomain, hrFullDomain) : null;
  const hrPoints = quantizePoints(640);
  const { data: windowedSamples } = useQuery({
    queryKey: ["activity-samples-window", canonicalId, hrPadded?.min, hrPadded?.max, hrPoints],
    queryFn: () => fetchActivitySamples(canonicalId, { points: hrPoints, startS: Math.floor(hrPadded!.min), endS: Math.ceil(hrPadded!.max) }),
    enabled: !!hrPadded && samples?.has_data,
    placeholderData: keepPreviousData,
  });
  const chartPoints = windowedSamples?.has_data ? windowedSamples.points : samples?.has_data ? samples.points : [];

  // --- Pieces (session 17 — see PLAN.md, the task called itself "session 13") -----------
  const { data: pieces } = useQuery({
    queryKey: ["pieces", canonicalId],
    queryFn: () => fetchPieces(canonicalId),
    enabled: !!workout,
  });
  const [addPieceOpen, setAddPieceOpen] = useState(false);
  const [selectedPieceId, setSelectedPieceId] = useState<number | null>(null);
  const effectiveSelectedPieceId = selectedPieceId ?? pieces?.[0]?.id ?? null;
  const pieceBands: PieceBand[] = (pieces ?? [])
    .filter((p) => p.window_start_s != null && p.window_end_s != null)
    .map((p) => ({ id: p.id, startS: p.window_start_s as number, endS: p.window_end_s as number }));
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
      return alignPiece(pieceId, piece?.window_activity_id ?? undefined, startS);
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
              className="min-h-9 rounded-md border border-accent bg-surface px-2 text-lg font-semibold text-text-primary"
            />
          ) : (
            <h1
              className="cursor-text text-lg font-semibold text-text-primary"
              onClick={() => {
                setTitleDraft(workout.title ?? "");
                setEditingTitle(true);
              }}
              title="Tap to rename"
            >
              {workout.title ?? "Workout"}
            </h1>
          )}
          <span className="text-sm text-text-tertiary">{categoryLabel(workout.category)}</span>
          {workout.overrides.title && (
            <button type="button" onClick={() => revert.mutate("title")} className="text-xs text-text-tertiary underline hover:text-text-secondary">
              revert to source
            </button>
          )}
        </div>
        <p className="text-sm text-text-tertiary">
          {workout.start ? formatShortDate(workout.start) : "—"}
          {workout.session_label && <span className="ml-2">{workout.session_label}</span>}
          {workout.exclude_from_totals && <span className="ml-2 text-text-tertiary">(excluded from totals)</span>}
        </p>
      </div>

      <Card>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          <Stat label="Distance" value={formatDistance(workout.distance)} />
          <Stat label="Time" value={formatDuration(workout.duration)} />
          {avgSplit && <Stat label="Avg split" value={`${formatSplit(avgSplit)}/500m`} />}
          {workout.avg_power != null && <Stat label="Watts" value={workout.avg_power.toFixed(0)} />}
          {workout.avg_hr != null && <Stat label="Avg HR" value={workout.avg_hr.toFixed(0)} />}
          {workout.avg_cadence != null && <Stat label="Cadence" value={`${workout.avg_cadence.toFixed(0)} spm`} />}
        </div>
        {workout.strain && (
          <div className="mt-4 flex items-center gap-2 border-t border-border pt-3">
            <span className="text-xs text-text-tertiary">Strain</span>
            <BandBadge band={workout.strain.band} label={bandLabel(workout.strain.band)} />
            {workout.strain.value != null && <span className="font-mono-nums text-sm text-text-primary">{workout.strain.value.toFixed(1)}</span>}
            {workout.strain_method?.includes("estimated") && <span className="text-xs text-text-tertiary">(estimated FTP)</span>}
          </div>
        )}
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

      {samples?.has_data && (
        <Card title="Heart rate">
          <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-text-tertiary">
            <span>
              avg <span className="font-mono-nums text-text-primary">{Math.round(samples.avg_hr ?? 0)}</span>
            </span>
            <span>
              max <span className="font-mono-nums text-text-primary">{samples.max_hr_observed}</span>
            </span>
            <span>
              min <span className="font-mono-nums text-text-primary">{samples.min_hr_observed}</span>
            </span>
            {samples.hr_recovery.session_end != null && (
              <span>
                recovery (60s) <span className="font-mono-nums text-text-primary">{samples.hr_recovery.session_end.toFixed(0)}</span> bpm
              </span>
            )}
            {samples.trimmed_tail_s > 0 && <span>watch left running {Math.round(samples.trimmed_tail_s)}s — greyed out, excluded above</span>}
          </div>
          {samples.zones?.hr && (
            <div className="mb-3">
              <ZoneBar zones={samples.zones.hr} height={8} showLegend />
            </div>
          )}
          {(samples.points.some((p) => p.power != null) || samples.points.some((p) => p.cadence != null)) && (
            <div className="mb-2 flex gap-2" role="tablist" aria-label="Overlay">
              {(["none", "power", "cadence"] as const).map((o) => (
                <button
                  key={o}
                  type="button"
                  role="tab"
                  aria-selected={overlay === o}
                  onClick={() => setOverlay(o)}
                  className={`min-h-9 rounded-md border px-3 text-xs ${overlay === o ? "border-accent text-accent" : "border-border text-text-tertiary"}`}
                >
                  {o === "none" ? "HR only" : o === "power" ? "+ Power" : "+ Cadence"}
                </button>
              ))}
            </div>
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
          />
        </Card>
      )}
      {workout.has_samples && samples && !samples.has_data && (
        <Card title="Heart rate">
          <p className="text-sm text-text-tertiary">No heart-rate data for this activity.</p>
        </Card>
      )}

      <Card
        title="Pieces"
        action={
          <button type="button" onClick={() => setAddPieceOpen(true)} className="min-h-9 rounded-md border border-accent px-3 text-xs font-medium text-accent">
            Add piece
          </button>
        }
      >
        {workout?.concept2_interval_activity_id != null && !pieces?.some((p) => p.has_intervals && p.concept2_activity_id === workout.concept2_interval_activity_id) && (
          <button
            type="button"
            disabled={importIntervals.isPending}
            onClick={() => importIntervals.mutate(workout.concept2_interval_activity_id!)}
            className="mb-2 min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary disabled:opacity-50"
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
      <AddPieceDialog open={addPieceOpen} onClose={() => setAddPieceOpen(false)} canonicalId={canonicalId} onSaved={() => setAddPieceOpen(false)} />

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
                      {s.is_rep_pr && <span className="rounded-full bg-accent/20 px-2 py-0.5 text-xs font-semibold text-accent">PR</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}

      <Card title="Edit">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-text-tertiary" htmlFor="wd-sport">
              Sport
            </label>
            <select
              id="wd-sport"
              value={workout.sport_family}
              onChange={(e) => patch.mutate({ sport_family: e.target.value as SportFamily })}
              className="min-h-9 rounded-md border border-border bg-surface px-2 text-sm text-text-primary"
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
            <label className="text-xs text-text-tertiary" htmlFor="wd-tags">
              Tags (comma-separated)
            </label>
            <input
              id="wd-tags"
              defaultValue={workout.tags.join(", ")}
              onBlur={(e) =>
                patch.mutate({ tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })
              }
              placeholder="race, test, technique, cross-training"
              className="min-h-9 flex-1 rounded-md border border-border bg-surface px-2 text-sm text-text-primary"
            />
          </div>

          <div>
            <label className="text-xs text-text-tertiary" htmlFor="wd-notes">
              Notes (this workout)
            </label>
            <textarea
              id="wd-notes"
              defaultValue={workout.notes ?? ""}
              onBlur={(e) => patch.mutate({ notes: e.target.value })}
              placeholder="How did it feel?"
              rows={2}
              className="mt-1 w-full resize-none rounded-md border border-border bg-surface-2 p-2 text-sm text-text-primary placeholder:text-text-tertiary"
            />
          </div>

          <div className="flex items-center gap-3">
            <label className="text-xs text-text-tertiary" htmlFor="wd-rpe">
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
            <p className="mb-2 text-xs text-text-tertiary">Sources — which record each metric came from. Edits never push back to Garmin.</p>
            <ul className="flex flex-col gap-1">
              {workout.sources.map((s) => (
                <li key={s.activity_id} className="flex flex-wrap items-center gap-2 text-xs text-text-secondary">
                  <span className="font-medium text-text-primary">{PROVENANCE_LABELS[s.provenance] ?? s.provenance}</span>
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
