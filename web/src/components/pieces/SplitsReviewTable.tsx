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
}: {
  splits: PieceSplitRow[];
  validation: PieceValidation | null;
  onChange?: (splits: PieceSplitRow[]) => void;
  readOnly?: boolean;
}) {
  const tableIssues = (validation?.issues ?? []).filter((i) => i.split_index === null);
  const issuesByRow = new Map<number, string[]>();
  for (const issue of validation?.issues ?? []) {
    if (issue.split_index == null) continue;
    issuesByRow.set(issue.split_index, [...(issuesByRow.get(issue.split_index) ?? []), issue.message]);
  }

  const update = (i: number, patch: Partial<PieceSplitRow>) => {
    if (!onChange) return;
    onChange(splits.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  };
  const remove = (i: number) => {
    if (!onChange) return;
    onChange(splits.filter((_, idx) => idx !== i).map((row, idx) => ({ ...row, split_index: idx + 1 })));
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
        <table className="w-full min-w-[480px] text-sm">
          <thead>
            <tr className="text-left text-xs text-text-tertiary">
              <th className="py-1 font-normal">#</th>
              <th className="py-1 font-normal">Distance (m)</th>
              <th className="py-1 font-normal">Split</th>
              <th className="py-1 font-normal">Rate</th>
              <th className="py-1 font-normal">Watts</th>
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
                        className="min-h-9 w-20 rounded-md border border-border bg-bg px-1.5 text-base font-mono-nums text-text-primary"
                      />
                    )}
                  </td>
                  <td className="py-1">
                    {readOnly ? (
                      <span className="font-mono-nums text-text-primary">{row.split_s != null ? row.split_s.toFixed(1) + "s" : "—"}</span>
                    ) : (
                      <TimeInput valueS={row.split_s} onChange={(s) => update(i, { split_s: s })} ariaLabel={`Split ${row.split_index} time`} className="min-h-9 w-24 rounded-md border border-border bg-bg px-1.5 text-base font-mono-nums text-text-primary" />
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
                        className="min-h-9 w-16 rounded-md border border-border bg-bg px-1.5 text-base font-mono-nums text-text-primary"
                      />
                    )}
                  </td>
                  <td className="py-1">
                    {readOnly ? (
                      <span className="font-mono-nums text-text-primary">{row.watts ?? "—"}</span>
                    ) : (
                      <input
                        type="number"
                        inputMode="numeric"
                        value={row.watts ?? ""}
                        onChange={(e) => update(i, { watts: e.target.value === "" ? null : Number(e.target.value) })}
                        className="min-h-9 w-16 rounded-md border border-border bg-bg px-1.5 text-base font-mono-nums text-text-primary"
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
                        className="min-h-9 w-16 rounded-md border border-border bg-bg px-1.5 text-base font-mono-nums text-text-primary"
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
      {Array.from(issuesByRow.entries()).map(([idx, messages]) => (
        <p key={idx} className="text-xs text-band-red-text">
          Split {idx}: {messages.join(" ")}
        </p>
      ))}
    </div>
  );
}
