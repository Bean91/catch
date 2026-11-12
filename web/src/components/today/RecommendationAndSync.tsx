import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSyncStatus, triggerSync } from "../../lib/api";
import { formatRelativeTime } from "../../lib/format";
import type { NextARace } from "../../lib/types";
import { Card } from "../ui/Card";

export function RecommendationAndSync({ recommendation, nextARace }: { recommendation: string; nextARace: NextARace | null }) {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({ queryKey: ["sync-status"], queryFn: fetchSyncStatus, refetchInterval: 60_000 });

  const syncAll = useMutation({
    mutationFn: async () => {
      // Sequential, not Promise.all: recompute_scores takes a non-blocking lock and skips
      // itself if another sync is already recomputing, so two sources finishing at once
      // can leave one of them unscored until the next scheduled sync. Also kinder to the
      // Pi's 1GB RAM than three syncs' worth of concurrent memory pressure.
      const sources = statusQuery.data?.map((s) => s.source) ?? ["garmin", "withings", "concept2"];
      const results = [];
      for (const source of sources) {
        results.push(await triggerSync(source));
      }
      return results;
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      queryClient.invalidateQueries({ queryKey: ["today"] });
    },
  });

  return (
    <Card className="flex h-full flex-col">
      <p className="text-lg font-medium text-text-primary lg:text-xl">{recommendation}</p>

      {nextARace && (
        <p className="mt-2 text-sm text-text-secondary">
          Next A race:{" "}
          {nextARace.id != null ? (
            <Link to={`/calendar/events/${nextARace.id}`} className="text-text-primary underline">
              {nextARace.name}
            </Link>
          ) : (
            <span className="text-text-primary">{nextARace.name}</span>
          )}
          <span className="font-mono-nums"> · {nextARace.days_to_go}d</span>
          {nextARace.taper && (
            <span className="ml-2 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">Taper</span>
          )}
        </p>
      )}

      {/* Absorbs the extra height the grid stretches this card to (at lg:, it sits next to
          the taller erg card) so the sync row anchors to the bottom instead of leaving a
          gap under the recommendation text. */}
      <div className="mt-4 flex-1" aria-hidden />

      <div className="flex flex-col gap-2 border-t border-border pt-3 sm:flex-row sm:items-center sm:justify-between">
        <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-text-tertiary">
          {(statusQuery.data ?? []).map((s) => (
            <li key={s.source} className="inline-flex items-center gap-1.5">
              <span
                aria-hidden
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: s.last_error ? "var(--band-red)" : "var(--band-green)" }}
              />
              <span className="capitalize">{s.source}</span>
              <span>{s.last_error ? "failed" : formatRelativeTime(s.last_success_at)}</span>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => syncAll.mutate()}
          disabled={syncAll.isPending}
          className="min-h-11 shrink-0 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {syncAll.isPending ? "Syncing…" : "Sync now"}
        </button>
      </div>
    </Card>
  );
}
