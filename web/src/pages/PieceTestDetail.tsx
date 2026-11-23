import { useQuery } from "@tanstack/react-query";
import { BackLink } from "../components/ui/PageHeader";
import { Link, useParams } from "react-router-dom";
import { fetchPieceTestDetail } from "../lib/api";
import { formatDistance, formatDuration, formatShortDate, formatSplit, splitUnitLabel } from "../lib/format";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { CompareCard, PacingCard } from "../components/tests/PacingCard";
import { PieceCard } from "../components/pieces/PieceCard";
import { MassPower } from "../components/pieces/MassPower";

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

  const { activity, piece, test_type, plan, pacing_analysis, compare_to_earlier } = data;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <BackLink to="/tests">Test center</BackLink>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-2">
          <h1 className="text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]">
            {piece.modality === "bike" ? "Bike " : ""}
            {test_type} piece — {activity.local_date ? formatShortDate(activity.local_date) : "—"}
          </h1>
          <Link to={`/workouts/${activity.id}`} className="shrink-0 text-sm font-medium text-accent hover:underline">
            Full workout detail →
          </Link>
        </div>
        <p className="font-mono-nums text-sm text-text-secondary">
          {formatDistance(piece.distance_m)} in {formatDuration(piece.duration_s)}
          {piece.avg_split_s != null && (
            <>
              {" "}· {formatSplit(piece.avg_split_s)}
              {splitUnitLabel(piece.split_unit_m)}
            </>
          )}
        </p>
        <div className="mt-1">
          <MassPower watts={piece.avg_watts} mass={data} modality={piece.modality} />
        </div>
      </div>

      {pacing_analysis && <PacingCard pacing={pacing_analysis} planStyle={plan?.style} />}

      {compare_to_earlier && <CompareCard title="Compare to earlier" earlier={compare_to_earlier} nowDate={activity.local_date} nowDurationS={piece.duration_s} />}

      <Card title="Piece">
        <PieceCard piece={piece} canonicalId={activity.id} />
      </Card>
    </div>
  );
}
