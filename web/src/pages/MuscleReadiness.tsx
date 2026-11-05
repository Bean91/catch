import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { MuscleBodyMap } from "../components/gym/MuscleBodyMap";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { CardSkeleton } from "../components/ui/Skeleton";
import { fetchMuscleReadiness } from "../lib/api";

export function MuscleReadinessPage() {
  const query = useQuery({ queryKey: ["muscle-readiness"], queryFn: fetchMuscleReadiness });

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <CardSkeleton lines={4} />
      </div>
    );
  }

  const byMuscle = query.data?.by_muscle ?? {};
  const sorted = Object.entries(byMuscle)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Muscle readiness</h1>
        <Link to="/gym" className="text-sm font-medium text-accent">
          Back to Gym
        </Link>
      </div>
      <Card title={`Load over the last ${query.data?.window_hours ?? 72}h`}>
        {sorted.length === 0 ? (
          <EmptyState message="No lifting logged in the last 72 hours." />
        ) : (
          <>
            <MuscleBodyMap byMuscle={byMuscle} />
            <ul className="mt-4 flex flex-col gap-1.5">
              {sorted.map(([muscle, value]) => (
                <li key={muscle} className="flex items-center justify-between text-sm">
                  <span className="capitalize text-text-secondary">{muscle}</span>
                  <span className="font-mono-nums text-text-primary">{Math.round(value)} AU</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </div>
  );
}
