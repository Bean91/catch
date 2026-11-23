import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { fetchToday, fetchTodayCheckin, isMock } from "../lib/api";
import { formatRelativeTime, formatShortDate } from "../lib/format";
import { useOnlineStatus } from "../lib/useOnlineStatus";
import { CheckinSheet } from "../components/today/CheckinSheet";
import { ErgCard } from "../components/today/ErgCard";
import { IllnessCard } from "../components/today/IllnessCard";
import { LoadCard } from "../components/today/LoadCard";
import { RecommendationAndSync } from "../components/today/RecommendationAndSync";
import { UpcomingEventsCard } from "../components/today/UpcomingEventsCard";
import { RecoveryRing } from "../components/today/RecoveryRing";
import { SleepCard } from "../components/today/SleepCard";
import { StrainGauge } from "../components/today/StrainGauge";
import { VitalsCard } from "../components/today/VitalsCard";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { Button } from "../components/ui/Button";
import { Notice } from "../components/ui/Notice";
import { PageHeader, SectionHeader } from "../components/ui/PageHeader";

// The dashboard's lower half is its own chunk: Today is the one eagerly loaded page, and the initial bundle has a budget.
const TodayMore = lazy(() => import("../components/today/TodayMore"));

// `forceCheckin`: the /checkin deep link (a notification tap, a link) opens the sheet even if it was skipped earlier today,
// and for an already-completed check-in it opens in edit mode.
export function TodayPage({ forceCheckin = false }: { forceCheckin?: boolean } = {}) {
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["today"], queryFn: fetchToday });
  const { data: checkinStatus } = useQuery({ queryKey: ["today-checkin"], queryFn: fetchTodayCheckin, enabled: !!data });
  const isOnline = useOnlineStatus();
  const [sheetOpen, setSheetOpen] = useState(false);
  // Not persisted across a reload, deliberately — "Skip for today" shouldn't nag again this
  // same page session, but a fresh page load with the check-in still not done should still
  // auto-open it (task Part A.1's "once a day, editable later").
  const [dismissedDate, setDismissedDate] = useState<string | null>(null);

  useEffect(() => {
    if (forceCheckin && data && checkinStatus) setSheetOpen(true);
  }, [forceCheckin, !!data, !!checkinStatus]);

  useEffect(() => {
    if (forceCheckin) return;
    if (!data || !checkinStatus || checkinStatus.completed || dismissedDate === data.date) return;
    // web/tests/touch/ drives Today under plain ?mock=1 — an auto-opening dialog there would
    // block every gesture test. The real app always auto-opens off real `completed` state;
    // mock mode needs the explicit ?checkin=1 opt-in on top of that (see DESIGN.md).
    if (isMock && new URLSearchParams(window.location.search).get("checkin") !== "1") return;
    setSheetOpen(true);
  }, [data?.date, checkinStatus?.completed, dismissedDate]);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2" aria-hidden>
          <div className="h-3 w-32 animate-shimmer rounded bg-[linear-gradient(90deg,var(--surface-2)_25%,var(--surface-3)_50%,var(--surface-2)_75%)] bg-[length:200%_100%]" />
          <div className="h-7 w-24 animate-shimmer rounded bg-[linear-gradient(90deg,var(--surface-2)_25%,var(--surface-3)_50%,var(--surface-2)_75%)] bg-[length:200%_100%]" />
        </div>
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

  const longDate = new Date(`${data.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      {/* Gated on an actual failed /api/health probe (useOnlineStatus), never on a date-string
          comparison — the old check compared the server's own-timezone calendar date against
          the browser's UTC-sliced one, which disagrees for several hours a day regardless of
          connectivity. A single source failing to sync (e.g. Concept2) is a per-card notice in
          RecommendationAndSync, never this global banner. */}
      {!isOnline && (
        <Notice tone="warn" role="status">
          You're offline — showing data from {formatRelativeTime(data.generated_at)} ({formatShortDate(data.generated_at)}).
          Reconnect to refresh.
        </Notice>
      )}

      <PageHeader
        eyebrow={longDate}
        title="Today"
        actions={
          <Button variant={checkinStatus?.completed ? "secondary" : "primary"} size="sm" onClick={() => setSheetOpen(true)}>
            {checkinStatus?.completed ? "Edit check-in" : "Morning check-in"}
          </Button>
        }
      />

      {data.checkin.niggle_flag && (
        // Never colour-only (DESIGN.md) — the band dot is paired with this text either way.
        <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-band-yellow/35 bg-band-yellow/10 px-3 py-1 text-xs font-medium text-text-primary">
          <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--band-yellow)" }} />
          Training issue: {data.checkin.niggle_area} — {data.checkin.niggle_streak_days} days running
        </span>
      )}

      {data.illness && data.illness.level !== "none" && <IllnessCard date={data.date} illness={data.illness} />}

      <section aria-label="Readiness" className="grid gap-4 sm:grid-cols-[minmax(0,240px)_minmax(0,1fr)] lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)_minmax(0,1fr)] lg:gap-5">
        <RecoveryRing recovery={data.recovery} />
        <StrainGauge strain={data.strain_today} targetRange={data.strain_target_range} dailyActivity={data.daily_activity} />
        <div className="sm:col-span-2 lg:col-span-1">
          <SleepCard sleep={data.sleep_last_night} />
        </div>
      </section>

      <RecommendationAndSync recommendation={data.recommendation} nextARace={data.next_a_race} />

      <section aria-label="Vitals and load" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 lg:gap-5">
        <VitalsCard title="HRV" unit="ms" decimals={0} trend={data.hrv} metric="hrv_rmssd" />
        <VitalsCard title="Resting HR" unit="bpm" decimals={0} trend={data.resting_hr} metric="resting_hr" />
        <div className="sm:col-span-2 lg:col-span-1">
          <LoadCard load={data.load} rowingLoad={data.rowing_load} />
        </div>
      </section>

      <SectionHeader title="Training" description="Your week, your consistency and your latest work." />
      <Suspense
        fallback={
          <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
            <CardSkeleton lines={4} />
            <CardSkeleton lines={4} />
          </div>
        }
      >
        <TodayMore />
      </Suspense>

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr] lg:gap-5">
        <ErgCard erg={data.latest_erg} predicted2k={data.predicted_2k} />
        <UpcomingEventsCard />
      </div>

      <CheckinSheet
        open={sheetOpen}
        onOpenChange={(v) => {
          setSheetOpen(v);
          if (!v) setDismissedDate(data.date);
        }}
        existing={checkinStatus?.checkin ?? null}
      />
    </div>
  );
}
