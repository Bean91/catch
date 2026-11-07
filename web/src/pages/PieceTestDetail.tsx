import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { fetchPieceTestDetail } from "../lib/api";
import { formatDistance, formatDuration, formatShortDate, formatSplit } from "../lib/format";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { SplitBarChart } from "../components/tests/SplitBarChart";
import { PieceCard } from "../components/pieces/PieceCard";

/** The piece equivalent of TestDetailPage (session 15) — a separate route/page rather than
 * folding into that one, since a piece additionally needs its own splits-edit/photo card
 * (PieceCard), and "activity.id" here is the *containing* session, not unique to the piece
 * (see routes_tests.py's comment on this exact route). */
export function PieceTestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const pieceId = Number(id);
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["piece-test-detail", pieceId], queryFn: () => fetchPieceTestDetail(pieceId) });

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <CardSkeleton lines={2} />
        <CardSkeleton lines={4} />
      </div>
    );
  }
  if (isError || !data) {
    return <ErrorState message="Couldn't load this piece." onRetry={() => refetch()} />;
  }

  const { activity, piece, test_type, plan, pacing_analysis, compare_to_earlier, w_per_kg } = data;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link to="/tests" className="text-sm text-text-tertiary transition-colors hover:text-text-secondary">
          ← Test center
        </Link>
        <div className="mt-1 flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold text-text-primary">
            {test_type} piece — {activity.local_date ? formatShortDate(activity.local_date) : "—"}
          </h1>
          <Link to={`/workouts/${activity.id}`} className="text-xs text-text-tertiary transition-colors hover:text-text-secondary">
            Full workout detail →
          </Link>
        </div>
        <p className="font-mono-nums text-sm text-text-secondary">
          {formatDistance(piece.distance_m)} in {formatDuration(piece.duration_s)}
          {w_per_kg != null && <> · {w_per_kg.toFixed(2)} W/kg</>}
        </p>
      </div>

      {pacing_analysis && (
        <Card title="Pacing">
          <SplitBarChart splits={pacing_analysis.splits} vsPlan={pacing_analysis.vs_plan} />
          <div className="mt-3 grid grid-cols-3 gap-3 text-center">
            <div>
              <div className="text-xs text-text-tertiary">Start</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatSplit(pacing_analysis.segments.start)}</div>
            </div>
            <div>
              <div className="text-xs text-text-tertiary">Middle 1000</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatSplit(pacing_analysis.segments.middle_1000)}</div>
            </div>
            <div>
              <div className="text-xs text-text-tertiary">Sprint</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatSplit(pacing_analysis.segments.sprint)}</div>
            </div>
          </div>
          <div className="mt-3 flex flex-col gap-1 border-t border-border pt-3 text-sm text-text-secondary">
            <span>
              Even split: <span className="font-mono-nums text-text-primary">{formatSplit(pacing_analysis.even_split_s)}</span>
              {pacing_analysis.deviation_from_even_pct != null && <> ({pacing_analysis.deviation_from_even_pct.toFixed(1)}% spread)</>}
            </span>
            {pacing_analysis.worst_split_vs_even && (
              <span>
                Slowest: split {pacing_analysis.worst_split_vs_even.split_index}, {pacing_analysis.worst_split_vs_even.seconds_lost_vs_even.toFixed(1)}s
                slower than even.
              </span>
            )}
          </div>
          {plan && <p className="mt-2 text-xs text-text-tertiary">Dashed line is the saved {plan.style.replace(/_/g, " ")} plan.</p>}
        </Card>
      )}

      {compare_to_earlier && (
        <Card title="Compare to earlier">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-xs text-text-tertiary">{compare_to_earlier.date ? formatShortDate(compare_to_earlier.date) : "—"}</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatDuration(compare_to_earlier.duration_s)}</div>
            </div>
            <span className="text-text-tertiary">→</span>
            <div>
              <div className="text-xs text-text-tertiary">{activity.local_date ? formatShortDate(activity.local_date) : "—"}</div>
              <div className="font-mono-nums text-sm text-text-primary">{formatDuration(piece.duration_s)}</div>
            </div>
          </div>
        </Card>
      )}

      <Card title="Piece">
        <PieceCard piece={piece} canonicalId={activity.id} />
      </Card>
    </div>
  );
}
