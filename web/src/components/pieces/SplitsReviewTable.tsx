import { formatSplit, splitUnitLabel } from "../../lib/format";
import { SPLIT_M, rateUnit, type PieceModality } from "../../lib/pieceSplits";
import type { PieceSplitRow, PieceValidation } from "../../lib/types";
import { TimeInput } from "./TimeInput";

/** The one review table both input methods (photo, typed/pasted) land on — task Part A.2.
 * Highlights exactly the rows a validation check flagged (task Part B.3: "highlight ... so I
 * fix it, instead of silently correcting it"), never auto-corrects a value itself. */
export function SplitsReviewTable({
  splits,
  validation,
  onChange,
  readOnly = false,
  modality = "rowing_erg",
  calculated,
}: {
  splits: PieceSplitRow[];
  validation: PieceValidation | null;
  onChange?: (splits: PieceSplitRow[]) => void;
  readOnly?: boolean;
  modality?: PieceModality;
  /** Session 34: the server preview's rows (POST /api/pieces/preview), aligned with `splits` — each row's watts as Catch calculates them
   *  from the split on a rowing erg. Shown as the watts field's placeholder; the browser never calculates power itself. */
  calculated?: PieceSplitRow[];
}) {
  const unit = splitUnitLabel(SPLIT_M[modality]);
  const tableIssues = (validation?.issues ?? []).filter((i) => i.split_index === null);
  const issuesByRow = new Map<number, string[]>();
  for (const issue of validation?.issues ?? []) {
    if (issue.split_index == null) continue;
    issuesByRow.set(issue.split_index, [...(issuesByRow.get(issue.split_index) ?? []), issue.message]);
  }

  const calcWatts = (i: number): string => {
    const own = splits[i];
    const server = calculated?.[i];
    const w = server?.watts_source === "pace" ? server.watts : own.watts_source === "pace" ? own.watts : null;
    return w != null ? String(Math.round(w)) : "";
  };

  const update = (i: number, patch: Partial<PieceSplitRow>) => {
    if (!onChange) return;
    onChange(splits.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  };
  const remove = (i: number) => {
    if (!onChange) return;
    onChange(splits.filter((_, idx) => idx !== i).map((row, idx) => ({ ...row, split_index: idx + 1 })));
  };
  const add = () => {
    if (!onChange) return;
    onChange([...splits, { split_index: splits.length + 1, distance_m: null, split_s: null, rate: null, watts: null, hr: null }]);
  };

  return (
    <div className="flex flex-col gap-2">
      {tableIssues.length > 0 && (
        <div className="rounded-md border border-band-red/40 bg-band-red/10 p-2 text-xs text-band-red-text">
          {tableIssues.map((i, idx) => (
            <div key={idx}>{i.message}</div>
          ))}
        </div>
      )}
      <div className="overflow-x-auto">
        {/* The 480px floor exists for the edit inputs below — a read-only row of plain text
         * cells (PieceCard's display mode) doesn't need it and forcing it anyway just
         * scrolls the card sideways on a 390px phone for no reason. */}
        <table className={readOnly ? "w-full text-sm" : "w-full min-w-[480px] text-sm"}>
          <thead>
            <tr className="text-left text-xs text-text-tertiary">
              <th className="py-1 font-normal">#</th>
              <th className="py-1 font-normal">Distance (m)</th>
              <th className="py-1 font-normal">Split {unit}</th>
              <th className="py-1 font-normal">{modality === "bike" ? "Cadence" : "Rate"} ({rateUnit(modality)})</th>
              <th className="py-1 font-normal">{modality === "rowing_erg" ? "Watts (from split)" : "Watts"}</th>
              <th className="py-1 font-normal">HR</th>
              {!readOnly && <th className="py-1 font-normal" aria-hidden="true" />}
            </tr>
          </thead>
          <tbody>
            {splits.map((row, i) => {
              const rowIssues = issuesByRow.get(row.split_index) ?? [];
              const flagged = rowIssues.length > 0;
              return (
                <tr key={i} className={flagged ? "bg-band-red/10" : undefined}>
                  <td className="py-1 font-mono-nums text-text-tertiary">{row.split_index}</td>
                  <td className="py-1">
                    {readOnly ? (
                      <span className="font-mono-nums text-text-primary">{row.distance_m ?? "—"}</span>
                    ) : (
                      <input
                        type="number"
                        inputMode="decimal"
                        value={row.distance_m ?? ""}
                        onChange={(e) => update(i, { distance_m: e.target.value === "" ? null : Number(e.target.value) })}
                        className="min-h-9 w-20 rounded-md border border-border bg-surface-2 px-1.5 text-base font-mono-nums text-text-primary"
                      />
                    )}
                  </td>
                  <td className="py-1">
                    {readOnly ? (
                      <span className="font-mono-nums text-text-primary">{formatSplit(row.split_s)}</span>
                    ) : (
                      <TimeInput valueS={row.split_s} onChange={(s) => update(i, { split_s: s })} ariaLabel={`Split ${row.split_index} time`} className="min-h-9 w-24 rounded-md border border-border bg-surface-2 px-1.5 text-base font-mono-nums text-text-primary" />
                    )}
                  </td>
                  <td className="py-1">
                    {readOnly ? (
                      <span className="font-mono-nums text-text-primary">{row.rate ?? "—"}</span>
                    ) : (
                      <input
                        type="number"
                        inputMode="numeric"
                        value={row.rate ?? ""}
                        onChange={(e) => update(i, { rate: e.target.value === "" ? null : Number(e.target.value) })}
                        className="min-h-9 w-16 rounded-md border border-border bg-surface-2 px-1.5 text-base font-mono-nums text-text-primary"
                      />
                    )}
                  </td>
                  <td className="py-1">
                    {readOnly ? (
                      <span className="font-mono-nums text-text-primary" title={row.watts_entered != null ? `You entered ${row.watts_entered} W; Catch uses the split's.` : undefined}>
                        {row.watts != null ? Math.round(row.watts) : "—"}
                      </span>
                    ) : (
                      <input
                        type="number"
                        inputMode="numeric"
                        aria-label={`Split ${row.split_index} watts`}
                        // A value Catch calculated is shown as a hint, not as something typed; typing your own marks it entered (the server checks it).
                        value={row.watts != null && row.watts_source !== "pace" ? row.watts : ""}
                        placeholder={calcWatts(i)}
                        onChange={(e) => update(i, { watts: e.target.value === "" ? null : Number(e.target.value), watts_source: e.target.value === "" ? null : "entered", watts_entered: null })}
                        className="min-h-9 w-16 rounded-md border border-border bg-surface-2 px-1.5 text-base font-mono-nums text-text-primary placeholder:text-text-tertiary"
                      />
                    )}
                  </td>
                  <td className="py-1">
                    {readOnly ? (
                      <span className="font-mono-nums text-text-primary">{row.hr != null ? Math.round(row.hr) : "—"}</span>
                    ) : (
                      <input
                        type="number"
                        inputMode="numeric"
                        value={row.hr ?? ""}
                        onChange={(e) => update(i, { hr: e.target.value === "" ? null : Number(e.target.value), hr_source: "typed" })}
                        className="min-h-9 w-16 rounded-md border border-border bg-surface-2 px-1.5 text-base font-mono-nums text-text-primary"
                      />
                    )}
                  </td>
                  {!readOnly && (
                    <td className="py-1">
                      <button type="button" onClick={() => remove(i)} aria-label={`Remove split ${row.split_index}`} className="flex min-h-9 min-w-9 items-center justify-center text-text-tertiary hover:text-band-red">
                        ×
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!readOnly && splits.length === 0 && <p className="text-xs text-text-tertiary">No splits — the piece is saved from its totals. Add splits if you have them.</p>}
      {!readOnly && (
        <p className="text-xs text-text-tertiary" data-testid="watts-help">
          {modality === "rowing_erg"
            ? "Watts are calculated from each split (Concept2's formula). Type the screen's watts only if you want them checked against the split."
            : "A bike's power is never calculated from pace. Type it from the screen, or leave it blank."}
        </p>
      )}
      {!readOnly && (
        <button type="button" onClick={add} className="min-h-9 self-start rounded-md border border-border px-3 text-xs font-medium text-text-primary hover:border-accent">
          + Add split
        </button>
      )}
      {Array.from(issuesByRow.entries()).map(([idx, messages]) => (
        <p key={idx} className="text-xs text-band-red-text">
          Split {idx}: {messages.join(" ")}
        </p>
      ))}
    </div>
  );
}
