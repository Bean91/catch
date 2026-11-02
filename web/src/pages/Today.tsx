import { useQuery } from "@tanstack/react-query";
import { fetchToday } from "../lib/api";
import { formatRelativeTime, formatShortDate } from "../lib/format";
import { useOnlineStatus } from "../lib/useOnlineStatus";
import { ErgCard } from "../components/today/ErgCard";
import { LoadCard } from "../components/today/LoadCard";
import { RecommendationAndSync } from "../components/today/RecommendationAndSync";
import { RecoveryRing } from "../components/today/RecoveryRing";
import { SleepCard } from "../components/today/SleepCard";
import { StrainGauge } from "../components/today/StrainGauge";
import { VitalsCard } from "../components/today/VitalsCard";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";

export function TodayPage() {
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["today"], queryFn: fetchToday });
  const isOnline = useOnlineStatus();

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <CardSkeleton lines={1} />
        <div className="grid gap-4 sm:grid-cols-2">
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return <ErrorState message="Couldn't load today's data." onRetry={() => refetch()} />;
  }

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      {/* Gated on an actual failed /api/health probe (useOnlineStatus), never on a date-string
          comparison — the old check compared the server's own-timezone calendar date against
          the browser's UTC-sliced one, which disagrees for several hours a day regardless of
          connectivity. A single source failing to sync (e.g. Concept2) is a per-card notice in
          RecommendationAndSync, never this global banner. */}
      {!isOnline && (
        <div className="rounded-md border border-border bg-surface-2 px-4 py-2.5 text-sm text-text-secondary">
          You're offline — showing data from {formatRelativeTime(data.generated_at)} ({formatShortDate(data.generated_at)}).
          Reconnect to refresh.
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-[220px_1fr] lg:grid-cols-[260px_1fr] lg:gap-5">
        <RecoveryRing recovery={data.recovery} />
        <div className="flex flex-col gap-4 lg:gap-5">
          <StrainGauge strain={data.strain_today} targetRange={data.strain_target_range} />
          <div className="hidden lg:block">
            <SleepCard sleep={data.sleep_last_night} />
          </div>
        </div>
      </div>

      <div className="lg:hidden">
        <SleepCard sleep={data.sleep_last_night} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 lg:gap-5">
        <VitalsCard title="HRV" unit="ms" decimals={0} trend={data.hrv} metric="hrv_rmssd" />
        <VitalsCard title="Resting HR" unit="bpm" decimals={0} trend={data.resting_hr} metric="resting_hr" />
        <div className="sm:col-span-2 lg:col-span-1">
          <LoadCard load={data.load} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr] lg:gap-5">
        <ErgCard erg={data.latest_erg} predicted2k={data.predicted_2k} />
        <RecommendationAndSync recommendation={data.recommendation} nextARace={data.next_a_race} />
      </div>
    </div>
  );
}
