import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchWorkoutWeather, refreshWorkoutWeather } from "../../lib/api";
import type { WeatherResponse, WeatherSummary } from "../../lib/types";
import { Card } from "../ui/Card";

function WindArrow({ fromDeg }: { fromDeg: number }) {
  // Meteorological direction is where the wind blows FROM; the arrow points where it blows TO.
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" className="shrink-0">
      <g transform={`rotate(${fromDeg + 180} 11 11)`}>
        <path d="M11 3 L16 17 L11 14 L6 17 Z" fill="var(--accent)" />
      </g>
    </svg>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-1.5 last:border-b-0">
      <dt className="text-sm text-text-tertiary">{label}</dt>
      <dd className="text-right font-mono-nums text-sm text-text-primary">{children}</dd>
    </div>
  );
}

const MISSING = <span className="text-text-tertiary">not available</span>;

function num(v: number | null | undefined, digits: number, unit: string) {
  return v == null ? MISSING : `${v.toFixed(digits)} ${unit}`;
}

export function weatherChip(w: WeatherSummary): string {
  const parts: string[] = [];
  if (w.temperature_c.avg != null) parts.push(`${Math.round(w.temperature_c.avg)}°C`);
  if (w.wind.speed_kmh != null) parts.push(`wind ${Math.round(w.wind.speed_kmh)} km/h${w.wind.direction_from_label ? ` from ${w.wind.direction_from_label}` : ""}`);
  if (w.precipitation_mm != null) parts.push(`${w.precipitation_mm.toFixed(1)} mm rain`);
  return parts.join(" · ");
}

/** The summary-card strip: observed values only, and nothing at all when there are none. */
export function WeatherChips({ canonicalId, enabled }: { canonicalId: number; enabled: boolean }) {
  const { data } = useQuery({ queryKey: ["workout-weather", canonicalId], queryFn: () => fetchWorkoutWeather(canonicalId), enabled });
  if (!data?.weather || (data.status !== "ok" && data.status !== "partial")) return null;
  const text = weatherChip(data.weather);
  if (!text) return null;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3" data-testid="weather-chips">
      <span className="text-xs text-text-tertiary">Conditions</span>
      <span className="text-sm text-text-primary">{data.weather.condition.text ? `${data.weather.condition.text} · ` : ""}{text}</span>
      {(data.status === "partial" || data.weather.provisional) && <span className="text-xs text-text-tertiary">(partial data)</span>}
    </div>
  );
}

const STATUS_TEXT: Record<WeatherResponse["status"], string> = {
  ok: "Observed conditions for this session's window and area.",
  partial: "Partial: some values are missing, or the day isn't final reanalysis yet. What is shown is real; the gaps are not filled in.",
  unavailable: "The provider returned nothing for this window.",
  not_fetched: "Weather hasn't been looked up for this activity yet.",
  no_gps: "Weather needs a GPS location, and this activity has none.",
};

export function WeatherCard({ canonicalId }: { canonicalId: number }) {
  const queryClient = useQueryClient();
  const { data, isError } = useQuery({ queryKey: ["workout-weather", canonicalId], queryFn: () => fetchWorkoutWeather(canonicalId) });
  const refresh = useMutation({
    mutationFn: () => refreshWorkoutWeather(canonicalId),
    onSuccess: (next) => queryClient.setQueryData(["workout-weather", canonicalId], next),
  });

  if (isError) return <Card title="Conditions"><p className="text-sm text-text-tertiary">Couldn't load weather.</p></Card>;
  if (!data) return null;
  const w = data.weather;
  const canRefresh = data.status !== "no_gps";

  return (
    <Card
      title="Conditions"
      action={
        canRefresh ? (
          <button
            type="button"
            disabled={refresh.isPending}
            onClick={() => refresh.mutate()}
            className="min-h-9 rounded-md border border-border px-3 text-xs font-medium text-text-primary disabled:opacity-50"
          >
            {refresh.isPending ? "Looking up…" : data.status === "not_fetched" ? "Look up" : "Refresh"}
          </button>
        ) : undefined
      }
    >
      <p className="mb-2 text-xs text-text-tertiary" data-testid="weather-status" data-status={data.status}>
        {STATUS_TEXT[data.status]}
      </p>
      {refresh.isError && <p className="mb-2 text-xs text-band-red-text">The weather provider couldn't be reached — nothing was changed.</p>}
      {w && (
        <>
          <dl>
            <Row label="Conditions">{w.condition.text ?? MISSING}</Row>
            <Row label="Temperature">{w.temperature_c.avg == null ? MISSING : `${w.temperature_c.avg.toFixed(1)} °C`}</Row>
            <Row label="Wind">
              {w.wind.speed_kmh == null ? (
                MISSING
              ) : (
                <span className="inline-flex items-center gap-2">
                  {w.wind.direction_from_deg != null && <WindArrow fromDeg={w.wind.direction_from_deg} />}
                  {w.wind.speed_kmh.toFixed(0)} km/h{w.wind.direction_from_label ? ` from ${w.wind.direction_from_label}` : ""}
                </span>
              )}
            </Row>
            <Row label="Gusts (max)">{num(w.wind.gust_max_kmh, 0, "km/h")}</Row>
            <Row label="Precipitation">{num(w.precipitation_mm, 1, "mm")}</Row>
            <Row label="Humidity">{num(w.humidity_pct, 0, "%")}</Row>
            <Row label="Pressure">{num(w.pressure_hpa, 0, "hPa")}</Row>
          </dl>
          <p className="mt-2 text-xs text-text-tertiary">
            Data coverage of this window: {Math.round(w.coverage * 100)}%. Area cell near {w.location_rounded.lat.toFixed(1)}°, {w.location_rounded.lon.toFixed(1)}° (coordinates rounded before being sent).
          </p>
        </>
      )}
      {data.disclaimer && <p className="mt-2 text-xs text-text-tertiary">{data.disclaimer}</p>}
      <p className="mt-2 text-xs text-text-tertiary">
        <a href={data.attribution_url} target="_blank" rel="noopener noreferrer" className="underline">
          {data.attribution}
        </a>
      </p>
    </Card>
  );
}
