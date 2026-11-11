import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchRoute, fetchRouteHistory, fetchTrack, patchRoute } from "../lib/api";
import { formatDuration, formatShortDate } from "../lib/format";
import { formatKm, formatPace, formatSpeedKmh } from "../lib/gpsFormat";
import type { RouteSession } from "../lib/types";
import { GpsBadge } from "../components/gps/GpsBadge";
import { SpeedHistogram } from "../components/gps/SpeedHistogram";
import { LazyRouteMap } from "../components/maps/LazyRouteMap";
import type { MapLine } from "../components/maps/RouteMap";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { CardSkeleton } from "../components/ui/Skeleton";

const paceOf = (mps: number | null | undefined) => formatPace("s_per_500m", mps ? 500 / mps : null);

function SessionFig({ title, s, extra }: { title: string; s: RouteSession | null; extra?: string }) {
  return (
    <div>
      <div className="text-xs text-text-tertiary">{title}</div>
      {s ? (
        <>
          <div className="font-mono-nums text-base font-medium text-text-primary">{paceOf(s.avg_speed_mps)}</div>
          <div className="text-xs text-text-tertiary">
            {s.date ? formatShortDate(s.date) : "—"} · {formatSpeedKmh(s.avg_speed_mps)}
            {extra ? ` · ${extra}` : ""}
          </div>
        </>
      ) : (
        <div className="text-base text-text-tertiary">—</div>
      )}
    </div>
  );
}

const CONFIDENCE_TEXT: Record<string, string> = {
  insufficient_data: "Not enough history to call this a pattern.",
  low: "Low confidence — a handful of sessions so far.",
  medium: "Medium confidence.",
  high: "High confidence — many sessions over a long history.",
};

export function RouteDetailPage() {
  const { id } = useParams();
  const routeId = Number(id);
  const queryClient = useQueryClient();
  const { data: route, isLoading, isError, refetch } = useQuery({ queryKey: ["route", routeId], queryFn: () => fetchRoute(routeId), enabled: Number.isFinite(routeId) });
  const { data: history } = useQuery({ queryKey: ["route-history", routeId], queryFn: () => fetchRouteHistory(routeId), enabled: Number.isFinite(routeId) });

  const [selected, setSelected] = useState<number | null>(null);
  const selectedCid = selected ?? history?.sessions[0]?.canonical_id ?? null;
  const { data: track } = useQuery({ queryKey: ["track", selectedCid], queryFn: () => fetchTrack(selectedCid!, 400), enabled: selectedCid != null });

  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [tagsDraft, setTagsDraft] = useState<string | null>(null);
  const patch = useMutation({
    mutationFn: (p: { name?: string | null; tags?: string[] }) => patchRoute(routeId, p),
    onSuccess: (updated) => {
      queryClient.setQueryData(["route", routeId], updated);
      queryClient.invalidateQueries({ queryKey: ["routes"] });
      queryClient.invalidateQueries({ queryKey: ["route-history", routeId] });
    },
  });

  const lines: MapLine[] = useMemo(() => {
    if (!route) return [];
    const out: MapLine[] = [{ id: "reference", segments: [{ coords: route.reference }], weight: 3, opacity: 0.55, dashed: true }];
    if (track?.has_track) out.push({ id: "session", segments: [{ coords: track.points.map((p) => [p.lat, p.lon] as [number, number]) }], weight: 5, opacity: 0.95, endpoints: true });
    return out;
  }, [route, track]);

  if (isLoading) return <CardSkeleton lines={4} />;
  if (isError || !route) return <ErrorState message="Couldn't load this route." onRetry={() => refetch()} />;

  const stats = history?.stats;
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/routes" className="text-sm text-text-tertiary transition-colors hover:text-text-secondary">
          ← Routes
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {editingName ? (
            <input
              autoFocus
              aria-label="Route name"
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={() => {
                setEditingName(false);
                if (nameDraft !== (route.name ?? "")) patch.mutate({ name: nameDraft });
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                if (e.key === "Escape") setEditingName(false);
              }}
              className="min-h-9 rounded-md border border-accent bg-surface px-2 text-lg font-semibold text-text-primary"
            />
          ) : (
            <h1
              className="cursor-text text-lg font-semibold text-text-primary"
              title="Tap to rename"
              onClick={() => {
                setNameDraft(route.name ?? "");
                setEditingName(true);
              }}
            >
              {route.display_name}
            </h1>
          )}
          {!route.name_is_manual && <span className="text-xs text-text-tertiary">auto-named — tap the title to name it</span>}
        </div>
        <p className="text-sm text-text-tertiary">
          {formatKm(route.length_m, 1)} <GpsBadge source={route.length_source} /> · {history?.stats.n_sessions ?? route.n_sessions} sessions
        </p>
        <label className="mt-2 flex items-center gap-2 text-xs text-text-tertiary">
          Tags
          <input
            aria-label="Route tags"
            value={tagsDraft ?? route.tags.join(", ")}
            onChange={(e) => setTagsDraft(e.target.value)}
            onBlur={() => {
              if (tagsDraft == null) return;
              patch.mutate({ tags: tagsDraft.split(",").map((t) => t.trim()).filter(Boolean) });
              setTagsDraft(null);
            }}
            placeholder="steady, lake, windy-day…"
            className="min-h-9 min-w-0 flex-1 rounded-md border border-border bg-surface px-2 text-sm text-text-primary"
          />
        </label>
      </div>

      <Card title="Course">
        <LazyRouteMap lines={lines} height={300} label="Route reference and selected session" />
        <p className="mt-2 text-xs text-text-tertiary">Dashed line: the route's reference course. Solid line: the session selected below.</p>
      </Card>

      {history && stats && (
        <>
          <Card title="History" action={<GpsBadge source="gps_derived" />}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <SessionFig title="Best" s={stats.best} />
              <div>
                <div className="text-xs text-text-tertiary">Typical (median)</div>
                <div className="font-mono-nums text-base font-medium text-text-primary">{paceOf(stats.typical_avg_speed_mps)}</div>
                <div className="text-xs text-text-tertiary">{formatSpeedKmh(stats.typical_avg_speed_mps)}</div>
              </div>
              <SessionFig title="Most recent" s={stats.recent} extra={stats.recent_vs_typical_pct != null ? `${stats.recent_vs_typical_pct >= 0 ? "+" : ""}${stats.recent_vs_typical_pct.toFixed(1)}% vs typical` : undefined} />
            </div>
            <p className="mt-3 text-xs text-text-tertiary" data-testid="history-confidence">
              {CONFIDENCE_TEXT[history.confidence]} {history.note}
            </p>
            <ul className="mt-2 list-disc pl-5 text-xs text-text-tertiary" data-testid="history-caveats">
              {stats.caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-text-tertiary">{history.comparison}</p>
          </Card>

          {stats.speed_distribution && (
            <Card title="Speed distribution">
              <SpeedHistogram dist={stats.speed_distribution} />
            </Card>
          )}

          <Card title="Heart-rate context">
            {stats.hr ? (
              <p className="text-sm text-text-primary">
                Average HR across {stats.hr.n} session{stats.hr.n === 1 ? "" : "s"} with heart-rate data: <span className="font-mono-nums">{Math.round(stats.hr.mean)}</span> bpm (range {Math.round(stats.hr.min)}–{Math.round(stats.hr.max)}).
              </p>
            ) : (
              <p className="text-sm text-text-tertiary">No heart-rate data recorded on this route.</p>
            )}
            <p className="mt-1 text-xs text-text-tertiary">Shown for context. Different heart rates at similar speeds can come from sleep, heat, fatigue, wind or current — this page can't say which.</p>
          </Card>

          {stats.weather_differences.length > 0 && (
            <Card title="Conditions, best session vs the others">
              <ul className="flex flex-col gap-1 text-sm" data-testid="weather-differences">
                {stats.weather_differences.map((d) => (
                  <li key={d.metric} className="text-text-primary">
                    {d.metric}: <span className="font-mono-nums">{d.best_session.toFixed(1)}</span> vs median <span className="font-mono-nums">{d.other_sessions_median.toFixed(1)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-text-tertiary">{stats.weather_differences[0].note}</p>
            </Card>
          )}

          <Card title="Sessions">
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="route-sessions">
                <thead>
                  <tr className="text-left text-xs text-text-tertiary">
                    <th className="py-1 pr-3 font-normal">Date</th>
                    <th className="py-1 pr-3 font-normal">Pace</th>
                    <th className="py-1 pr-3 font-normal">Moving</th>
                    <th className="py-1 pr-3 font-normal">HR</th>
                    <th className="py-1 pr-3 font-normal">Conditions</th>
                    <th className="py-1 font-normal" />
                  </tr>
                </thead>
                <tbody className="font-mono-nums">
                  {history.sessions.map((s) => (
                    <tr key={s.activity_id} className={`border-t border-border ${s.canonical_id === selectedCid ? "bg-surface-2" : ""}`}>
                      <td className="py-1.5 pr-3">
                        {s.canonical_id != null ? (
                          <Link to={`/workouts/${s.canonical_id}`} className="text-accent underline">
                            {s.date ? formatShortDate(s.date) : "—"}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="py-1.5 pr-3 text-text-primary">{paceOf(s.avg_speed_mps)}</td>
                      <td className="py-1.5 pr-3 text-text-primary">{formatDuration(s.moving_s)}</td>
                      <td className="py-1.5 pr-3 text-text-secondary">{s.avg_hr != null ? Math.round(s.avg_hr) : "—"}</td>
                      <td className="py-1.5 pr-3 font-sans text-xs text-text-tertiary">
                        {s.weather ? `${s.weather.temperature_avg_c != null ? `${Math.round(s.weather.temperature_avg_c)}°C, ` : ""}${s.weather.wind_speed_kmh != null ? `wind ${Math.round(s.weather.wind_speed_kmh)} km/h` : "no wind data"}` : "not fetched"}
                      </td>
                      <td className="py-1.5">
                        <button
                          type="button"
                          aria-pressed={s.canonical_id === selectedCid}
                          onClick={() => setSelected(s.canonical_id)}
                          className="min-h-9 rounded-md border border-border px-2 font-sans text-xs text-text-primary"
                        >
                          Show
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
