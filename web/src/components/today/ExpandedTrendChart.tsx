import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { fetchSeries } from "../../lib/api";
import { RANGE_PRESETS, presetToDomain, type RangePreset } from "../../lib/chartRange";
import type { TrendMetric } from "../../lib/types";
import type { Domain } from "../../lib/useChartInteraction";
import { TrendLineChart } from "../charts/TrendLineChart";

const DAY_MS = 86_400_000;

// The Today screen's HRV/resting-HR sparklines expand into this — a full interactive chart in
// a dialog, lazy-loaded (`React.lazy` in VitalsCard) since Today is the one eager route.
export default function ExpandedTrendChart({ metric, formatValue }: { metric: TrendMetric; formatValue: (v: number) => string }) {
  const now = useMemo(() => new Date(), []);
  const [preset, setPreset] = useState<RangePreset>("12w");

  const allQuery = useQuery({
    queryKey: ["series-all", metric],
    queryFn: () => fetchSeries([metric], "1900-01-01", now.toISOString().slice(0, 10), 400),
  });
  const allPoints = allQuery.data?.series[metric]?.points ?? [];
  const earliestMs = allPoints.length ? new Date(allPoints[0].date + "T00:00:00").getTime() : now.getTime() - 84 * DAY_MS;
  // Memoized for the same reason Trends.tsx's fullDomain is (see that component's comment) —
  // a stable object identity across pan/zoom re-renders.
  const fullDomain: Domain = useMemo(() => ({ min: Math.min(earliestMs, now.getTime() - 7 * DAY_MS), max: now.getTime() }), [earliestMs, now]);

  // `domain` updates every pan/zoom frame (live x-scale); `queryDomain` only updates once a
  // gesture settles — see Trends.tsx's identical split for why (a CPU-throttled pan perf test
  // caught mid-gesture refetches spiking frame time otherwise).
  const [domain, setDomain] = useState<Domain>(() => presetToDomain(preset, now, new Date(earliestMs)));
  const [queryDomain, setQueryDomain] = useState<Domain>(() => presetToDomain(preset, now, new Date(earliestMs)));

  // Re-derives the domain once the real earliestMs loads (see Trends.tsx's identical effect
  // for the full explanation) — the mount-time default here happens to match "12w"'s fallback
  // exactly, but a user picking "1y"/"all" before `allQuery` resolves would otherwise stick at
  // the narrower fallback span forever.
  const lastAppliedEarliestMs = useRef<number | null>(null);
  useEffect(() => {
    if (lastAppliedEarliestMs.current === earliestMs) return;
    lastAppliedEarliestMs.current = earliestMs;
    const next = presetToDomain(preset, now, new Date(earliestMs));
    setDomain(next);
    setQueryDomain(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [earliestMs]);

  const selectPreset = (next: RangePreset) => {
    setPreset(next);
    const nextDomain = presetToDomain(next, now, new Date(earliestMs));
    setDomain(nextDomain);
    setQueryDomain(nextDomain);
  };

  const span = queryDomain.max - queryDomain.min;
  const from = new Date(Math.max(fullDomain.min, queryDomain.min - span)).toISOString().slice(0, 10);
  const to = new Date(Math.min(fullDomain.max, queryDomain.max + span)).toISOString().slice(0, 10);
  const seriesQuery = useQuery({
    queryKey: ["series", metric, from, to, 400],
    queryFn: () => fetchSeries([metric], from, to, 400),
    placeholderData: keepPreviousData,
  });
  const points = seriesQuery.data?.series[metric]?.points ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-1.5 overflow-x-auto">
        {RANGE_PRESETS.filter((r) => r.value !== "season").map((r) => (
          <button
            key={r.value}
            type="button"
            onClick={() => selectPreset(r.value)}
            className={`min-h-9 rounded-md border px-2.5 text-xs transition-colors ${
              preset === r.value ? "border-accent text-accent" : "border-border text-text-tertiary hover:text-text-secondary"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>
      {points.length > 0 ? (
        <TrendLineChart
          points={points}
          formatValue={formatValue}
          domain={domain}
          fullDomain={fullDomain}
          onDomainChange={setDomain}
          onDomainSettled={setQueryDomain}
          onResetDomain={() => selectPreset(preset)}
        />
      ) : (
        <div className="flex h-40 items-center justify-center text-sm text-text-tertiary">Not enough history yet.</div>
      )}
    </div>
  );
}
