import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Button, buttonClass } from "../components/ui/Button";
import { controlBase } from "../components/ui/Field";
import { PageHeader } from "../components/ui/PageHeader";
import { PillNav } from "../components/ui/PillNav";
import { Segmented } from "../components/ui/Segmented";
import { useEffect, useRef, useState } from "react";
import { bulkEditActivities, fetchWorkouts } from "../lib/api";
import type { WorkoutCategory } from "../lib/types";
import { WorkoutRow } from "../components/workouts/WorkoutRow";
import { MergeSheet } from "../components/workouts/MergeSheet";
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
  // Session 36: search your own words (title, notes, conditions, equipment, tags, the day's note) and filter by tag or by "has notes".
  const [searchText, setSearchText] = useState("");
  const [q, setQ] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [notesOnly, setNotesOnly] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setQ(searchText.trim()), 300);
    return () => clearTimeout(id);
  }, [searchText]);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const [bulkMode, setBulkMode] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkTag, setBulkTag] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);

  const { data, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["workouts", filter, q, tagFilter, notesOnly],
    queryFn: ({ pageParam }) => fetchWorkouts({ category: filter === "all" ? undefined : filter, cursor: pageParam, q: q || undefined, tag: tagFilter.trim() || undefined, hasNotes: notesOnly || undefined }),
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

  const runBulk = async (patch: Parameters<typeof bulkEditActivities>[1], opts?: Parameters<typeof bulkEditActivities>[2]) => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    try {
      await bulkEditActivities(Array.from(selected), patch, opts);
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
      <PageHeader
        eyebrow="Training"
        title="Workouts"
        subtitle="Every session from every source, merged into one record each."
        actions={
          <Button
            size="sm"
            variant={bulkMode ? "primary" : "secondary"}
            onClick={() => {
              setBulkMode((v) => !v);
              setSelected(new Set());
            }}
          >
            {bulkMode ? "Done" : "Select"}
          </Button>
        }
      />
      <PillNav
        label="Related"
        items={[
          { to: "/library", label: "Library" },
          { to: "/feedback", label: "Feedback" },
          { to: "/tests", label: "Tests" },
          { to: "/routes", label: "Routes" },
          { to: "/workouts/duplicates", label: "Duplicates" },
        ]}
      />

      {bulkMode && (
        <div className="sticky top-[calc(var(--shell-top)+env(safe-area-inset-top)+8px)] z-10 flex flex-wrap items-center gap-2 rounded-lg border border-accent/30 bg-surface-3/95 px-4 py-3 shadow-raised backdrop-blur lg:top-4">
          <span className="font-mono-nums text-sm text-text-secondary">{selected.size} selected</span>
          <select
            defaultValue=""
            disabled={bulkBusy || selected.size === 0}
            onChange={(e) => {
              if (e.target.value) runBulk({ sport_family: e.target.value as "cycling" | "rowing" | "running" | "strength" | "other" });
              e.target.value = "";
            }}
            className={`${controlBase} min-h-9 text-sm`}
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
            className={`${controlBase} min-h-9 w-32 text-sm`}
          />
          <button
            type="button"
            disabled={bulkBusy || selected.size === 0 || !bulkTag}
            onClick={() => runBulk({}, { tagsAdd: [bulkTag.trim()] })}
            className={buttonClass("secondary", "sm")}
          >
            Tag
          </button>
          <button
            type="button"
            disabled={bulkBusy || selected.size === 0}
            onClick={() => runBulk({ exclude_from_totals: true })}
            className={buttonClass("secondary", "sm")}
          >
            Exclude from totals
          </button>
          <button
            type="button"
            disabled={bulkBusy || selected.size === 0}
            onClick={() => runBulk({ exclude_from_totals: false })}
            className={buttonClass("secondary", "sm")}
          >
            Include in totals
          </button>
          {selected.size >= 2 && (
            <button
              type="button"
              disabled={bulkBusy}
              onClick={() => setMergeOpen(true)}
              className={buttonClass("primary", "sm")}
              data-testid="merge-selected"
            >
              Merge…
            </button>
          )}
        </div>
      )}
      <MergeSheet
        open={mergeOpen}
        ids={Array.from(selected)}
        onClose={() => setMergeOpen(false)}
        onMerged={() => {
          setMergeOpen(false);
          setSelected(new Set());
          setBulkMode(false);
          void queryClient.invalidateQueries({ queryKey: ["workouts"] });
          void queryClient.invalidateQueries({ queryKey: ["today"] });
        }}
      />

      <Segmented label="Filter by type" value={filter} onChange={setFilter} options={FILTERS} className="self-start" />
      <div className="flex flex-wrap items-center gap-2" role="search" aria-label="Search your workouts">
        <input
          type="search"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Search notes, conditions, equipment, tags…"
          aria-label="Search workouts"
          className={`${controlBase} min-h-11 min-w-0 flex-1 basis-56 text-sm`}
          data-testid="workout-search"
        />
        <input
          value={tagFilter}
          onChange={(e) => setTagFilter(e.target.value)}
          placeholder="Tag"
          aria-label="Filter by tag"
          className={`${controlBase} min-h-11 w-28 min-w-0 text-sm`}
        />
        <label className="flex min-h-11 items-center gap-2 text-sm text-text-secondary">
          <input type="checkbox" checked={notesOnly} onChange={(e) => setNotesOnly(e.target.checked)} className="h-5 w-5 accent-accent" />
          Has notes
        </label>
      </div>

      {isLoading && (
        <div className="flex flex-col gap-3">
          <CardSkeleton lines={1} />
          <CardSkeleton lines={1} />
          <CardSkeleton lines={1} />
        </div>
      )}

      {isError && <ErrorState message="Couldn't load workouts." onRetry={() => refetch()} />}

      {!isLoading && !isError && items.length === 0 && <EmptyState message={q || tagFilter.trim() || notesOnly ? "Nothing matches that search." : "No workouts in this filter yet."} />}

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
