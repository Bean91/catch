import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchActivitySamples, fetchErgStrokes, fetchSettings, fetchWorkoutDetail, patchActivity, revertActivityField, splitActivity } from "../lib/api";
import { bandLabel, categoryLabel, formatDistance, formatDuration, formatShortDate, formatSplit } from "../lib/format";
import type { Domain } from "../lib/useChartInteraction";
import type { EditableActivityField, SportFamily } from "../lib/types";
import { ErgChart } from "../components/charts/ErgChart";
import { HrChart } from "../components/charts/HrChart";
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
  const { data: samples } = useQuery({
    queryKey: ["activity-samples", canonicalId],
    queryFn: () => fetchActivitySamples(canonicalId, { points: 800 }),
    enabled: !!workout && workout.has_samples,
  });
  const hrFullDomain: Domain | null = samples?.has_data ? { min: 0, max: Math.max(samples.n_samples, 1) } : null;
  const [hrDomain, setHrDomain] = useState<Domain | null>(null);
  const effectiveHrDomain = hrDomain ?? hrFullDomain ?? { min: 0, max: 1 };
  const resetHrDomain = () => setHrDomain(hrFullDomain);
  const [overlay, setOverlay] = useState<"none" | "power" | "cadence">("none");

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
            points={samples.points}
            zonesConfig={samples.zones_config}
            maxHrSetting={samples.max_hr_setting}
            avgHr={samples.avg_hr}
            laps={samples.laps}
            trimmedTailS={samples.trimmed_tail_s}
            overlay={overlay}
            domain={effectiveHrDomain}
            fullDomain={hrFullDomain ?? { min: 0, max: 1 }}
            onDomainChange={setHrDomain}
            onResetDomain={resetHrDomain}
          />
        </Card>
      )}
      {workout.has_samples && samples && !samples.has_data && (
        <Card title="Heart rate">
          <p className="text-sm text-text-tertiary">No heart-rate data for this activity.</p>
        </Card>
      )}

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
