import { useQuery } from "@tanstack/react-query";
import { BackLink } from "../components/ui/PageHeader";
import { Link, useParams } from "react-router-dom";
import { fetchTestDetail } from "../lib/api";
import { formatDistance, formatDuration, formatShortDate, formatSplit } from "../lib/format";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { SplitBarChart } from "../components/tests/SplitBarChart";
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
        <div className="mt-1 flex items-center justify-between gap-2">
          <h1 className="text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]">
            {test_type ?? "Test"} — {activity.local_date ? formatShortDate(activity.local_date) : "—"}
          </h1>
          <Link to={`/workouts/${canonicalId}`} className="text-xs text-text-tertiary transition-colors hover:text-text-secondary">
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

      {pacing_analysis && (
        <Card title="Pacing">
          <SplitBarChart splits={pacing_analysis.splits} vsPlan={pacing_analysis.vs_plan} />
          <div className="mt-3 grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-xs text-text-tertiary">Start</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatSplit(pacing_analysis.segments.start)}</div>
            </div>
            <div>
              <div className="text-xs text-text-tertiary">Middle 1000</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatSplit(pacing_analysis.segments.middle_1000)}</div>
            </div>
            <div>
              <div className="text-xs text-text-tertiary">Sprint</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatSplit(pacing_analysis.segments.sprint)}</div>
            </div>
          </div>
          <div className="mt-3 flex flex-col gap-1 border-t border-border pt-3 text-sm text-text-secondary">
            <span>
              Even split: <span className="font-mono-nums text-text-primary">{formatSplit(pacing_analysis.even_split_s)}</span>
              {pacing_analysis.deviation_from_even_pct != null && <> ({pacing_analysis.deviation_from_even_pct.toFixed(1)}% spread)</>}
            </span>
            {pacing_analysis.worst_split_vs_even && (
              <span>
                Slowest: split {pacing_analysis.worst_split_vs_even.split_index}, {pacing_analysis.worst_split_vs_even.seconds_lost_vs_even.toFixed(1)}s
                slower than even.
              </span>
            )}
          </div>
          {plan && <p className="mt-2 text-xs text-text-tertiary">Dashed line is the saved {plan.style.replace(/_/g, " ")} plan.</p>}
        </Card>
      )}

      {compare_to_earlier && (
        <Card title="Compare to earlier test">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-xs text-text-tertiary">{compare_to_earlier.date ? formatShortDate(compare_to_earlier.date) : "—"}</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatDuration(compare_to_earlier.duration_s)}</div>
            </div>
            <span className="text-text-tertiary">→</span>
            <div>
              <div className="text-xs text-text-tertiary">{activity.local_date ? formatShortDate(activity.local_date) : "—"}</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatDuration(activity.duration)}</div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
