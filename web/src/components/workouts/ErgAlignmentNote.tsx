import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { clearErgAlignment, setErgAlignment, suggestErgAlignment } from "../../lib/api";
import type { ErgAlignment, ErgAlignmentSuggestion } from "../../lib/types";
import { Button } from "../ui/Button";
import { Input } from "../ui/Field";

function signed(seconds: number): string {
  const sign = seconds < 0 ? "−" : "";
  const a = Math.abs(seconds);
  return `${sign}${Math.floor(a / 60)}:${String(a % 60).padStart(2, "0")}`;
}

function describe(offset: number): string {
  return offset >= 0
    ? `the erg recording starts ${signed(offset)} into the heart-rate recording`
    : `the erg recording starts ${signed(-offset)} before the heart-rate recording`;
}

/** Session 36 follow-up: the line under the erg chart when its strokes and the heart-rate chart come from two devices. Nothing is
 * linked until the athlete confirms an offset — the server may propose one from the two recordings' heart rate or stroke rate, and
 * the athlete can use it, adjust it or set one by hand. */
export function ErgAlignmentNote({ canonicalId, alignment }: { canonicalId: number; alignment: ErgAlignment }) {
  const qc = useQueryClient();
  const [suggestion, setSuggestion] = useState<ErgAlignmentSuggestion | null>(null);
  const [draft, setDraft] = useState<number | null>(null);
  const refresh = (a: ErgAlignment) => {
    qc.setQueryData(["erg-alignment", canonicalId], a);
    setDraft(null);
    setSuggestion(null);
  };
  const suggest = useMutation({ mutationFn: () => suggestErgAlignment(canonicalId), onSuccess: setSuggestion });
  const save = useMutation({ mutationFn: (offset: number) => setErgAlignment(canonicalId, offset), onSuccess: refresh });
  const clear = useMutation({ mutationFn: () => clearErgAlignment(canonicalId), onSuccess: refresh });

  if (alignment.state === "confirmed" && draft == null) {
    return (
      <div className="mt-2 flex flex-col gap-2 text-xs text-text-tertiary" data-testid="erg-alignment">
        <p>
          Linked to the heart-rate chart at the offset you set: {describe(alignment.offset_s ?? 0)}. The two devices' clocks aren't compared — this
          offset is yours.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setDraft(alignment.offset_s ?? 0)}>
            Change offset
          </Button>
          <Button size="sm" variant="ghost" loading={clear.isPending} onClick={() => clear.mutate()}>
            Unlink
          </Button>
        </div>
      </div>
    );
  }

  if (!alignment.wall_time_known) {
    return (
      <p className="mt-2 text-xs text-text-tertiary" data-testid="erg-alignment">
        Not linked to the heart-rate chart: that chart is from another device, and this erg result doesn't say how long each rest was, so its strokes
        can't be placed in time.
      </p>
    );
  }

  return (
    <div className="mt-2 flex flex-col gap-2 text-xs text-text-tertiary" data-testid="erg-alignment">
      <p>Not linked to the heart-rate chart: that chart is from another device, and the two clocks aren't assumed to agree.</p>
      {suggestion && suggestion.offset_s != null && draft == null && (
        <div className="rounded-md border border-border bg-surface-2 p-3 text-text-secondary" data-testid="erg-alignment-suggestion">
          <p>
            The two recordings' {suggestion.signal === "stroke_rate" ? "stroke rates" : "heart rates"} line up best when {describe(suggestion.offset_s)}{" "}
            (correlation {suggestion.r?.toFixed(2)} over {Math.round((suggestion.overlap_s ?? 0) / 60)} min). A proposal, not a measurement — check it on
            the charts.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate(suggestion.offset_s as number)}>
              Use this offset
            </Button>
            <Button size="sm" onClick={() => setDraft(suggestion.offset_s)}>
              Adjust
            </Button>
          </div>
        </div>
      )}
      {suggestion && suggestion.offset_s == null && draft == null && <p className="text-text-secondary">{suggestion.reason ?? "No offset fits clearly."} You can set one by hand.</p>}
      {draft != null ? (
        <div className="flex flex-col gap-2 rounded-md border border-border p-3" data-testid="erg-alignment-editor">
          <label className="flex flex-wrap items-center gap-2 text-text-secondary">
            Offset (seconds; negative if the erg started first)
            <Input
              type="number"
              inputMode="numeric"
              step={1}
              className="w-28"
              value={draft}
              onChange={(e) => setDraft(Math.trunc(Number(e.target.value) || 0))}
              data-testid="erg-offset-input"
            />
          </label>
          <div className="flex flex-wrap gap-1.5">
            {[-5, -1, 1, 5].map((d) => (
              <Button key={d} size="sm" variant="ghost" onClick={() => setDraft((v) => (v ?? 0) + d)}>
                {d > 0 ? `+${d}` : d} s
              </Button>
            ))}
          </div>
          <p>{describe(draft)}.</p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate(draft)}>
              Save offset
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
              Cancel
            </Button>
          </div>
          {save.isError && <p className="text-band-red-text">{(save.error as Error).message}</p>}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {!suggestion && (
            <Button size="sm" loading={suggest.isPending} onClick={() => suggest.mutate()}>
              Find the offset
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setDraft(suggestion?.offset_s ?? 0)}>
            Set it by hand
          </Button>
        </div>
      )}
    </div>
  );
}
