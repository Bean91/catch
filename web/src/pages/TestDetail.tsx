import { useQuery } from "@tanstack/react-query";
import { BackLink } from "../components/ui/PageHeader";
import { Link, useParams } from "react-router-dom";
import { fetchTestDetail } from "../lib/api";
import { formatDistance, formatDuration, formatShortDate } from "../lib/format";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { CompareCard, PacingCard } from "../components/tests/PacingCard";
import { MassPower } from "../components/pieces/MassPower";

export function TestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const canonicalId = Number(id);
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["test-detail", canonicalId], queryFn: () => fetchTestDetail(canonicalId) });

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <CardSkeleton lines={2} />
        <CardSkeleton lines={4} />
      </div>
    );
  }
  if (isError || !data) {
    return <ErrorState message="Couldn't load this test." onRetry={() => refetch()} />;
  }

  const { activity, test_type, plan, pacing_analysis, compare_to_earlier } = data;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <BackLink to="/tests">Test center</BackLink>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-2">
          <h1 className="text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]">
            {test_type ?? "Test"} — {activity.local_date ? formatShortDate(activity.local_date) : "—"}
          </h1>
          <Link to={`/workouts/${canonicalId}`} className="shrink-0 text-sm font-medium text-accent hover:underline">
            Full workout detail →
          </Link>
        </div>
        <p className="font-mono-nums text-sm text-text-secondary">
          {formatDistance(activity.distance)} in {formatDuration(activity.duration)}
        </p>
        <div className="mt-1">
          <MassPower watts={activity.avg_power} mass={data} />
        </div>
      </div>

      {pacing_analysis && <PacingCard pacing={pacing_analysis} planStyle={plan?.style} />}

      {compare_to_earlier && <CompareCard title="Compare to earlier test" earlier={compare_to_earlier} nowDate={activity.local_date} nowDurationS={activity.duration} />}
    </div>
  );
}
