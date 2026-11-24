import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { WorkoutRow } from "../components/workouts/WorkoutRow";
import { ButtonLink } from "../components/ui/Button";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { PageHeader, SectionHeader } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { fetchWorkouts } from "../lib/api";
import { TRAIN_ITEMS } from "../lib/navigation";

/**
 * The Train tab's hub (session 35): every training destination one tap away, the latest sessions, and the two things people
 * start from here most. It owns no data of its own — the recent list is the first page of the same activities endpoint.
 */
export function TrainPage() {
  const recent = useQuery({ queryKey: ["workouts-recent"], queryFn: () => fetchWorkouts({}) });
  const latest = recent.data?.items.slice(0, 4) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Training"
        title="Train"
        subtitle="Log, review and plan the work."
        actions={
          <>
            <ButtonLink to="/gym" variant="primary">
              Start gym session
            </ButtonLink>
            <ButtonLink to="/tests">Log a test</ButtonLink>
          </>
        }
      />

      <ul className="grid grid-cols-2 gap-3 lg:grid-cols-3" aria-label="Training sections">
        {TRAIN_ITEMS.map(({ to, label, Icon, blurb }) => (
          <li key={to} className="min-w-0">
            <Link
              to={to}
              className="glass-secondary group flex h-full min-w-0 flex-col gap-3 rounded-lg border border-border bg-surface p-4 shadow-[var(--highlight),var(--shadow-1)] transition-[border-color,transform] duration-150 hover:border-accent/40 active:scale-[0.99]"
            >
              <span aria-hidden className="flex h-9 w-9 items-center justify-center rounded-md bg-accent-soft text-accent transition-colors group-hover:bg-accent group-hover:text-accent-contrast">
                <Icon className="h-5 w-5" />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-text-primary">{label}</span>
                {blurb && <span className="mt-0.5 block text-xs leading-snug text-text-tertiary">{blurb}</span>}
              </span>
            </Link>
          </li>
        ))}
      </ul>

      <section className="flex flex-col gap-3" aria-labelledby="recent-sessions">
        <SectionHeader
          id="recent-sessions"
          title="Recent sessions"
          action={
            <Link to="/workouts" className="text-sm font-medium text-accent hover:underline">
              All workouts
            </Link>
          }
        />
        {recent.isLoading ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : recent.isError ? (
          <ErrorState message="Couldn't load your recent sessions." onRetry={() => recent.refetch()} />
        ) : latest.length === 0 ? (
          <EmptyState message="No sessions yet. Connect a source in Settings, or log one in the gym." />
        ) : (
          <ul className="flex flex-col gap-2">
            {latest.map((w) => (
              <li key={w.id}>
                <WorkoutRow workout={w} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
