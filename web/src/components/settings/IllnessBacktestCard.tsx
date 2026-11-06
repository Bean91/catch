import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchIllnessBacktest, markIllnessBacktest } from "../../lib/api";
import { formatShortDate, formatPercent } from "../../lib/format";
import { Card } from "../ui/Card";

/** Task Part B.4: list every night history would have flagged, let the athlete mark right/
 * wrong, report precision over what's actually been marked. A review/debug tool, not a
 * polished feature screen — plain list, no chart. */
export function IllnessBacktestCard() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["illness-backtest"], queryFn: fetchIllnessBacktest });

  const mark = useMutation({
    mutationFn: ({ date, correct }: { date: string; correct: boolean }) => markIllnessBacktest(date, correct),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["illness-backtest"] }),
  });

  return (
    <Card title="Illness detector backtest">
      <p className="mb-3 text-xs text-text-tertiary">
        Every night this would have flagged "watch" or "likely" — mark each one right or wrong to track precision.
      </p>
      {isLoading || !data ? (
        <p className="text-sm text-text-tertiary">Loading…</p>
      ) : data.flagged.length === 0 ? (
        <p className="text-sm text-text-tertiary">No flagged nights yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {data.marked_count > 0 && (
            <p className="text-sm text-text-primary">
              Precision: {formatPercent((data.precision ?? 0) * 100)} over {data.marked_count} marked night(s).
            </p>
          )}
          {data.flagged.map((f) => (
            <div key={f.date} className="rounded-md border border-border p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-text-primary">
                  {formatShortDate(f.date)} — {f.level}
                </span>
                {f.dismissed && <span className="text-xs text-text-tertiary">dismissed ({f.dismiss_reason})</span>}
              </div>
              <p className="mt-1 text-xs text-text-secondary">{f.explanation}</p>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={() => mark.mutate({ date: f.date, correct: true })}
                  className={`min-h-11 flex-1 rounded-md border text-xs font-medium ${
                    f.backtest_mark === "correct" ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"
                  }`}
                >
                  Correct
                </button>
                <button
                  type="button"
                  onClick={() => mark.mutate({ date: f.date, correct: false })}
                  className={`min-h-11 flex-1 rounded-md border text-xs font-medium ${
                    f.backtest_mark === "incorrect" ? "border-accent bg-accent/15 text-accent" : "border-border text-text-secondary"
                  }`}
                >
                  Wrong
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
