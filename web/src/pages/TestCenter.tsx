import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, buttonClass } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";
import { Segmented } from "../components/ui/Segmented";
import { useState } from "react";
import { Link } from "react-router-dom";
import { confirmTest, fetchBikePieces, fetchPbs, fetchProjection, fetchTestCandidates, fetchTests, isMock } from "../lib/api";
import { isPublic } from "../lib/deployment";
import { formatDistance, formatDuration, formatShortDate, formatTimeTenths } from "../lib/format";
import { ERG_TEST_TYPES, type ErgTestType } from "../lib/types";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { PacingPlanDialog } from "../components/tests/PacingPlanDialog";
import { AddPieceDialog } from "../components/pieces/AddPieceDialog";
import { PbTable } from "../components/workouts/PbTable";

export function TestCenterPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ErgTestType | null>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [addPieceOpen, setAddPieceOpen] = useState(false);

  const candidatesQuery = useQuery({ queryKey: ["test-candidates"], queryFn: fetchTestCandidates });
  const testsQuery = useQuery({ queryKey: ["tests", filter], queryFn: () => fetchTests(filter ?? undefined) });
  const pbsQuery = useQuery({ queryKey: ["pbs"], queryFn: fetchPbs });
  const bikeQuery = useQuery({ queryKey: ["tests", "bike-pieces"], queryFn: fetchBikePieces });
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
      <PageHeader
        eyebrow="Training"
        title="Test center"
        subtitle={
          <>
            500m/1k/2k/5k/6k, 30min r20, 60min, and custom erg tests.
            {(isPublic || isMock) && (
              <>
                {" "}
                <Link to="/settings/leaderboards" data-testid="tests-leaderboards-link" className="font-medium text-accent hover:underline">
                  Publish verified results to the leaderboards
                </Link>
              </>
            )}
          </>
        }
        actions={
          <>
            <Button size="sm" onClick={() => setAddPieceOpen(true)}>
              Add piece
            </Button>
            <Button size="sm" variant="primary" onClick={() => setPlanOpen(true)}>
              Build pacing plan
            </Button>
          </>
        }
      />

      {candidatesQuery.data != null && candidatesQuery.data.length > 0 && (
        <Card tone="accent" title="Looks like a test — confirm?">
          <div className="flex flex-col gap-2">
            {candidatesQuery.data.map((c) => (
              <div key={c.canonical_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-surface p-3">
                <div className="min-w-0 wrap-anywhere text-sm text-text-primary">
                  {c.title ?? "Erg piece"} — {c.date ? formatShortDate(c.date) : "—"}
                  <span className="ml-2 font-mono-nums text-text-tertiary">
                    {formatDistance(c.distance_m)} / {formatDuration(c.duration_s)}
                  </span>
                </div>
                <button
                  type="button"
                  disabled={confirm.isPending}
                  onClick={() => confirm.mutate({ id: c.canonical_id, type: c.suggested_test_type })}
                  className={buttonClass("primary", "sm")}
                >
                  Confirm as {c.suggested_test_type}
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card material="solid" title="Personal bests">
        {pbsQuery.isLoading ? (
          <CardSkeleton lines={3} />
        ) : pbsQuery.isError ? (
          <ErrorState message="Couldn't load personal bests." onRetry={() => pbsQuery.refetch()} />
        ) : pbsQuery.data ? (
          <PbTable pbs={pbsQuery.data} />
        ) : null}
      </Card>

      <Card title="Confirmed tests">
        {/* It was a tablist whose buttons weren't tabs; Segmented gives them the role, selection state and arrow keys. */}
        <Segmented
          label="Test type"
          size="sm"
          className="mb-3"
          value={filter ?? "all"}
          onChange={(v) => setFilter(v === "all" ? null : (v as typeof filter))}
          options={[{ value: "all", label: "All" }, ...ERG_TEST_TYPES.map((t) => ({ value: t, label: t }))]}
        />

        {filter && (
          <div className="mb-3 rounded-md border border-accent/25 bg-accent-soft p-3 text-sm text-text-secondary">
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
                key={`${t.kind}-${t.piece_id ?? t.canonical_id}`}
                to={t.kind === "piece" ? `/tests/piece/${t.piece_id}` : `/tests/${t.canonical_id}`}
                className="flex items-center justify-between gap-2 rounded-md border border-border p-3 transition-colors hover:border-accent/40"
              >
                <div className="text-sm text-text-primary">
                  {t.test_type} — {t.date ? formatShortDate(t.date) : "—"}
                  {t.kind === "piece" && <span className="ml-2 rounded-full border border-border px-1.5 py-0.5 text-[10px] text-text-tertiary">piece</span>}
                </div>
                <div className="font-mono-nums text-sm text-text-secondary">{formatDuration(t.duration_s)}</div>
              </Link>
            ))}
          </div>
        )}
      </Card>

      {bikeQuery.data && bikeQuery.data.length > 0 && (
        <Card title="Bike pieces">
          <p className="mb-2 text-xs text-text-tertiary">Pace per 1000 m. Bike pieces are kept apart from rowing tests, PBs and the 2k estimate.</p>
          <div className="flex flex-col gap-2" data-testid="bike-pieces">
            {bikeQuery.data.map((t) => (
              <Link
                key={`bike-${t.piece_id}`}
                to={`/tests/piece/${t.piece_id}`}
                className="flex items-center justify-between gap-2 rounded-md border border-border p-3 transition-colors hover:border-accent/40"
              >
                <div className="text-sm text-text-primary">
                  {t.test_type} — {t.date ? formatShortDate(t.date) : "—"}
                  <span className="ml-2 rounded-full border border-border px-1.5 py-0.5 text-[10px] text-text-tertiary">Bike</span>
                </div>
                <div className="font-mono-nums text-sm text-text-secondary">{formatDuration(t.duration_s)}</div>
              </Link>
            ))}
          </div>
        </Card>
      )}

      <PacingPlanDialog open={planOpen} onOpenChange={setPlanOpen} />
      <AddPieceDialog
        open={addPieceOpen}
        onClose={() => setAddPieceOpen(false)}
        onSaved={() => {
          setAddPieceOpen(false);
          queryClient.invalidateQueries({ queryKey: ["tests"] });
          queryClient.invalidateQueries({ queryKey: ["pbs"] });
        }}
      />
    </div>
  );
}
