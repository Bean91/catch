import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchLoadHistory } from "../../lib/api";
import { formatShortDate } from "../../lib/format";
import { Card } from "../ui/Card";
import { DataTable } from "../ui/DataList";
import { ErrorState } from "../ui/EmptyState";
import { InfoTip } from "../ui/InfoTip";
import { Segmented } from "../ui/Segmented";
import { CardSkeleton } from "../ui/Skeleton";
import { MiniLineChart } from "./MiniLineChart";
import { ValueBars } from "./ValueBars";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const METRIC_TEXT = { minutes: "Minutes a week", sessions: "Sessions a week", distance_m: "Distance a week", load: "Training load a week" } as const;

function fmtMetric(metric: keyof typeof METRIC_TEXT, v: number | null): string {
  if (v == null) return "—";
  if (metric === "distance_m") return `${(v / 1000).toFixed(1)} km`;
  if (metric === "sessions") return v.toFixed(1);
  return `${Math.round(v)}`;
}

/** Session 36: weekly volume, Foster's monotony and strain, where the rest days fall, and the last four weeks against the twelve
 * before — all descriptive. Nothing here is a warning: the figures are the week's own numbers with what they mean. */
export function LoadHistoryCard() {
  const [weeks, setWeeks] = useState<"12" | "26" | "52">("26");
  const q = useQuery({ queryKey: ["load-history", weeks], queryFn: () => fetchLoadHistory(Number(weeks)) });
  return (
    <Card material="solid"
      title="Load and volume"
      testId="load-history"
      action={<Segmented label="Weeks" size="sm" value={weeks} onChange={setWeeks} options={[{ value: "12", label: "12 wk" }, { value: "26", label: "26 wk" }, { value: "52", label: "1 yr" }]} />}
    >
      {q.isError ? (
        <ErrorState message="Couldn't load the training history." onRetry={() => q.refetch()} />
      ) : !q.data ? (
        <CardSkeleton lines={5} />
      ) : (
        <div className="flex flex-col gap-4">
          <div>
            <p className="mb-1 text-xs text-text-tertiary">Minutes trained each week (excluded workouts left out; a workout recorded by two devices counts once)</p>
            <ValueBars
              bars={q.data.weeks.map((w) => ({ key: w.week_start, label: formatShortDate(w.week_start), title: `${formatShortDate(w.week_start)}: ${Math.round(w.minutes)} min, ${w.sessions} sessions${w.complete ? "" : " (so far)"}`, value: Math.round(w.minutes), emphasis: !w.complete }))}
              format={(v) => `${Math.round(v)}`}
              zeroBased
              height={170}
              showValues={false}
              ariaLabel="Minutes trained each week"
            />
          </div>
          <div>
            <p className="mb-1 flex items-center gap-1 text-xs text-text-tertiary">
              Training monotony each week
              <InfoTip label="training monotony">
                Foster's monotony: the week's average daily training load divided by how much it varied from day to day (rest days count as zero). Higher means the days
                were more alike; the week's strain is its load times its monotony. It describes the week — it isn't a diagnosis or a prediction of injury.
              </InfoTip>
            </p>
            <MiniLineChart points={q.data.weeks.filter((w) => w.complete).map((w) => ({ date: w.week_start, value: w.monotony }))} color="var(--accent)" format={(v) => v.toFixed(2)} label="Weekly training monotony" height={140} />
          </div>
          {q.data.comparison && (
            <DataTable label="Recent weeks against your baseline">
              <thead>
                <tr>
                  <th />
                  <th>Last {q.data.comparison.recent_weeks} weeks</th>
                  <th>{q.data.comparison.baseline_weeks} weeks before</th>
                  <th>Change</th>
                </tr>
              </thead>
              <tbody>
                {q.data.comparison.rows.map((r) => (
                  <tr key={r.metric}>
                    <td className="text-text-secondary">{METRIC_TEXT[r.metric]}</td>
                    <td className="font-mono-nums">{fmtMetric(r.metric, r.recent)}</td>
                    <td className="font-mono-nums">{fmtMetric(r.metric, r.baseline)}</td>
                    <td className="font-mono-nums">{r.change_pct == null ? "—" : `${r.change_pct > 0 ? "+" : ""}${r.change_pct.toFixed(0)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
          <div>
            <p className="mb-1 text-xs text-text-tertiary">Days with no training logged, by weekday, over {q.data.complete_weeks} full weeks</p>
            <ul className="grid grid-cols-7 gap-1 text-center text-xs" aria-label="Days with no training by weekday">
              {q.data.rest_by_weekday.map((n, i) => (
                <li key={i} className="rounded-md bg-surface-2 py-1.5">
                  <span className="block text-text-tertiary">{WEEKDAYS[i]}</span>
                  <span className="font-mono-nums text-text-primary">{n}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Card>
  );
}
