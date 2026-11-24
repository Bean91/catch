import { useQuery } from "@tanstack/react-query";
import { MuscleBodyMap } from "../components/gym/MuscleBodyMap";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { CardSkeleton } from "../components/ui/Skeleton";
import { fetchMuscleReadiness } from "../lib/api";

export function MuscleReadinessPage() {
  const query = useQuery({ queryKey: ["muscle-readiness"], queryFn: fetchMuscleReadiness });

  const header = (
    <PageHeader
      back={{ to: "/gym", label: "Gym" }}
      eyebrow="Health"
      title="Muscle readiness"
      subtitle="Muscular load from your lifting and hard cardio, by area. Darker means more recent load."
    />
  );
  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        {header}
        <CardSkeleton lines={4} />
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="flex flex-col gap-4">
        {header}
        <ErrorState message="Couldn't load muscle readiness." onRetry={() => query.refetch()} />
      </div>
    );
  }

  const byMuscle = query.data?.by_muscle ?? {};
  const sorted = Object.entries(byMuscle)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex flex-col gap-4">
      {header}
      <Card material="solid" title={`Load over the last ${query.data?.window_hours ?? 72}h`}>
        {sorted.length === 0 ? (
          <EmptyState message={`No lifting logged in the last ${query.data?.window_hours ?? 72} hours.`} />
        ) : (
          <>
            <MuscleBodyMap byMuscle={byMuscle} />
            <ul className="mt-4 flex flex-col gap-2">
              {sorted.map(([muscle, value]) => (
                <li key={muscle} className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)_3.5rem] items-center gap-3 text-sm">
                  <span className="truncate capitalize text-text-secondary">{muscle}</span>
                  <span aria-hidden className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                    <span className="block h-full rounded-full bg-accent" style={{ width: `${(value / sorted[0][1]) * 100}%` }} />
                  </span>
                  <span className="text-right font-mono-nums text-text-primary">{Math.round(value)} AU</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </div>
  );
}
