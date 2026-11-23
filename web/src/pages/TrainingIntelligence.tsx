import { useQuery } from "@tanstack/react-query";
import { PerformanceTrendsCard } from "../components/intelligence/PerformanceTrendsCard";
import { ConsistencyCard } from "../components/intelligence/ConsistencyCard";
import { InsightsList } from "../components/intelligence/InsightCard";
import { RecommendationsCard } from "../components/intelligence/RecommendationCard";
import { StrengthsWeaknessesCard } from "../components/intelligence/StrengthsWeaknessesCard";
import { TrainingDistributionCard } from "../components/intelligence/TrainingDistributionCard";
import { TrainingProfileCard } from "../components/intelligence/TrainingProfileCard";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { CardSkeleton, Skeleton } from "../components/ui/Skeleton";
import { PageHeader, SectionHeader } from "../components/ui/PageHeader";
import { ProgressionCard } from "../components/intelligence/ProgressionCard";
import { IntervalComparisonCard } from "../components/intelligence/IntervalComparisonCard";
import {
  fetchIntervalComparisons,
  fetchPerformanceTrends,
  fetchRecommendations,
  fetchTrainingConsistency,
  fetchTrainingDistribution,
  fetchTrainingInsights,
  fetchTrainingProfile,
} from "../lib/api";

/** Session 18 (see PLAN.md) — a dedicated route under Trends (`/trends/intelligence`), not a
 * new top-level Sidebar/BottomNav destination: both nav lists are already documented as
 * tight (DESIGN.md), and the task asked for "the existing Trends or Coach area," which this
 * satisfies via the entry link on Trends' own header rather than a ninth/eighth nav slot.
 * Each section is its own Card + useQuery, mirroring Trends.tsx's own composition style —
 * not a single monolithic fetch. */
export function TrainingIntelligencePage() {
  const profileQuery = useQuery({ queryKey: ["training-profile"], queryFn: fetchTrainingProfile });
  const trendsQuery = useQuery({ queryKey: ["performance-trends"], queryFn: () => fetchPerformanceTrends() });
  const intervalsQuery = useQuery({ queryKey: ["interval-comparisons"], queryFn: fetchIntervalComparisons });
  const distributionQuery = useQuery({ queryKey: ["training-distribution"], queryFn: () => fetchTrainingDistribution(12) });
  const consistencyQuery = useQuery({ queryKey: ["training-consistency"], queryFn: () => fetchTrainingConsistency() });
  const insightsQuery = useQuery({ queryKey: ["training-insights"], queryFn: fetchTrainingInsights });
  const recommendationsQuery = useQuery({ queryKey: ["recommendations"], queryFn: () => fetchRecommendations("active") });
  // "Saved" rows fall out of the "active" list the moment they go stale (a resolved
  // recommendation shouldn't keep reading as active — see is_active in catch/sync/
  // training_intelligence.py), so Save needs its own always-visible section or the button
  // would do nothing the athlete could ever see again.
  const savedQuery = useQuery({ queryKey: ["recommendations", "saved"], queryFn: () => fetchRecommendations("all") });
  const savedRecommendations = (savedQuery.data ?? []).filter((r) => r.saved);

  const loading = <Skeleton className="h-24 w-full" />;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        back={{ to: "/trends", label: "Trends" }}
        eyebrow="Analysis"
        title="Training intelligence"
        subtitle="What your data says about your training — each claim with the confidence behind it."
      />

      {profileQuery.isLoading && <CardSkeleton lines={3} />}
      {profileQuery.isError && <ErrorState message="Couldn't load the training profile." onRetry={() => profileQuery.refetch()} />}
      {profileQuery.data && <TrainingProfileCard profile={profileQuery.data} />}

      <SectionHeader title="Performance" description="Like-for-like pieces over time, and how intervals compare." />
      <ProgressionCard />
      <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
        <Card title="Performance trajectory">
          {trendsQuery.isLoading && loading}
          {trendsQuery.isError && <ErrorState message="Couldn't load performance trends." onRetry={() => trendsQuery.refetch()} />}
          {trendsQuery.data && <PerformanceTrendsCard buckets={trendsQuery.data.buckets} />}
        </Card>
        <Card title="Interval sessions">
          {intervalsQuery.isLoading && loading}
          {intervalsQuery.isError && <ErrorState message="Couldn't load interval comparisons." onRetry={() => intervalsQuery.refetch()} />}
          {intervalsQuery.data && <IntervalComparisonCard buckets={intervalsQuery.data.buckets} />}
        </Card>
      </div>

      <SectionHeader title="Training" description="How your time is spread across intensities, and how regularly you train." />
      <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
        <Card title="Training distribution (last 12 weeks)">
          {distributionQuery.isLoading && loading}
          {distributionQuery.isError && <ErrorState message="Couldn't load training distribution." onRetry={() => distributionQuery.refetch()} />}
          {distributionQuery.data && <TrainingDistributionCard weeks={distributionQuery.data.weeks} />}
        </Card>
        <Card title="Consistency">
          {consistencyQuery.isLoading && loading}
          {consistencyQuery.isError && <ErrorState message="Couldn't load consistency." onRetry={() => consistencyQuery.refetch()} />}
          {consistencyQuery.data && <ConsistencyCard consistency={consistencyQuery.data} />}
        </Card>
      </div>

      <Card title="Strengths & areas to investigate">
        {profileQuery.isLoading && loading}
        {profileQuery.data && <StrengthsWeaknessesCard strengths={profileQuery.data.strengths} weaknesses={profileQuery.data.weaknesses} />}
      </Card>

      <SectionHeader title="Insights and recommendations" />
      <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
        <Card title="Recent insights">
          {insightsQuery.isLoading && loading}
          {insightsQuery.isError && <ErrorState message="Couldn't load insights." onRetry={() => insightsQuery.refetch()} />}
          {insightsQuery.data && <InsightsList insights={insightsQuery.data} />}
        </Card>
        <Card title="Recommendations">
          {recommendationsQuery.isLoading && loading}
          {recommendationsQuery.isError && <ErrorState message="Couldn't load recommendations." onRetry={() => recommendationsQuery.refetch()} />}
          {recommendationsQuery.data && <RecommendationsCard recommendations={recommendationsQuery.data} />}
        </Card>
      </div>

      {savedRecommendations.length > 0 && (
        <Card title="Saved">
          <RecommendationsCard recommendations={savedRecommendations} />
        </Card>
      )}
    </div>
  );
}
