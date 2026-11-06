import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { confirmTest, fetchPbs, fetchProjection, fetchTestCandidates, fetchTests } from "../lib/api";
import { formatDistance, formatDuration, formatShortDate, formatTimeTenths } from "../lib/format";
import { ERG_TEST_TYPES, type ErgTestType } from "../lib/types";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { PacingPlanDialog } from "../components/tests/PacingPlanDialog";
import { PbTable } from "../components/workouts/PbTable";

export function TestCenterPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ErgTestType | null>(null);
  const [planOpen, setPlanOpen] = useState(false);

  const candidatesQuery = useQuery({ queryKey: ["test-candidates"], queryFn: fetchTestCandidates });
  const testsQuery = useQuery({ queryKey: ["tests", filter], queryFn: () => fetchTests(filter ?? undefined) });
  const pbsQuery = useQuery({ queryKey: ["pbs"], queryFn: fetchPbs });
  const projectionQuery = useQuery({
    queryKey: ["test-projection", filter],
    queryFn: () => fetchProjection(filter!),
    enabled: !!filter,
  });

  const confirm = useMutation({
    mutationFn: ({ id, type }: { id: number; type: ErgTestType }) => confirmTest(id, type),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["test-candidates"] });
      queryClient.invalidateQueries({ queryKey: ["tests"] });
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-text-primary">Test center</h1>
          <p className="text-sm text-text-tertiary">500m/1k/2k/5k/6k, 30min r20, 60min, and custom erg tests.</p>
        </div>
        <button
          type="button"
          onClick={() => setPlanOpen(true)}
          className="min-h-11 shrink-0 rounded-full border border-accent bg-accent px-4 text-sm font-medium text-accent-contrast"
        >
          Build pacing plan
        </button>
      </div>

      {candidatesQuery.data != null && candidatesQuery.data.length > 0 && (
        <Card title="Looks like a test — confirm?">
          <div className="flex flex-col gap-2">
            {candidatesQuery.data.map((c) => (
              <div key={c.canonical_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3">
                <div className="text-sm text-text-primary">
                  {c.title ?? "Erg piece"} — {c.date ? formatShortDate(c.date) : "—"}
                  <span className="ml-2 font-mono-nums text-text-tertiary">
                    {formatDistance(c.distance_m)} / {formatDuration(c.duration_s)}
                  </span>
                </div>
                <button
                  type="button"
                  disabled={confirm.isPending}
                  onClick={() => confirm.mutate({ id: c.canonical_id, type: c.suggested_test_type })}
                  className="min-h-9 rounded-md border border-accent bg-accent px-3 text-sm font-medium text-accent-contrast disabled:opacity-50"
                >
                  Confirm as {c.suggested_test_type}
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="Personal bests">
        {pbsQuery.isLoading ? <CardSkeleton lines={3} /> : pbsQuery.data ? <PbTable pbs={pbsQuery.data} /> : null}
      </Card>

      <Card title="Confirmed tests">
        <div className="mb-3 flex flex-wrap gap-2" role="tablist" aria-label="Test type">
          <button
            type="button"
            onClick={() => setFilter(null)}
            className={`min-h-9 rounded-full border px-3 text-xs font-medium ${filter === null ? "border-accent text-accent" : "border-border text-text-tertiary"}`}
          >
            All
          </button>
          {ERG_TEST_TYPES.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setFilter(t)}
              className={`min-h-9 rounded-full border px-3 text-xs font-medium ${filter === t ? "border-accent text-accent" : "border-border text-text-tertiary"}`}
            >
              {t}
            </button>
          ))}
        </div>

        {filter && (
          <div className="mb-3 rounded-md bg-surface-2 p-3 text-xs text-text-secondary">
            {projectionQuery.data ? (
              projectionQuery.data.value != null ? (
                <>
                  Projected {filter}: {formatTimeTenths(projectionQuery.data.value)} by {formatShortDate(projectionQuery.data.target_date)}
                  {projectionQuery.data.range && (
                    <> (range {formatTimeTenths(projectionQuery.data.range[0])}–{formatTimeTenths(projectionQuery.data.range[1])})</>
                  )}
                  . {projectionQuery.data.explanation}
                </>
              ) : (
                projectionQuery.data.explanation
              )
            ) : (
              "Loading projection…"
            )}
          </div>
        )}

        {testsQuery.isLoading && <CardSkeleton lines={2} />}
        {testsQuery.isError && <ErrorState message="Couldn't load tests." onRetry={() => testsQuery.refetch()} />}
        {testsQuery.data && testsQuery.data.length === 0 && <EmptyState message="No confirmed tests yet." />}
        {testsQuery.data && testsQuery.data.length > 0 && (
          <div className="flex flex-col gap-2">
            {testsQuery.data.map((t) => (
              <Link
                key={t.canonical_id}
                to={`/tests/${t.canonical_id}`}
                className="flex items-center justify-between gap-2 rounded-md border border-border p-3 transition-colors hover:border-accent/40"
              >
                <div className="text-sm text-text-primary">
                  {t.test_type} — {t.date ? formatShortDate(t.date) : "—"}
                </div>
                <div className="font-mono-nums text-sm text-text-secondary">{formatDuration(t.duration_s)}</div>
              </Link>
            ))}
          </div>
        )}
      </Card>

      <PacingPlanDialog open={planOpen} onOpenChange={setPlanOpen} />
    </div>
  );
}
