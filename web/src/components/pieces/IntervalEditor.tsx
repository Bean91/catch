import { useState } from "react";
import { fetchIntervalTemplate } from "../../lib/api";
import type { IntervalTarget, IntervalValidationIssue, PieceInterval } from "../../lib/types";
import { TimeInput } from "./TimeInput";

const inputCls = "min-h-9 w-full rounded-md border border-border bg-bg px-2 text-base font-mono-nums text-text-primary";
const btnCls = "min-h-9 min-w-9 rounded-md border border-border px-2 text-xs font-medium text-text-primary disabled:opacity-40";

export function blankInterval(target: IntervalTarget = "distance"): PieceInterval {
  return {
    target_type: target,
    work_distance_m: target === "distance" ? 500 : null,
    work_duration_s: target === "time" ? 60 : null,
    rest_duration_s: null,
    avg_split_s: null,
    avg_watts: null,
    avg_rate: null,
    avg_hr: null,
    max_hr: null,
    calories: null,
    notes: null,
  };
}

function Num({ label, value, onChange, step }: { label: string; value: number | null; onChange: (v: number | null) => void; step?: number }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-text-tertiary">{label}</span>
      <input type="number" inputMode="decimal" min={0} step={step} aria-label={label} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} className={inputCls} />
    </label>
  );
}

/** Stacked rows rather than a wide table: a 390px screen can't fit target + result + rest +
 * five optional metrics per row without sideways scrolling (DESIGN.md "Intervals within a
 * piece"). Only the prescription and result are always visible; the rest sits under "More",
 * so entering 4 x 500m stays a handful of taps. No totals or averages are computed here —
 * the server returns them with every save. */
export function IntervalEditor({
  rows,
  onChange,
  canonicalId,
  issues = [],
}: {
  rows: PieceInterval[];
  onChange: (rows: PieceInterval[]) => void;
  canonicalId: number;
  issues?: IntervalValidationIssue[];
}) {
  const [count, setCount] = useState(4);
  const [mode, setMode] = useState<IntervalTarget>("distance");
  const [distanceM, setDistanceM] = useState<number | null>(500);
  const [durationS, setDurationS] = useState<number | null>(60);
  const [restS, setRestS] = useState<number | null>(60);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [busy, setBusy] = useState(false);

  const target = mode === "distance" ? distanceM : durationS;

  const generate = async () => {
    if (!target || count < 1) return;
    setBusy(true);
    try {
      const made = await fetchIntervalTemplate(canonicalId, {
        count,
        ...(mode === "distance" ? { distance_m: target } : { duration_s: target }),
        ...(restS ? { rest_s: restS } : {}),
      });
      const base = rows.map((r, i) => (i === rows.length - 1 && restS && !r.rest_duration_s ? { ...r, rest_duration_s: restS } : r));
      onChange([...base, ...made]);
    } finally {
      setBusy(false);
    }
  };

  const patch = (i: number, p: Partial<PieceInterval>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= rows.length) return;
    const next = [...rows];
    [next[i], next[j]] = [next[j], next[i]];
    setOpen({});
    onChange(next);
  };
  const remove = (i: number) => {
    setOpen({});
    onChange(rows.filter((_, j) => j !== i));
  };

  return (
    <div className="flex flex-col gap-3" data-testid="interval-editor">
      <div className="rounded-md border border-border p-3">
        <div className="text-xs font-medium text-text-secondary">Quick add</div>
        <div className="mt-2 grid grid-cols-[4rem_auto_1fr] items-end gap-2">
          <Num label="Reps" value={count} onChange={(v) => setCount(Math.max(1, Math.min(100, v ?? 1)))} />
          <div className="flex gap-1" role="group" aria-label="Work type">
            {(["distance", "time"] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={mode === m}
                onClick={() => setMode(m)}
                className={`min-h-9 rounded-md border px-2.5 text-xs font-medium ${mode === m ? "border-accent bg-accent/10 text-text-primary" : "border-border text-text-tertiary"}`}
              >
                {m === "distance" ? "m" : "time"}
              </button>
            ))}
          </div>
          {mode === "distance" ? (
            <Num label="Distance (m)" value={distanceM} onChange={setDistanceM} />
          ) : (
            <label className="flex flex-col gap-1">
              <span className="text-xs text-text-tertiary">Work time</span>
              <TimeInput valueS={durationS} onChange={setDurationS} ariaLabel="Work time" />
            </label>
          )}
        </div>
        <div className="mt-2 flex items-end gap-2">
          <label className="flex flex-1 flex-col gap-1">
            <span className="text-xs text-text-tertiary">Rest between</span>
            <TimeInput valueS={restS} onChange={setRestS} ariaLabel="Rest between" />
          </label>
          <button type="button" disabled={busy || !target} onClick={generate} className="min-h-9 rounded-md border border-accent bg-accent px-4 text-xs font-medium text-accent-contrast disabled:opacity-50">
            Add {count} ×
          </button>
        </div>
      </div>

      {rows.length === 0 && <p className="text-sm text-text-tertiary">No intervals yet — use Quick add, or add a custom one.</p>}

      <ol className="flex flex-col gap-2">
        {rows.map((r, i) => {
          const rowIssues = issues.filter((x) => x.index === i);
          const isDist = r.target_type === "distance";
          return (
            <li key={r.id ?? `new-${i}`} className={`rounded-md border p-2.5 ${rowIssues.length ? "border-band-red/50 bg-band-red/10" : "border-border"}`} data-testid="interval-row">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono-nums text-xs font-medium text-text-secondary">#{i + 1}</span>
                <div className="flex gap-1">
                  <button type="button" aria-label={`Move interval ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)} className={btnCls}>
                    ↑
                  </button>
                  <button type="button" aria-label={`Move interval ${i + 1} down`} disabled={i === rows.length - 1} onClick={() => move(i, 1)} className={btnCls}>
                    ↓
                  </button>
                  <button type="button" aria-label={`Delete interval ${i + 1}`} onClick={() => remove(i)} className={`${btnCls} hover:border-band-red/40 hover:text-band-red-text`}>
                    ✕
                  </button>
                </div>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-1">
                  <div className="flex gap-1" role="group" aria-label={`Interval ${i + 1} work type`}>
                    {(["distance", "time"] as const).map((m) => (
                      <button
                        key={m}
                        type="button"
                        aria-pressed={r.target_type === m}
                        onClick={() => patch(i, { target_type: m, ...(m === "distance" && !r.work_distance_m ? { work_distance_m: 500 } : {}), ...(m === "time" && !r.work_duration_s ? { work_duration_s: 60 } : {}) })}
                        className={`min-h-9 flex-1 rounded-md border text-xs font-medium ${r.target_type === m ? "border-accent bg-accent/10 text-text-primary" : "border-border text-text-tertiary"}`}
                      >
                        {m === "distance" ? "Distance" : "Time"}
                      </button>
                    ))}
                  </div>
                  {isDist ? (
                    <Num label={`Interval ${i + 1} distance (m)`} value={r.work_distance_m} onChange={(v) => patch(i, { work_distance_m: v })} />
                  ) : (
                    <TimeInput valueS={r.work_duration_s} onChange={(v) => patch(i, { work_duration_s: v })} ariaLabel={`Interval ${i + 1} work time`} />
                  )}
                </div>
                <div className="flex flex-col justify-end gap-1">
                  <span className="text-xs text-text-tertiary">{isDist ? "Result time" : "Result distance (m)"}</span>
                  {isDist ? (
                    <TimeInput valueS={r.work_duration_s} onChange={(v) => patch(i, { work_duration_s: v })} ariaLabel={`Interval ${i + 1} result time`} />
                  ) : (
                    <input type="number" inputMode="decimal" min={0} aria-label={`Interval ${i + 1} result distance`} value={r.work_distance_m ?? ""} onChange={(e) => patch(i, { work_distance_m: e.target.value === "" ? null : Number(e.target.value) })} className={inputCls} />
                  )}
                </div>
              </div>
              <div className="mt-2 flex items-end gap-2">
                <label className="flex flex-1 flex-col gap-1">
                  <span className="text-xs text-text-tertiary">Rest after</span>
                  <TimeInput valueS={r.rest_duration_s} onChange={(v) => patch(i, { rest_duration_s: v })} ariaLabel={`Interval ${i + 1} rest`} />
                </label>
                <button type="button" aria-expanded={!!open[i]} onClick={() => setOpen({ ...open, [i]: !open[i] })} className={btnCls}>
                  {open[i] ? "Less" : "More"}
                </button>
              </div>
              {open[i] && (
                <div className="mt-2 grid grid-cols-3 gap-2">
                  <Num label="Watts" value={r.avg_watts} onChange={(v) => patch(i, { avg_watts: v })} />
                  <Num label="Rate (spm)" value={r.avg_rate} onChange={(v) => patch(i, { avg_rate: v })} />
                  <Num label="Calories" value={r.calories} onChange={(v) => patch(i, { calories: v })} />
                  <Num label="Avg HR" value={r.avg_hr} onChange={(v) => patch(i, { avg_hr: v })} />
                  <Num label="Max HR" value={r.max_hr} onChange={(v) => patch(i, { max_hr: v })} />
                  <label className="col-span-3 flex flex-col gap-1">
                    <span className="text-xs text-text-tertiary">Notes</span>
                    <input type="text" aria-label={`Interval ${i + 1} notes`} value={r.notes ?? ""} onChange={(e) => patch(i, { notes: e.target.value || null })} className="min-h-9 w-full rounded-md border border-border bg-bg px-2 text-base text-text-primary" />
                  </label>
                </div>
              )}
              {rowIssues.map((x, k) => (
                <p key={k} className="mt-1.5 text-xs text-band-red-text">
                  {x.message}
                </p>
              ))}
            </li>
          );
        })}
      </ol>

      <button type="button" onClick={() => onChange([...rows, blankInterval(rows[rows.length - 1]?.target_type ?? "distance")])} className="min-h-9 self-start rounded-md border border-border px-3 text-xs font-medium text-text-primary">
        + Add custom interval
      </button>
      {issues.filter((x) => x.index === null).map((x, k) => (
        <p key={k} className="text-xs text-band-red-text">
          {x.message}
        </p>
      ))}
    </div>
  );
}
