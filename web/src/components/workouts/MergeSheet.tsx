import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError, combineWorkouts, previewMerge } from "../../lib/api";
import { categoryLabel, formatDistance, formatDuration, formatNumber, formatSplit } from "../../lib/format";
import { formatInstantDate, formatInstantTime } from "../../lib/localTime";
import type { MergePreviewItem } from "../../lib/types";
import { SheetContent } from "../ui/Sheet";
import { buttonClass } from "../ui/Button";

const SOURCE_LABEL: Record<string, string> = {
  garmin: "Garmin",
  concept2: "Concept2",
  whoop: "Whoop",
  peloton: "Peloton",
  catch_strength: "Catch",
  apple_health: "Apple Health",
  health_connect: "Health Connect",
};

/** Session 33: merge the selected workouts into one. Shows each workout as it is now, why they can't be merged (in words — the
 * confirm button is absent, not dimmed), and the merged result exactly as the server's resolver computes it, before anything is
 * written. Every figure comes from the server; the browser adds nothing up itself. Bottom sheet at z-30 over the nav, centred from
 * `sm:`, no autofocus — the existing sheet pattern. */
export function MergeSheet({ open, ids, onClose, onMerged }: { open: boolean; ids: number[]; onClose: () => void; onMerged: () => void }) {
  const navigate = useNavigate();
  const key = [...ids].sort((a, b) => a - b);
  const preview = useQuery({ queryKey: ["merge-preview", ...key], queryFn: () => previewMerge(key), enabled: open && ids.length >= 2, staleTime: 0, retry: false });
  const merge = useMutation({
    mutationFn: () => combineWorkouts(key, preview.data!.preview_hash),
    onSuccess: (detail) => {
      onMerged();
      navigate(`/workouts/${detail.id}`);
    },
    onError: () => preview.refetch(),
  });
  const p = preview.data;
  const r = p?.result;

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent width="lg" onOpenAutoFocus={(e) => e.preventDefault()} data-testid="merge-sheet">
          <Dialog.Title className="text-lg font-semibold text-text-primary">Merge {ids.length} workouts into one</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            For one session that was recorded in parts — a watch that stopped and restarted, an erg reset between pieces. Every recording is kept; times and
            distances are added, and a stretch recorded twice is counted once. You can undo it from the merged workout.
          </Dialog.Description>

          {preview.isLoading && <p className="mt-4 text-sm text-text-tertiary">Checking these workouts…</p>}
          {preview.isError && (
            <p role="alert" className="mt-4 text-sm text-band-red-text">
              {preview.error instanceof ApiError ? preview.error.message : "Couldn't check these workouts."}
            </p>
          )}

          {p && (
            <div className="mt-4 flex flex-col gap-3">
              <ol className="flex flex-col gap-2" aria-label="Selected workouts, in time order">
                {p.items.map((item) => (
                  <ItemRow key={item.id} item={item} keep={item.id === p.keep_id && p.compatible} />
                ))}
              </ol>

              {p.overlaps.length > 0 && p.compatible && (
                <p className="rounded-md bg-surface-2 p-2 text-xs text-text-secondary" data-testid="merge-overlap">
                  {p.overlaps.map((o) => `${formatDuration(o.seconds)} recorded twice`).join("; ")} — counted once.
                </p>
              )}

              {!p.compatible && (
                <div role="alert" className="rounded-md border border-band-red/40 bg-band-red/10 p-3 text-sm text-text-primary" data-testid="merge-reasons">
                  <p className="font-medium">These can't be merged:</p>
                  <ul className="mt-1 list-disc pl-5 text-text-secondary">
                    {p.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
              )}

              {r && (
                <section className="rounded-md border border-accent/40 p-3" aria-label="Merged workout" data-testid="merge-result">
                  <h3 className="text-sm font-semibold text-text-primary">Merged workout</h3>
                  <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3">
                    <Fact label="Starts">{r.start ? `${formatInstantDate(r.start, r.local_tz)}, ${formatInstantTime(r.start, r.local_tz)}` : "—"}</Fact>
                    <Fact label="Moving time">{formatDuration(r.duration)}</Fact>
                    <Fact label="Distance">
                      {formatDistance(r.distance)}
                      {r.distance_partial && <span className="block text-xs text-text-tertiary">some parts had no distance</span>}
                    </Fact>
                    <Fact label="Avg HR">{r.avg_hr != null ? `${formatNumber(r.avg_hr)} bpm` : "—"}</Fact>
                    <Fact label="Max HR">{r.max_hr != null ? `${formatNumber(r.max_hr)} bpm` : "—"}</Fact>
                    {r.avg_split_500m != null && <Fact label="Avg split">{formatSplit(r.avg_split_500m)} /500m</Fact>}
                    {r.avg_power != null && <Fact label="Avg power">{formatNumber(r.avg_power)} W</Fact>}
                  </dl>
                  <p className="mt-2 text-xs text-text-tertiary">
                    {r.parts.length} part{r.parts.length === 1 ? "" : "s"}; average heart rate is weighted by each part's time. Strain is worked out once from the
                    combined heart-rate trace.
                  </p>
                </section>
              )}

              {merge.isError && (
                <p role="alert" className="text-sm text-band-red-text">
                  {merge.error instanceof ApiError ? merge.error.message : "Couldn't merge — nothing was changed."}
                </p>
              )}

              <div className="flex gap-2">
                <button type="button" onClick={onClose} className={buttonClass("secondary", "md", "flex-1")}>
                  {p.compatible ? "Cancel" : "Close"}
                </button>
                {p.compatible && (
                  <button
                    type="button"
                    disabled={merge.isPending}
                    onClick={() => merge.mutate()}
                    className={buttonClass("primary", "md", "flex-1")}
                  >
                    {merge.isPending ? "Merging…" : "Merge these workouts"}
                  </button>
                )}
              </div>
            </div>
          )}
        </SheetContent>
    </Dialog.Root>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-text-tertiary">{label}</dt>
      <dd className="font-mono-nums text-text-primary">{children}</dd>
    </div>
  );
}

function ItemRow({ item, keep }: { item: MergePreviewItem; keep: boolean }) {
  const sources = [...new Set(item.sources.map((s) => SOURCE_LABEL[s.source] ?? s.source))];
  return (
    <li className="rounded-md border border-border p-3 text-sm" data-testid={`merge-item-${item.id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium text-text-primary">{item.title ?? categoryLabel(item.category)}</span>
        <span className="text-xs text-text-tertiary">
          {item.start ? `${formatInstantDate(item.start, item.local_tz)}, ${formatInstantTime(item.start, item.local_tz)}` : "no start time"}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono-nums text-xs text-text-secondary">
        <span>{categoryLabel(item.category)}</span>
        <span>{formatDuration(item.duration)}</span>
        <span>{formatDistance(item.distance)}</span>
        {item.avg_hr != null && <span>{formatNumber(item.avg_hr)} bpm avg</span>}
        {item.avg_split_500m != null && <span>{formatSplit(item.avg_split_500m)} /500m</span>}
        {item.avg_power != null && <span>{formatNumber(item.avg_power)} W</span>}
      </div>
      <div className="mt-1 text-xs text-text-tertiary">
        From {sources.join(" + ")}
        {keep && " · kept as the merged workout (it's the earliest)"}
      </div>
    </li>
  );
}
