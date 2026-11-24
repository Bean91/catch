import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { BackLink } from "../components/ui/PageHeader";
import { fetchDuplicates, markNotDuplicate, mergeActivities, previewDuplicateMerge } from "../lib/api";
import { formatDuration, formatShortDate } from "../lib/format";
import { formatInstantTime } from "../lib/localTime";
import type { DuplicateMergePreview, DuplicatePair } from "../lib/types";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { buttonClass } from "../components/ui/Button";
import { DataTable } from "../components/ui/DataList";

const SOURCE_LABEL: Record<string, string> = { garmin: "Garmin", concept2: "Concept2", whoop: "Whoop", peloton: "Peloton", catch_strength: "Catch gym log", apple_health: "Apple Health", health_connect: "Health Connect", manual: "Entered by you" };
const label = (s: string) => SOURCE_LABEL[s] ?? s;

const FIELDS: { key: keyof DuplicateMergePreview["a"] & string; text: string; fmt: (v: number | string | null) => string }[] = [
  { key: "start", text: "Started", fmt: (v) => (typeof v === "string" ? formatInstantTime(v) : "—") },
  { key: "duration", text: "Time", fmt: (v) => (typeof v === "number" ? formatDuration(v) : "—") },
  { key: "distance", text: "Distance", fmt: (v) => (typeof v === "number" ? `${Math.round(v).toLocaleString()} m` : "—") },
  { key: "avg_hr", text: "Avg HR", fmt: (v) => (typeof v === "number" ? `${Math.round(v)} bpm` : "—") },
  { key: "max_hr", text: "Max HR", fmt: (v) => (typeof v === "number" ? `${Math.round(v)} bpm` : "—") },
  { key: "avg_power", text: "Power", fmt: (v) => (typeof v === "number" ? `${Math.round(v)} W` : "—") },
  { key: "avg_cadence", text: "Rate", fmt: (v) => (typeof v === "number" ? `${Math.round(v)}` : "—") },
  { key: "calories", text: "Calories", fmt: (v) => (typeof v === "number" ? `${Math.round(v)}` : "—") },
];

const MOVE_TEXT: Record<string, string> = { pieces: "pieces", planned: "plan link", notes: "technique notes", feedback: "feedback entries", publications: "leaderboard publications", event_results: "event results" };

/** The comparison a merge decision needs: both recordings side by side, the merged figure for each field and which recording it
 * comes from, the overlap, and what moves. Nothing is merged until "Merge these". */
function Review({ pair, onDone }: { pair: DuplicatePair; onDone: () => void }) {
  const q = useQuery({ queryKey: ["merge-preview", pair.a.activity_id, pair.b.activity_id], queryFn: () => previewDuplicateMerge(pair.a.activity_id, pair.b.activity_id) });
  const merge = useMutation({ mutationFn: () => mergeActivities(pair.a.activity_id, pair.b.activity_id), onSuccess: onDone });
  if (q.isError) return <ErrorState message="Couldn't build the comparison." onRetry={() => q.refetch()} />;
  if (!q.data) return <CardSkeleton lines={4} />;
  const p = q.data;
  const fromText = (f: string) => {
    const src = p.merged?.from[f];
    if (!src) return "";
    return src.startsWith(`${p.a.source}:`) ? label(p.a.source) : src.startsWith(`${p.b.source}:`) ? label(p.b.source) : src.split(":")[0];
  };
  return (
    <div className="mt-3 flex flex-col gap-3 border-t border-border pt-3" data-testid="merge-review">
      <DataTable label="Compare the two recordings" minWidth="440px">
        <thead>
          <tr>
            <th />
            <th>{label(p.a.source)}</th>
            <th>{label(p.b.source)}</th>
            <th>If merged</th>
          </tr>
        </thead>
        <tbody>
          {FIELDS.map((f) => (
            <tr key={f.key}>
              <td className="text-text-secondary">{f.text}</td>
              <td className="font-mono-nums">{f.fmt(p.a[f.key] as number | string | null)}</td>
              <td className="font-mono-nums">{f.fmt(p.b[f.key] as number | string | null)}</td>
              <td className="font-mono-nums">
                {p.merged ? f.fmt(p.merged.values[f.key] ?? null) : "—"}
                {p.merged && fromText(f.key) && <span className="block text-[11px] font-sans text-text-tertiary">from {fromText(f.key)}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>
      <p className="text-sm text-text-secondary">
        {p.overlap_s != null ? `They overlap for ${formatDuration(p.overlap_s)}. ` : ""}
        Why they were flagged: {p.reasons.length ? p.reasons.join(", ") : "similar time and sport"}.
      </p>
      {p.merged && (
        <p className="text-xs text-text-tertiary">
          Both recordings are kept inside one workout, and either can be split off again from the workout's page. Each figure comes from the recording that measures it best
          (the order is in Settings).
          {Object.keys(p.merged.moves).length > 0 && ` Moves with it: ${Object.entries(p.merged.moves).map(([k, n]) => `${n} ${MOVE_TEXT[k] ?? k}`).join(", ")}.`}
        </p>
      )}
      {p.blocked_reason && (
        <p role="alert" className="text-sm text-text-secondary">
          {p.blocked_reason}
        </p>
      )}
      {merge.isError && (
        <p role="alert" className="text-sm text-text-secondary">
          {(merge.error as Error).message}
        </p>
      )}
      {p.merged && !p.blocked_reason && (
        <button type="button" disabled={merge.isPending} onClick={() => merge.mutate()} className={buttonClass("primary", "md", "self-start")} data-testid="confirm-merge">
          {merge.isPending ? "Merging…" : "Merge these"}
        </button>
      )}
    </div>
  );
}

function Side({ side }: { side: DuplicatePair["a"] }) {
  return (
    <div className="min-w-0 flex-1 rounded-md border border-border bg-surface-2 p-3">
      <div className="text-sm font-medium text-text-primary">{label(side.source)}</div>
      <div className="text-xs text-text-tertiary">
        {side.start ? `${formatShortDate(side.start)} · ${formatInstantTime(side.start)}` : "—"}
      </div>
      <div className="font-mono-nums text-xs text-text-secondary">{formatDuration(side.duration)}</div>
    </div>
  );
}

export function DuplicatesPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["duplicates"], queryFn: fetchDuplicates });
  const [open, setOpen] = useState<string | null>(null);

  const invalidate = () => {
    setOpen(null);
    queryClient.invalidateQueries({ queryKey: ["duplicates"] });
    queryClient.invalidateQueries({ queryKey: ["workouts"] });
  };
  const notDuplicate = useMutation({
    mutationFn: ({ a, b }: { a: number; b: number }) => markNotDuplicate(a, b),
    onSuccess: invalidate,
  });

  return (
    <div className="flex flex-col gap-4">
      <div>
        <BackLink to="/workouts">Workouts</BackLink>
        <h1 className="mt-1 text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]">Possible duplicates</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Recordings that look like the same session (same sport, overlapping time, similar length) but weren't close enough to merge on their own. Compare them, then merge or
          keep them apart.
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

      {data?.map((pair) => {
        const key = `${pair.a.activity_id}-${pair.b.activity_id}`;
        return (
          <Card material="solid" key={key} testId="duplicate-pair">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <Side side={pair.a} />
              <span className="self-center text-xs text-text-tertiary">vs</span>
              <Side side={pair.b} />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3">
              <span className="text-xs text-text-tertiary">{pair.score >= 0.75 ? "Strong match" : pair.score >= 0.5 ? "Likely match" : "Possible match"}</span>
              {pair.hard_block && <span className="text-xs text-text-tertiary">indoor/outdoor mismatch — won't auto-merge</span>}
              <button type="button" onClick={() => setOpen(open === key ? null : key)} className={buttonClass(open === key ? "subtle" : "primary", "sm")} aria-expanded={open === key}>
                {open === key ? "Hide comparison" : "Compare and merge…"}
              </button>
              <button
                type="button"
                disabled={notDuplicate.isPending}
                onClick={() => notDuplicate.mutate({ a: pair.a.activity_id, b: pair.b.activity_id })}
                className={buttonClass("secondary", "sm")}
              >
                Not a duplicate
              </button>
            </div>
            {open === key && <Review pair={pair} onDone={invalidate} />}
          </Card>
        );
      })}
    </div>
  );
}
