import { todayISO, toISODate } from "../lib/dates";
import { Button } from "../components/ui/Button";
import { controlClass } from "../components/ui/Field";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Segmented } from "../components/ui/Segmented";
import { ChartSkeleton } from "../components/ui/Skeleton";
import { StatTile } from "../components/ui/StatTile";
import { useToast } from "../components/ui/Toast";
import { dateRangeText, padDateRange, quantizePoints } from "../lib/chartFetch";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ChartNavigator } from "../components/charts/ChartNavigator";
import { TrendLineChart } from "../components/charts/TrendLineChart";
import { Sparkline } from "../components/today/Sparkline";
import { Card } from "../components/ui/Card";

import { fetchBody, fetchSeries, postManualWeight } from "../lib/api";
import { RANGE_PRESETS, parseChartUrlState, presetToDomain, writeChartUrlState, type RangePreset } from "../lib/chartRange";
import { formatNumber, formatShortDate } from "../lib/format";
import type { Domain } from "../lib/useChartInteraction";

const DAY_MS = 86_400_000;

const SOURCE_LABELS: Record<string, string> = { withings: "Withings", garmin: "Garmin scale", manual: "a manual entry" };
function sourceLabel(source: string | null | undefined): string {
  if (!source) return "an unknown source";
  return SOURCE_LABELS[source] ?? source;
}



export function BodyPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const now = useMemo(() => new Date(), []);

  // weight and w_per_kg are "stacked together" on this page the same way Trends' main chart
  // and weekly-volume bars are — one shared view domain, interaction spec #6.
  const allQuery = useQuery({
    queryKey: ["series-all", "weight", "w_per_kg"],
    queryFn: () => fetchSeries(["weight", "w_per_kg"], "1900-01-01", todayISO(), 600),
  });
  const weightAll = allQuery.data?.series.weight?.points ?? [];
  const earliestMs = weightAll.length ? new Date(weightAll[0].date + "T00:00:00").getTime() : now.getTime() - 60 * DAY_MS;

  const urlState = parseChartUrlState(params);
  const defaultDomain = useMemo(() => presetToDomain("12w", now, new Date(earliestMs)), [now, earliestMs]);
  const initialDomain: Domain =
    urlState.from && urlState.to
      ? { min: new Date(urlState.from + "T00:00:00").getTime(), max: new Date(urlState.to + "T00:00:00").getTime() }
      : urlState.preset
        ? presetToDomain(urlState.preset, now, new Date(earliestMs))
        : defaultDomain;

  // `domain` updates every pan/zoom frame (live x-scale); `queryDomain` only updates once a
  // gesture settles, which is what the series query keys off — see Trends.tsx's identical
  // split for why (a CPU-throttled pan perf test caught mid-gesture refetches otherwise).
  const [domain, setDomain] = useState<Domain>(initialDomain);
  const [queryDomain, setQueryDomain] = useState<Domain>(initialDomain);

  // Memoized for the same reason Trends.tsx's fullDomain is, including the `queryDomain.min`
  // term — see that component's comment for the metric-switch bug this specifically guards
  // against (this page has no metric switcher, but the same `allQuery`-refetch-shrinks-
  // fullDomain-while-on-a-custom-range hazard applies any time that query's data changes).
  const fullDomain: Domain = useMemo(
    () => ({ min: Math.min(earliestMs, now.getTime() - 7 * DAY_MS, queryDomain.min), max: now.getTime() }),
    [earliestMs, now, queryDomain.min],
  );

  // Re-derives the domain once the real earliestMs loads — see Trends.tsx's identical effect
  // for the full explanation (a cold `?range=all`/`1y`/`6m` load — or even the no-param default —
  // would otherwise permanently stick at the ~60-day mount-time fallback span, since useState's
  // initializer only runs once). Gated on the custom from/to pair, not `urlState.preset` itself —
  // the latter is also null on the no-param default, which skipped this re-derive on the single
  // most common entry point (see Trends.tsx's comment for the full story).
  const lastAppliedEarliestMs = useRef<number | null>(null);
  useEffect(() => {
    if (lastAppliedEarliestMs.current === earliestMs) return;
    lastAppliedEarliestMs.current = earliestMs;
    if (urlState.from && urlState.to) return;
    const next = presetToDomain(urlState.preset ?? "12w", now, new Date(earliestMs));
    setDomain(next);
    setQueryDomain(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [earliestMs]);

  const commitToUrl = useCallback(
    (next: Domain, preset: RangePreset | null) => {
      setParams(
        (prev) =>
          writeChartUrlState(
            prev,
            preset
              ? { preset, from: null, to: null }
              : { preset: null, from: toISODate(new Date(next.min)), to: toISODate(new Date(next.max)) },
          ),
        { replace: true },
      );
    },
    [setParams],
  );

  const onDomainSettled = useCallback(
    (next: Domain) => {
      setQueryDomain(next);
      commitToUrl(next, null);
    },
    [commitToUrl],
  );

  // See Trends.tsx's identical `lastPreset` for why this can't just be `urlState.preset ??
  // "12w"` — the URL's preset clears to null the moment the user pans, so that would always
  // reset to 12w instead of "whatever preset was active before this pan."
  const [lastPreset, setLastPreset] = useState<RangePreset>(urlState.preset ?? "12w");

  const selectPreset = (preset: RangePreset) => {
    const next = presetToDomain(preset, now, new Date(earliestMs));
    setDomain(next);
    setQueryDomain(next);
    setLastPreset(preset);
    commitToUrl(next, preset);
  };
  const resetDomain = () => selectPreset(lastPreset);

  const padded = padDateRange(queryDomain, fullDomain);
  const points = quantizePoints(600);
  const seriesQuery = useQuery({
    queryKey: ["series", "weight,w_per_kg", padded.from, padded.to, points],
    queryFn: () => fetchSeries(["weight", "w_per_kg"], padded.from, padded.to, points),
    placeholderData: keepPreviousData,
  });
  const weightPoints = seriesQuery.data?.series.weight?.points ?? [];
  const wPerKgPoints = seriesQuery.data?.series.w_per_kg?.points ?? [];
  // Memoized for the same reason Trends.tsx's navigatorBackdrop is — see that comment.
  const navigatorBackdrop = useMemo(
    () => weightAll.map((p) => ({ x: new Date(p.date + "T00:00:00").getTime(), y: p.value })),
    [weightAll],
  );

  const queryClient = useQueryClient();
  const bodyQuery = useQuery({ queryKey: ["body"], queryFn: () => fetchBody() });
  const readings = bodyQuery.data ?? [];
  const latest = readings[readings.length - 1];

  const [manualDate, setManualDate] = useState(todayISO());
  const [manualWeight, setManualWeight] = useState("");
  const [manualUnit, setManualUnit] = useState<"kg" | "lb">("kg");
  const { toast } = useToast();
  // Session 35: a mutation (it was hand-rolled async + useState), so pending/error state comes from one place.
  const manual = useMutation({
    // Session 34: sent as entered; the server converts pounds to kilograms (the one conversion, catch/analytics/units.py).
    mutationFn: () => postManualWeight(manualDate, Number(manualWeight), manualUnit),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["body"] }),
        queryClient.invalidateQueries({ queryKey: ["series"] }),
        queryClient.invalidateQueries({ queryKey: ["series-all"] }),
      ]);
      setManualWeight("");
      toast("Weight added");
    },
  });
  const submitManualWeight = (e: FormEvent) => {
    e.preventDefault();
    const value = Number(manualWeight);
    if (!Number.isFinite(value) || value <= 0) return;
    manual.mutate();
  };
  const manualError = manual.isError ? (manual.error instanceof Error ? manual.error.message : "Couldn't save that weight.") : null;
  const fatSpark = useMemo(() => readings.map((r) => ({ date: r.date, value: r.fat_pct })), [readings]);
  const muscleSpark = useMemo(() => readings.map((r) => ({ date: r.date, value: r.muscle_kg })), [readings]);
  const latestWeight = weightPoints.length ? weightPoints[weightPoints.length - 1] : null;

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader eyebrow="Health" title="Body" subtitle="Weight, composition and power for your size — one resolved reading per day." />

      <div className="grid grid-cols-3 gap-3 rounded-lg border border-border bg-surface p-4 shadow-[var(--highlight),var(--shadow-1)]">
        <StatTile label="Weight" value={latestWeight ? latestWeight.value.toFixed(1) : "—"} unit="kg" sub={latestWeight ? formatShortDate(latestWeight.date) : "No reading"} />
        <StatTile label="Body fat" value={latest?.fat_pct != null ? formatNumber(latest.fat_pct, 1) : "—"} unit="%" sub={latest?.fat_pct != null ? sourceLabel(latest.fat_pct_source) : "No reading"} />
        <StatTile label="Muscle" value={latest?.muscle_kg != null ? formatNumber(latest.muscle_kg, 1) : "—"} unit="kg" sub={latest?.muscle_kg != null ? sourceLabel(latest.muscle_kg_source) : "No reading"} />
      </div>

      <Segmented label="Range" size="sm" value={urlState.preset ?? ""} onChange={(v) => selectPreset(v as RangePreset)} options={RANGE_PRESETS.map((r) => ({ value: r.value, label: r.label }))} className="self-start" />

      <Card title="Weight">
        {seriesQuery.isError && weightPoints.length === 0 ? (
          <ErrorState message="Couldn't load your weight history." onRetry={() => seriesQuery.refetch()} />
        ) : seriesQuery.isLoading && weightPoints.length === 0 ? (
          <ChartSkeleton height={240} />
        ) : weightPoints.length > 0 ? (
          <>
            <TrendLineChart
              color="var(--metric-sleep)"
              points={weightPoints}
              secondaryKey="smoothed"
              formatValue={(v) => `${v.toFixed(1)}kg`}
              domain={domain}
              fullDomain={fullDomain}
              onDomainChange={setDomain}
              onDomainSettled={onDomainSettled}
              onResetDomain={resetDomain}
            />
            <div className="mt-3">
              <ChartNavigator
                fullDomain={fullDomain}
                viewDomain={domain}
                minSpan={7 * DAY_MS}
                onChange={setDomain}
                onChangeSettled={onDomainSettled}
                backdrop={navigatorBackdrop}
                valueText={dateRangeText}
              />
            </div>
            <p className="mt-2 text-xs text-text-tertiary">
              Solid = raw readings. Dashed = 7-day smoothed (a single-day outlier doesn't move it).
              {weightPoints[weightPoints.length - 1]?.source && (
                <> Latest from {sourceLabel(weightPoints[weightPoints.length - 1].source)}.</>
              )}
            </p>
          </>
        ) : (
          <EmptyState message="No weight data yet — connect Withings or a Garmin scale, or add one below." />
        )}
        <form onSubmit={submitManualWeight} className="mt-4 flex flex-wrap items-end gap-3 border-t border-border pt-4">
          <div>
            <label htmlFor="manual-weight-date" className="mb-1 block text-xs font-medium text-text-secondary">
              Date
            </label>
            <input
              id="manual-weight-date"
              type="date"
              value={manualDate}
              onChange={(e) => setManualDate(e.target.value)}
              className={`${controlClass} w-auto`}
            />
          </div>
          <div>
            <label htmlFor="manual-weight-kg" className="mb-1 block text-xs font-medium text-text-secondary">
              Weight
            </label>
            <div className="flex gap-1">
              <input
                id="manual-weight-kg"
                type="number"
                step="0.1"
                inputMode="decimal"
                value={manualWeight}
                onChange={(e) => setManualWeight(e.target.value)}
                placeholder={manualUnit === "kg" ? "79.0" : "174.0"}
                className={`${controlClass} w-28 font-mono-nums`}
              />
              <select
                aria-label="Weight unit"
                value={manualUnit}
                onChange={(e) => setManualUnit(e.target.value as "kg" | "lb")}
                className={`${controlClass} w-auto`}
                data-testid="manual-weight-unit"
              >
                <option value="kg">kg</option>
                <option value="lb">lb</option>
              </select>
            </div>
          </div>
          <Button type="submit" variant="primary" loading={manual.isPending} disabled={!manualWeight}>
            Add manual weight
          </Button>
          <span className="basis-full text-xs text-text-tertiary">Always the last-resort source — a real scale reading wins if one exists that day. Pounds are stored as kilograms.</span>
          {manualError && <p role="alert" className="w-full text-sm text-band-red-text">{manualError}</p>}
        </form>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="Body fat %">
          {latest?.fat_pct != null ? (
            <>
              <div className="font-mono-nums text-[2rem] font-semibold leading-none tracking-tight text-text-primary">{formatNumber(latest.fat_pct, 1)}%</div>
              <div className="mt-1 text-xs text-text-tertiary">from {sourceLabel(latest.fat_pct_source)}</div>
              <div className="mt-3">
                <Sparkline points={fatSpark} baselineBand={null} color="var(--metric-sleep)" label="Body fat" format={(v) => `${v.toFixed(1)}%`} />
              </div>
            </>
          ) : (
            <EmptyState message="No body-fat data yet." />
          )}
        </Card>
        <Card title="Muscle mass">
          {latest?.muscle_kg != null ? (
            <>
              <div className="font-mono-nums text-[2rem] font-semibold leading-none tracking-tight text-text-primary">{formatNumber(latest.muscle_kg, 1)}kg</div>
              <div className="mt-1 text-xs text-text-tertiary">from {sourceLabel(latest.muscle_kg_source)}</div>
              <div className="mt-3">
                <Sparkline points={muscleSpark} baselineBand={null} color="var(--metric-rate)" label="Muscle mass" format={(v) => `${v.toFixed(1)} kg`} />
              </div>
            </>
          ) : (
            <EmptyState message="No muscle-mass data yet." />
          )}
        </Card>
      </div>

      <Card title="W/kg over time">
        {seriesQuery.isLoading && wPerKgPoints.length === 0 ? (
          <ChartSkeleton height={240} />
        ) : wPerKgPoints.length > 0 ? (
          <TrendLineChart
            color="var(--metric-power)"
            points={wPerKgPoints}
            formatValue={(v) => v.toFixed(2)}
            domain={domain}
            fullDomain={fullDomain}
            onDomainChange={setDomain}
            onDomainSettled={onDomainSettled}
            onResetDomain={resetDomain}
            showBand={false}
            onPointTap={(point) => {
              if (point.activity_id != null) navigate(`/workouts/${point.activity_id}`);
            }}
          />
        ) : (
          <EmptyState message="No erg power + weight pairing yet." />
        )}
      </Card>
    </div>
  );
}
