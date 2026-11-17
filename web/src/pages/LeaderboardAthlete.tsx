import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { fetchLbProfile } from "../lib/api";
import { EntryRow } from "../components/leaderboards/EntryRow";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";

export function LeaderboardAthletePage() {
  const { id = "" } = useParams();
  const q = useQuery({ queryKey: ["lb-athlete", id], queryFn: () => fetchLbProfile(id), retry: false });
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/leaderboards" className="text-sm font-medium text-accent hover:underline">
          ← Leaderboards
        </Link>
        <h1 className="mt-1 text-lg font-semibold text-text-primary" data-testid="lb-athlete-name">
          {q.data?.name ?? "Athlete"}
        </h1>
        <p className="mt-1 text-sm text-text-secondary">Only results this athlete chose to publish. Nothing about their recovery, sleep, weight or training is ever shown here.</p>
      </div>
      {q.isLoading && <CardSkeleton lines={3} />}
      {q.isError && <p className="text-sm text-text-secondary">This athlete's profile isn't available.</p>}
      {q.data && q.data.results.length === 0 && (
        <Card>
          <p className="text-sm text-text-secondary">No public results.</p>
        </Card>
      )}
      {q.data && q.data.results.length > 0 && (
        <ul className="flex flex-col gap-2" data-testid="lb-athlete-results">
          {q.data.results.map((e) => (
            <EntryRow key={e.entry_id} entry={e} />
          ))}
        </ul>
      )}
    </div>
  );
}
