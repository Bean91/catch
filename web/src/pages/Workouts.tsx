import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { bulkEditActivities, fetchWorkouts } from "../lib/api";
import type { WorkoutCategory } from "../lib/types";
import { WorkoutRow } from "../components/workouts/WorkoutRow";
import { CardSkeleton } from "../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";

const FILTERS: { value: WorkoutCategory | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "erg", label: "Erg" },
  { value: "on_water", label: "On-water" },
  { value: "strength", label: "Strength" },
  { value: "other", label: "Other" },
];

export function WorkoutsPage() {
  const [filter, setFilter] = useState<WorkoutCategory | "all">("all");
  const sentinelRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const [bulkMode, setBulkMode] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkTag, setBulkTag] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);

  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["workouts", filter],
    queryFn: ({ pageParam }) => fetchWorkouts({ category: filter === "all" ? undefined : filter, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });

  const toggleSelected = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const runBulk = async (patch: Parameters<typeof bulkEditActivities>[1]) => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    try {
      await bulkEditActivities(Array.from(selected), patch);
      await queryClient.invalidateQueries({ queryKey: ["workouts"] });
      setSelected(new Set());
      setBulkTag("");
    } finally {
      setBulkBusy(false);
    }
  };

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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-text-primary">Workouts</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/library" className="min-h-11 rounded-full border border-border bg-surface px-4 text-sm font-medium text-text-secondary transition-colors hover:border-accent/40 flex items-center">
            Library
          </Link>
          <Link to="/feedback" className="min-h-11 rounded-full border border-border bg-surface px-4 text-sm font-medium text-text-secondary transition-colors hover:border-accent/40 flex items-center">
            Feedback
          </Link>
          <Link to="/tests" className="min-h-11 rounded-full border border-border bg-surface px-4 text-sm font-medium text-text-secondary transition-colors hover:border-accent/40 flex items-center">
            Tests
          </Link>
          <Link to="/routes" className="min-h-11 rounded-full border border-border bg-surface px-4 text-sm font-medium text-text-secondary transition-colors hover:border-accent/40 flex items-center">
            Routes
          </Link>
          <Link to="/workouts/duplicates" className="min-h-11 rounded-full border border-border bg-surface px-4 text-sm font-medium text-text-secondary transition-colors hover:border-accent/40 flex items-center">
            Duplicates
          </Link>
          <button
            type="button"
            onClick={() => {
              setBulkMode((v) => !v);
              setSelected(new Set());
            }}
            className={`min-h-11 rounded-full border px-4 text-sm font-medium transition-colors ${
              bulkMode ? "border-accent bg-accent text-accent-contrast" : "border-border bg-surface text-text-secondary hover:border-accent/40"
            }`}
          >
            {bulkMode ? "Done" : "Select"}
          </button>
        </div>
      </div>

      {bulkMode && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-2 px-4 py-3">
          <span className="font-mono-nums text-sm text-text-secondary">{selected.size} selected</span>
          <select
            defaultValue=""
            disabled={bulkBusy || selected.size === 0}
            onChange={(e) => {
              if (e.target.value) runBulk({ sport_family: e.target.value as "cycling" | "rowing" | "running" | "strength" | "other" });
              e.target.value = "";
            }}
            className="min-h-9 rounded-md border border-border bg-surface px-2 text-sm text-text-primary disabled:opacity-40"
          >
            <option value="" disabled>
              Retype as…
            </option>
            <option value="rowing">Rowing</option>
            <option value="cycling">Cycling</option>
            <option value="running">Running</option>
            <option value="strength">Strength</option>
            <option value="other">Other</option>
          </select>
          <input
            value={bulkTag}
            onChange={(e) => setBulkTag(e.target.value)}
            placeholder="tag, e.g. race"
            className="min-h-9 w-32 rounded-md border border-border bg-surface px-2 text-sm text-text-primary"
          />
          <button
            type="button"
            disabled={bulkBusy || selected.size === 0 || !bulkTag}
            onClick={() => runBulk({ tags: [bulkTag] })}
            className="min-h-9 rounded-md border border-border px-3 text-sm text-text-secondary disabled:opacity-40"
          >
            Tag
          </button>
          <button
            type="button"
            disabled={bulkBusy || selected.size === 0}
            onClick={() => runBulk({ exclude_from_totals: true })}
            className="min-h-9 rounded-md border border-border px-3 text-sm text-text-secondary disabled:opacity-40"
          >
            Exclude from totals
          </button>
          <button
            type="button"
            disabled={bulkBusy || selected.size === 0}
            onClick={() => runBulk({ exclude_from_totals: false })}
            className="min-h-9 rounded-md border border-border px-3 text-sm text-text-secondary disabled:opacity-40"
          >
            Include in totals
          </button>
        </div>
      )}

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
            <WorkoutRow key={w.id} workout={w} selectable={bulkMode} selected={selected.has(w.id)} onToggleSelected={toggleSelected} />
          ))}
          <div ref={sentinelRef} aria-hidden className="h-1" />
          {isFetchingNextPage && <CardSkeleton lines={1} />}
        </div>
      )}
    </div>
  );
}
