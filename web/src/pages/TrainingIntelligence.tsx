import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { PerformanceTrendsCard } from "../components/intelligence/PerformanceTrendsCard";
import { ConsistencyCard } from "../components/intelligence/ConsistencyCard";
import { InsightsList } from "../components/intelligence/InsightCard";
import { RecommendationsCard } from "../components/intelligence/RecommendationCard";
import { StrengthsWeaknessesCard } from "../components/intelligence/StrengthsWeaknessesCard";
import { TrainingDistributionCard } from "../components/intelligence/TrainingDistributionCard";
import { TrainingProfileCard } from "../components/intelligence/TrainingProfileCard";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { CardSkeleton } from "../components/ui/Skeleton";
import {
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

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Training intelligence</h1>
        <Link to="/trends" className="text-sm font-medium text-accent">
          Back to Trends
        </Link>
      </div>

      {profileQuery.isLoading && <CardSkeleton lines={3} />}
      {profileQuery.isError && <ErrorState message="Couldn't load the training profile." onRetry={() => profileQuery.refetch()} />}
      {profileQuery.data && <TrainingProfileCard profile={profileQuery.data} />}

      <Card title="Performance trajectory">
        {trendsQuery.isLoading && <CardSkeleton lines={2} />}
        {trendsQuery.isError && <ErrorState message="Couldn't load performance trends." onRetry={() => trendsQuery.refetch()} />}
        {trendsQuery.data && <PerformanceTrendsCard buckets={trendsQuery.data.buckets} />}
      </Card>

      <Card title="Training distribution (last 12 weeks)">
        {distributionQuery.isLoading && <CardSkeleton lines={2} />}
        {distributionQuery.isError && <ErrorState message="Couldn't load training distribution." onRetry={() => distributionQuery.refetch()} />}
        {distributionQuery.data && <TrainingDistributionCard weeks={distributionQuery.data.weeks} />}
      </Card>

      <Card title="Consistency">
        {consistencyQuery.isLoading && <CardSkeleton lines={2} />}
        {consistencyQuery.isError && <ErrorState message="Couldn't load consistency." onRetry={() => consistencyQuery.refetch()} />}
        {consistencyQuery.data && <ConsistencyCard consistency={consistencyQuery.data} />}
      </Card>

      <Card title="Strengths & areas to investigate">
        {profileQuery.data && <StrengthsWeaknessesCard strengths={profileQuery.data.strengths} weaknesses={profileQuery.data.weaknesses} />}
      </Card>

      <Card title="Recent insights">
        {insightsQuery.isLoading && <CardSkeleton lines={2} />}
        {insightsQuery.isError && <ErrorState message="Couldn't load insights." onRetry={() => insightsQuery.refetch()} />}
        {insightsQuery.data && <InsightsList insights={insightsQuery.data} />}
      </Card>

      <Card title="Recommendations">
        {recommendationsQuery.isLoading && <CardSkeleton lines={2} />}
        {recommendationsQuery.isError && <ErrorState message="Couldn't load recommendations." onRetry={() => recommendationsQuery.refetch()} />}
        {recommendationsQuery.data && <RecommendationsCard recommendations={recommendationsQuery.data} />}
      </Card>

      {savedRecommendations.length > 0 && (
        <Card title="Saved">
          <RecommendationsCard recommendations={savedRecommendations} />
        </Card>
      )}
    </div>
  );
}
