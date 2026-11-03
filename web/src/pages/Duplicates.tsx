import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchDuplicates, markNotDuplicate, mergeActivities } from "../lib/api";
import { formatDuration, formatShortDate } from "../lib/format";
import type { DuplicatePairSide } from "../lib/types";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";

function Side({ side }: { side: DuplicatePairSide }) {
  return (
    <div className="flex-1 rounded-md border border-border bg-surface-2 p-3">
      <div className="text-sm font-medium text-text-primary">{side.source}</div>
      <div className="text-xs text-text-tertiary">{side.start ? formatShortDate(side.start) : "—"}</div>
      <div className="font-mono-nums text-xs text-text-secondary">{formatDuration(side.duration)}</div>
    </div>
  );
}

export function DuplicatesPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["duplicates"], queryFn: fetchDuplicates });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["duplicates"] });
    queryClient.invalidateQueries({ queryKey: ["workouts"] });
  };
  const merge = useMutation({
    mutationFn: ({ a, b }: { a: number; b: number }) => mergeActivities(a, b),
    onSuccess: invalidate,
  });
  const notDuplicate = useMutation({
    mutationFn: ({ a, b }: { a: number; b: number }) => markNotDuplicate(a, b),
    onSuccess: invalidate,
  });

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link to="/workouts" className="text-sm text-text-tertiary transition-colors hover:text-text-secondary">
          ← Workouts
        </Link>
        <h1 className="mt-1 text-lg font-semibold text-text-primary">Possible duplicates</h1>
        <p className="text-sm text-text-tertiary">
          Flagged by the matching engine (same sport, overlapping time, similar duration) but below the auto-merge threshold — review and merge or dismiss.
        </p>
      </div>

      {isLoading && (
        <div className="flex flex-col gap-3">
          <CardSkeleton lines={2} />
          <CardSkeleton lines={2} />
        </div>
      )}
      {isError && <ErrorState message="Couldn't load duplicates." onRetry={() => refetch()} />}
      {!isLoading && !isError && (data?.length ?? 0) === 0 && <EmptyState message="No possible duplicates right now." />}

      {data?.map((pair, i) => (
        <Card key={i}>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Side side={pair.a} />
            <span className="self-center text-xs text-text-tertiary">vs</span>
            <Side side={pair.b} />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3">
            <span className="font-mono-nums text-xs text-text-tertiary">score {pair.score.toFixed(2)}</span>
            {pair.hard_block && <span className="text-xs text-text-tertiary">indoor/outdoor mismatch — won't auto-merge</span>}
            <button
              type="button"
              disabled={merge.isPending}
              onClick={() => merge.mutate({ a: pair.a.activity_id, b: pair.b.activity_id })}
              className="min-h-9 rounded-md border border-accent bg-accent px-3 text-sm font-medium text-accent-contrast disabled:opacity-40"
            >
              Merge
            </button>
            <button
              type="button"
              disabled={notDuplicate.isPending}
              onClick={() => notDuplicate.mutate({ a: pair.a.activity_id, b: pair.b.activity_id })}
              className="min-h-9 rounded-md border border-border px-3 text-sm text-text-secondary disabled:opacity-40"
            >
              Not a duplicate
            </button>
          </div>
        </Card>
      ))}
    </div>
  );
}
