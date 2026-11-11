import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchOnWater, fetchTrack, setActivityRoute } from "../../lib/api";
import { formatDuration } from "../../lib/format";
import { formatKm, formatMmSs, formatPace, formatSpeedKmh, paceUnitLabel, splitChoices } from "../../lib/gpsFormat";
import type { LapRow, OnWaterData, SplitRow, TrackData, WorkoutCategory } from "../../lib/types";
import { LazyRouteMap } from "../maps/LazyRouteMap";
import type { MapLine } from "../maps/RouteMap";
import { Card } from "../ui/Card";
import { GpsBadge } from "./GpsBadge";
import { TrackChart, type TrackMetric } from "./TrackChart";
import { WeatherCard } from "./WeatherCard";

function Fig({ label, value, sub, source }: { label: string; value: string; sub?: string; source?: "gps_derived" | "provider" }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-xs text-text-tertiary">
        {label}
        {source && <GpsBadge source={source} />}
      </div>
      <div className="font-mono-nums text-base font-medium text-text-primary">{value}</div>
      {sub && <div className="text-xs text-text-tertiary">{sub}</div>}
    </div>
  );
}

function Segmented<T extends string | number>({ options, value, onChange, label }: { options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="flex flex-wrap gap-2" role="tablist" aria-label={label}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={`min-h-9 rounded-md border px-3 text-xs ${value === o.value ? "border-accent text-accent" : "border-border text-text-tertiary"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function RouteChip({ canonicalId, data, rowing }: { canonicalId: number; data: OnWaterData; rowing: boolean }) {
  const queryClient = useQueryClient();
  const change = useMutation({
    mutationFn: (body: Parameters<typeof setActivityRoute>[1]) => setActivityRoute(canonicalId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["on-water", canonicalId] }),
  });
  if (!rowing) return null;
  const route = data.route;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3 text-sm" data-testid="route-chip">
      {route ? (
        <>
          <span className="text-text-tertiary">Repeated route</span>
          <Link to={`/routes/${route.id}`} className="font-medium text-accent underline">
            {route.display_name}
          </Link>
          <span className="text-xs text-text-tertiary">
            {route.n_sessions ?? "?"} sessions · {formatKm(route.length_m, 1)} <GpsBadge source={route.length_source} />
          </span>
          <button type="button" disabled={change.isPending} onClick={() => change.mutate({ route_id: null })} className="min-h-9 text-xs text-text-tertiary underline disabled:opacity-50">
            Not this route
          </button>
        </>
      ) : (
        <>
          <span className="text-text-tertiary">Not part of a repeated route yet — a route forms once two sessions follow the same course.</span>
          <button
            type="button"
            disabled={change.isPending}
            onClick={() => change.mutate({ new_route: true })}
            className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary disabled:opacity-50"
          >
            Save this course as a route
          </button>
        </>
      )}
    </div>
  );
}

function MetricsCard({ data }: { data: OnWaterData }) {
  const m = data.metrics;
  const unit = data.pace.unit;
  const prov = m.provider;
  const delta = m.distance_delta_vs_provider_pct;
  const cons = data.splits.consistency;
  return (
    <Card title="GPS metrics">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Fig label="Distance" value={formatKm(m.distance_m.value)} source="gps_derived" />
        <Fig label="Moving time" value={formatDuration(m.moving_s.value)} sub={`elapsed ${formatDuration(m.elapsed_s.value)}`} source="gps_derived" />
        <Fig label="Avg speed" value={formatSpeedKmh(m.avg_speed_mps.value)} sub="while moving" source="gps_derived" />
        <Fig label="Avg pace" value={formatPace(unit, data.pace.value)} sub="while moving" source="gps_derived" />
        <Fig label="Peak speed" value={formatSpeedKmh(m.peak_speed_mps.value)} sub="best ~10 s" source="gps_derived" />
        <Fig
          label="Pace consistency"
          value={cons?.cv_pct != null ? `${cons.cv_pct.toFixed(1)}% CV` : "—"}
          sub={cons ? `${cons.n_splits} clean splits, ±${cons.split_time_sd_s.toFixed(1)} s` : "needs at least 4 clean splits"}
          source={cons ? "gps_derived" : undefined}
        />
      </div>
      <div className="mt-3 border-t border-border pt-3" data-testid="provider-figures">
        <div className="mb-1 flex items-center gap-2 text-xs text-text-tertiary">
          What Garmin reported <GpsBadge source="provider" />
        </div>
        <p className="font-mono-nums text-sm text-text-primary">
          {prov.distance_m ? formatKm(prov.distance_m.value) : "no distance"}
          {prov.moving_s ? ` · ${formatDuration(prov.moving_s.value)} moving` : ""}
          {prov.max_speed_mps ? ` · max ${formatSpeedKmh(prov.max_speed_mps.value)}` : ""}
        </p>
        {delta != null && (
          <p className="mt-1 text-xs text-text-tertiary">
            GPS distance is {delta >= 0 ? "+" : ""}
            {delta.toFixed(1)}% vs Garmin's. Both are shown — neither replaces the other. Garmin's average speed is over elapsed time; GPS elapsed-basis average is {formatSpeedKmh(m.avg_speed_elapsed_mps.value)}.
          </p>
        )}
      </div>
      <details className="mt-3 text-xs text-text-tertiary">
        <summary className="min-h-9 cursor-pointer py-2">How the GPS track was filtered</summary>
        <ul className="mt-1 list-disc pl-5" data-testid="filter-report">
          <li>{m.filter_report.points_in} fixes read</li>
          <li>{m.filter_report.dropped_no_fix} without a usable position dropped</li>
          <li>{m.filter_report.dropped_duplicate_time + m.filter_report.dropped_out_of_order} with a repeated or backwards timestamp dropped</li>
          <li>{m.filter_report.dropped_jump} implausible jumps dropped (faster than {m.filter_report.ceiling_mps} m/s)</li>
          <li>
            {m.filter_report.gaps} gap{m.filter_report.gaps === 1 ? "" : "s"} ({Math.round(m.filter_report.gap_seconds)} s) — distance is never filled in across a gap
          </li>
          {m.filter_report.accuracy_reported === false && <li>This device doesn't report GPS accuracy.</li>}
        </ul>
      </details>
      <p className="mt-2 text-xs text-text-tertiary" data-testid="environment-note">
        {data.environment_note}
      </p>
    </Card>
  );
}

function SplitsCard({ data, sport, splitM, onSplitM }: { data: OnWaterData; sport: string; splitM: number | undefined; onSplitM: (m: number) => void }) {
  const choices = splitChoices(sport);
  const current = splitM ?? data.splits.split_m;
  const options = choices.includes(current) ? choices : [...choices, current].sort((a, b) => a - b);
  const unit = data.pace.unit;
  return (
    <Card title="Splits" action={<GpsBadge source="gps_derived" />}>
      <div className="mb-3">
        <Segmented label="Split distance" value={current} onChange={onSplitM} options={options.map((v) => ({ value: v, label: v >= 1000 ? `${v / 1000} km` : `${v} m` }))} />
      </div>
      {data.splits.splits.length === 0 ? (
        <p className="text-sm text-text-tertiary">Not enough GPS distance for a split.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="splits-table">
            <thead>
              <tr className="text-left text-xs text-text-tertiary">
                <th className="py-1 pr-3 font-normal">#</th>
                <th className="py-1 pr-3 font-normal">Time</th>
                <th className="py-1 pr-3 font-normal">{paceUnitLabel(unit) === "km/h" ? "Speed" : "Pace"}</th>
                <th className="py-1 pr-3 font-normal">HR</th>
                <th className="py-1 font-normal" />
              </tr>
            </thead>
            <tbody className="font-mono-nums">
              {data.splits.splits.map((s: SplitRow) => (
                <tr key={s.index} className="border-t border-border">
                  <td className="py-1.5 pr-3 text-text-tertiary">{s.index}</td>
                  <td className="py-1.5 pr-3 text-text-primary">{formatMmSs(s.time_s)}</td>
                  <td className="py-1.5 pr-3 text-text-primary">{formatPace(s.pace.unit, s.pace.value)}</td>
                  <td className="py-1.5 pr-3 text-text-secondary">{s.avg_hr != null ? Math.round(s.avg_hr) : "—"}</td>
                  <td className="py-1.5 text-xs text-text-tertiary">
                    {s.partial ? `partial ${Math.round(s.distance_m)} m` : ""}
                    {s.has_gap ? " spans a GPS gap" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-xs text-text-tertiary">Each boundary is the time the GPS distance reached a multiple of the split, interpolated between fixes. {data.splits.method}.</p>
    </Card>
  );
}

function LapsCard({ data }: { data: OnWaterData }) {
  if (!data.laps.usable) return null;
  const unit = data.pace.unit;
  return (
    <Card title="Laps">
      <div className="overflow-x-auto">
        <table className="w-full text-sm" data-testid="laps-table">
          <thead>
            <tr className="text-left text-xs text-text-tertiary">
              <th className="py-1 pr-3 font-normal">#</th>
              <th className="py-1 pr-3 font-normal">Time</th>
              <th className="py-1 pr-3 font-normal">
                Distance <GpsBadge source="gps_derived" />
              </th>
              <th className="py-1 pr-3 font-normal">
                Garmin <GpsBadge source="provider" />
              </th>
              <th className="py-1 font-normal">Pace</th>
            </tr>
          </thead>
          <tbody className="font-mono-nums">
            {data.laps.rows.map((l: LapRow, i: number) => (
              <tr key={i} className="border-t border-border">
                <td className="py-1.5 pr-3 text-text-tertiary">{i + 1}</td>
                <td className="py-1.5 pr-3 text-text-primary">{formatMmSs(l.duration_s)}</td>
                <td className="py-1.5 pr-3 text-text-primary">{formatKm(l.gps_distance_m)}</td>
                <td className="py-1.5 pr-3 text-text-secondary">{l.provider.distance_m != null ? formatKm(l.provider.distance_m) : "—"}</td>
                <td className="py-1.5 text-text-primary">
                  {unit === "km_per_h" ? formatSpeedKmh(l.gps_avg_speed_mps) : formatPace(unit, l.gps_avg_speed_mps ? (unit === "s_per_500m" ? 500 : 1000) / l.gps_avg_speed_mps : null)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function trackToLines(track: TrackData): { lines: MapLine[]; range: [number, number] | null } {
  const segments: MapLine["segments"] = [];
  let cur: { coords: [number, number][]; speeds: number[] } | null = null;
  let lastSeg = -1;
  for (const p of track.points) {
    if (!cur || p.segment !== lastSeg) {
      cur = { coords: [], speeds: [] };
      segments.push(cur);
      lastSeg = p.segment;
    }
    cur.coords.push([p.lat, p.lon]);
    cur.speeds.push(p.speed_mps);
  }
  const speeds = track.points.map((p) => p.speed_mps).filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  const range: [number, number] | null = speeds.length > 3 ? [speeds[Math.floor(speeds.length * 0.05)], speeds[Math.floor(speeds.length * 0.95)]] : null;
  return { lines: [{ id: "track", segments, endpoints: true }], range };
}

/** Everything GPS on a workout's page. Renders nothing for an activity that isn't outdoor and has
 * no track (an erg, a lift); an on-water row *without* GPS gets an explicit fallback instead. */
export function GpsSection({ canonicalId, category, hasTrack, sportFamily }: { canonicalId: number; category: WorkoutCategory; hasTrack: boolean; sportFamily: string }) {
  const wanted = hasTrack || category === "on_water";
  const [splitM, setSplitM] = useState<number | undefined>(undefined);
  const [metric, setMetric] = useState<TrackMetric>("pace");
  const [xAxis, setXAxis] = useState<"time" | "distance">("time");
  const [hoverS, setHoverS] = useState<number | null>(null);

  const { data: track } = useQuery({ queryKey: ["track", canonicalId], queryFn: () => fetchTrack(canonicalId, 600), enabled: wanted });
  const { data: ow } = useQuery({ queryKey: ["on-water", canonicalId, splitM ?? null], queryFn: () => fetchOnWater(canonicalId, splitM), enabled: wanted, placeholderData: (prev) => prev });

  const mapData = useMemo(() => (track?.has_track ? trackToLines(track) : null), [track]);
  const hoverPoint = useMemo(() => {
    if (hoverS == null || !track?.has_track) return null;
    let best = track.points[0];
    for (const p of track.points) if (Math.abs(p.elapsed_s - hoverS) < Math.abs(best.elapsed_s - hoverS)) best = p;
    return { lat: best.lat, lon: best.lon };
  }, [hoverS, track]);

  if (!wanted) return null;
  if (!track || !ow) return <Card title="Route & GPS"><p className="text-sm text-text-tertiary">Loading GPS…</p></Card>;

  if (!track.has_track || !ow.has_track) {
    return (
      <Card title="Route & GPS">
        <p className="text-sm text-text-secondary" data-testid="no-gps">
          {track.has_track ? "No GPS track." : track.message}
        </p>
        <p className="mt-1 text-xs text-text-tertiary">Nothing here is estimated — distance, speed and the map need the watch's own GPS fixes.</p>
      </Card>
    );
  }

  const rowing = sportFamily === "rowing";
  const hasElevation = track.has_elevation;
  const metrics: TrackMetric[] = hasElevation ? ["pace", "speed", "elevation"] : ["pace", "speed"];

  return (
    <>
      <Card title="Route" action={<GpsBadge source="gps_derived" />}>
        {mapData && <LazyRouteMap lines={mapData.lines} speedRange={mapData.range} hover={hoverPoint} label="Route map" />}
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-tertiary" data-testid="map-legend">
          <span>Ring = start, solid dot = finish</span>
          {mapData?.range && (
            <span>
              line: thin &amp; faint = slow ({formatSpeedKmh(mapData.range[0])}), thick &amp; solid = fast ({formatSpeedKmh(mapData.range[1])})
            </span>
          )}
        </div>
        <RouteChip canonicalId={canonicalId} data={ow} rowing={rowing} />
      </Card>

      <MetricsCard data={ow} />

      <Card title="Speed & pace" action={<GpsBadge source="gps_derived" />}>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <Segmented label="Metric" value={metric} onChange={setMetric} options={metrics.map((v) => ({ value: v, label: v === "pace" ? "Pace" : v === "speed" ? "Speed" : "Elevation" }))} />
          <Segmented label="X axis" value={xAxis} onChange={setXAxis} options={[{ value: "time", label: "Time" }, { value: "distance", label: "Distance" }]} />
        </div>
        <TrackChart points={track.points} metric={metric} xAxis={xAxis} paceUnit={track.pace_unit} onHoverElapsed={setHoverS} />
        <p className="mt-1 text-xs text-text-tertiary">
          {metric === "elevation" ? "Elevation as recorded by the watch." : "Computed from consecutive GPS fixes, lightly smoothed for display."} Heart rate is in the chart above. Hover or drag across the chart to see the point on the map.
        </p>
      </Card>

      <SplitsCard data={ow} sport={sportFamily} splitM={splitM} onSplitM={setSplitM} />
      <LapsCard data={ow} />
      {!ow.laps.usable && ow.laps.note && <p className="px-1 text-xs text-text-tertiary">{ow.laps.note}</p>}
      <WeatherCard canonicalId={canonicalId} />
    </>
  );
}
