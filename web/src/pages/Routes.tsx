import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchRoutes } from "../lib/api";
import { formatKm } from "../lib/gpsFormat";
import { formatShortDate } from "../lib/format";
import { GpsBadge } from "../components/gps/GpsBadge";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { CardSkeleton } from "../components/ui/Skeleton";

export function RoutesPage() {
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["routes"], queryFn: fetchRoutes });

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link to="/workouts" className="text-sm text-text-tertiary transition-colors hover:text-text-secondary">
          ← Workouts
        </Link>
        <h1 className="mt-1 text-lg font-semibold text-text-primary">Routes</h1>
        <p className="text-sm text-text-tertiary">Courses you've rowed more than once, grouped only when the GPS tracks genuinely line up.</p>
      </div>
      {isLoading && <CardSkeleton lines={3} />}
      {isError && <ErrorState message="Couldn't load routes." onRetry={() => refetch()} />}
      {data && data.length === 0 && (
        <Card>
          <p className="text-sm text-text-secondary" data-testid="routes-empty">No repeated routes yet.</p>
          <p className="mt-1 text-xs text-text-tertiary">A route appears once two on-water sessions follow the same course — same start and finish, about the same length, and the tracks overlapping. A single row is never promoted on its own, and you can also save one course as a route from its workout page.</p>
        </Card>
      )}
      <div className="flex flex-col gap-3">
        {data?.map((r) => (
          <Link key={r.id} to={`/routes/${r.id}`} className="block rounded-lg border border-border bg-surface p-4 transition-colors hover:border-accent/40 sm:p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-base font-medium text-text-primary">{r.display_name}</span>
              <span className="font-mono-nums text-sm text-text-secondary">
                {formatKm(r.length_m, 1)} <GpsBadge source={r.length_source} />
              </span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-tertiary">
              <span>{r.n_sessions} sessions</span>
              {r.last_session && <span>last {formatShortDate(r.last_session)}</span>}
              {!r.name_is_manual && <span>auto-named — open to give it a name</span>}
              {r.tags.map((t) => (
                <span key={t} className="rounded-full border border-border px-2 py-0.5">
                  {t}
                </span>
              ))}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
