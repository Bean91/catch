import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { fetchWorkouts } from "../lib/api";
import type { WorkoutCategory } from "../lib/types";
import { WorkoutRow } from "../components/workouts/WorkoutRow";
import { CardSkeleton } from "../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";

const FILTERS: { value: WorkoutCategory | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "erg", label: "Erg" },
  { value: "on_water", label: "On-water" },
  { value: "other", label: "Other" },
];

export function WorkoutsPage() {
  const [filter, setFilter] = useState<WorkoutCategory | "all">("all");
  const sentinelRef = useRef<HTMLDivElement>(null);

  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["workouts", filter],
    queryFn: ({ pageParam }) => fetchWorkouts({ category: filter === "all" ? undefined : filter, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) {
        fetchNextPage();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const items = data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-text-primary">Workouts</h1>

      <div className="flex gap-2 overflow-x-auto pb-1" role="tablist" aria-label="Filter by type">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            role="tab"
            aria-selected={filter === f.value}
            onClick={() => setFilter(f.value)}
            className={`min-h-11 shrink-0 rounded-full border px-4 text-sm font-medium transition-colors ${
              filter === f.value
                ? "border-accent bg-accent text-accent-contrast"
                : "border-border bg-surface text-text-secondary hover:border-accent/40"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="flex flex-col gap-3">
          <CardSkeleton lines={1} />
          <CardSkeleton lines={1} />
          <CardSkeleton lines={1} />
        </div>
      )}

      {isError && <ErrorState message="Couldn't load workouts." onRetry={() => refetch()} />}

      {!isLoading && !isError && items.length === 0 && <EmptyState message="No workouts in this filter yet." />}

      {!isLoading && !isError && items.length > 0 && (
        <div className="flex flex-col gap-2">
          {items.map((w) => (
            <WorkoutRow key={w.id} workout={w} />
          ))}
          <div ref={sentinelRef} aria-hidden className="h-1" />
          {isFetchingNextPage && <CardSkeleton lines={1} />}
        </div>
      )}
    </div>
  );
}
