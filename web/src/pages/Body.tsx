import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ChartNavigator } from "../components/charts/ChartNavigator";
import { TrendLineChart } from "../components/charts/TrendLineChart";
import { Sparkline } from "../components/today/Sparkline";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { fetchBody, fetchSeries, postManualWeight } from "../lib/api";
import { RANGE_PRESETS, parseChartUrlState, presetToDomain, writeChartUrlState, type RangePreset } from "../lib/chartRange";
import { formatNumber } from "../lib/format";
import type { Domain } from "../lib/useChartInteraction";

const DAY_MS = 86_400_000;

const SOURCE_LABELS: Record<string, string> = { withings: "Withings", garmin: "Garmin scale", manual: "a manual entry" };
function sourceLabel(source: string | null | undefined): string {
  if (!source) return "an unknown source";
  return SOURCE_LABELS[source] ?? source;
}

function quantizePoints(plotWidthPx: number): number {
  return Math.min(2000, Math.max(200, Math.ceil((plotWidthPx * 2) / 100) * 100));
}

function padDomain(domain: Domain, full: Domain): { from: string; to: string } {
  const span = domain.max - domain.min;
  const min = Math.max(full.min, domain.min - span);
  const max = Math.min(full.max, domain.max + span);
  return { from: new Date(min).toISOString().slice(0, 10), to: new Date(max).toISOString().slice(0, 10) };
}

export function BodyPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const now = useMemo(() => new Date(), []);

  // weight and w_per_kg are "stacked together" on this page the same way Trends' main chart
  // and weekly-volume bars are — one shared view domain, interaction spec #6.
  const allQuery = useQuery({
    queryKey: ["series-all", "weight", "w_per_kg"],
    queryFn: () => fetchSeries(["weight", "w_per_kg"], "1900-01-01", now.toISOString().slice(0, 10), 600),
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
              : { preset: null, from: new Date(next.min).toISOString().slice(0, 10), to: new Date(next.max).toISOString().slice(0, 10) },
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

  const padded = padDomain(queryDomain, fullDomain);
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

  const [manualDate, setManualDate] = useState(now.toISOString().slice(0, 10));
  const [manualWeight, setManualWeight] = useState("");
  const [savingManual, setSavingManual] = useState(false);
  const submitManualWeight = async (e: FormEvent) => {
    e.preventDefault();
    const kg = Number(manualWeight);
    if (!Number.isFinite(kg) || kg <= 0) return;
    setSavingManual(true);
    try {
      await postManualWeight(manualDate, kg);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["body"] }),
        queryClient.invalidateQueries({ queryKey: ["series"] }),
        queryClient.invalidateQueries({ queryKey: ["series-all"] }),
      ]);
      setManualWeight("");
    } finally {
      setSavingManual(false);
    }
  };
  const fatSpark = readings.map((r) => ({ date: r.date, value: r.fat_pct }));
  const muscleSpark = readings.map((r) => ({ date: r.date, value: r.muscle_kg }));

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <h1 className="text-lg font-semibold text-text-primary">Body</h1>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Range">
        {RANGE_PRESETS.map((r) => (
          <button
            key={r.value}
            type="button"
            role="tab"
            aria-selected={urlState.preset === r.value}
            onClick={() => selectPreset(r.value)}
            className={`min-h-11 rounded-md border px-3.5 text-sm transition-colors ${
              urlState.preset === r.value ? "border-accent text-accent" : "border-border text-text-tertiary hover:text-text-secondary"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>

      <Card title="Weight">
        {seriesQuery.isLoading && weightPoints.length === 0 ? (
          <div className="h-40 animate-pulse rounded-md bg-surface-2" aria-hidden />
        ) : weightPoints.length > 0 ? (
          <>
            <TrendLineChart
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
        <form onSubmit={submitManualWeight} className="mt-4 flex flex-wrap items-end gap-2 border-t border-border pt-3">
          <div>
            <label htmlFor="manual-weight-date" className="block text-xs text-text-tertiary">
              Date
            </label>
            <input
              id="manual-weight-date"
              type="date"
              value={manualDate}
              onChange={(e) => setManualDate(e.target.value)}
              className="min-h-9 rounded-md border border-border bg-surface px-2 text-sm text-text-primary"
            />
          </div>
          <div>
            <label htmlFor="manual-weight-kg" className="block text-xs text-text-tertiary">
              Weight (kg)
            </label>
            <input
              id="manual-weight-kg"
              type="number"
              step="0.1"
              inputMode="decimal"
              value={manualWeight}
              onChange={(e) => setManualWeight(e.target.value)}
              placeholder="79.0"
              className="min-h-9 w-24 rounded-md border border-border bg-surface px-2 text-sm text-text-primary"
            />
          </div>
          <button
            type="submit"
            disabled={savingManual || !manualWeight}
            className="min-h-9 rounded-md border border-accent bg-accent px-3 text-sm font-medium text-accent-contrast disabled:opacity-40"
          >
            Add manual weight
          </button>
          <span className="text-xs text-text-tertiary">Always the last-resort source — a real scale reading wins if one exists that day.</span>
        </form>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="Body fat %">
          {latest?.fat_pct != null ? (
            <>
              <div className="font-mono-nums text-3xl font-semibold text-text-primary">{formatNumber(latest.fat_pct, 1)}%</div>
              <div className="text-xs text-text-tertiary">from {sourceLabel(latest.fat_pct_source)}</div>
              <div className="mt-3">
                <Sparkline points={fatSpark} baselineBand={null} />
              </div>
            </>
          ) : (
            <EmptyState message="No body-fat data yet." />
          )}
        </Card>
        <Card title="Muscle mass">
          {latest?.muscle_kg != null ? (
            <>
              <div className="font-mono-nums text-3xl font-semibold text-text-primary">{formatNumber(latest.muscle_kg, 1)}kg</div>
              <div className="text-xs text-text-tertiary">from {sourceLabel(latest.muscle_kg_source)}</div>
              <div className="mt-3">
                <Sparkline points={muscleSpark} baselineBand={null} />
              </div>
            </>
          ) : (
            <EmptyState message="No muscle-mass data yet." />
          )}
        </Card>
      </div>

      <Card title="W/kg over time">
        {seriesQuery.isLoading && wPerKgPoints.length === 0 ? (
          <div className="h-40 animate-pulse rounded-md bg-surface-2" aria-hidden />
        ) : wPerKgPoints.length > 0 ? (
          <TrendLineChart
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
