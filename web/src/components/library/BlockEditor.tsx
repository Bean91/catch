import { formatClock, parseClock } from "../../lib/duration";
import type { TemplateBlock, ZoneLabel } from "../../lib/types";

const ZONE_CHOICES: ZoneLabel[] = ["UT2", "UT1", "AT", "TR", "AN"];
const inputCls = "min-h-11 w-full min-w-0 rounded-md border border-border bg-bg px-3 text-sm text-text-primary";

// One editor row holds the raw text the athlete typed; `rowToBlock` turns it into the API shape
// (text -> seconds/metres only — no totals are computed in the browser).
export interface BlockRow {
  reps: string;
  kind: "time" | "distance";
  work: string;
  rest: string;
  zone: ZoneLabel | "";
  rateMin: string;
  rateMax: string;
  split: string;
  watts: string;
  note: string;
}

export const blankRow = (): BlockRow => ({ reps: "4", kind: "distance", work: "500", rest: "1:00", zone: "", rateMin: "", rateMax: "", split: "", watts: "", note: "" });

export function blockToRow(b: TemplateBlock): BlockRow {
  return {
    reps: String(b.reps),
    kind: b.work_m != null ? "distance" : "time",
    work: b.work_m != null ? String(b.work_m) : formatClock(b.work_s, true),
    rest: b.rest_s ? formatClock(b.rest_s, true) : "",
    zone: b.zone ?? "",
    rateMin: b.rate_min != null ? String(b.rate_min) : "",
    rateMax: b.rate_max != null ? String(b.rate_max) : "",
    split: b.split_s ? formatClock(b.split_s, true) : "",
    watts: b.watts ? String(b.watts) : "",
    note: b.note ?? "",
  };
}

export function rowToBlock(r: BlockRow, index: number): { block: TemplateBlock | null; error: string | null } {
  const label = `Block ${index + 1}`;
  const reps = Number(r.reps);
  if (!Number.isInteger(reps) || reps < 1) return { block: null, error: `${label}: reps must be a whole number.` };
  const work = r.kind === "distance" ? Number(r.work) : parseClock(r.work);
  if (work == null || !Number.isFinite(work) || work <= 0) return { block: null, error: `${label}: ${r.kind === "distance" ? "enter the distance in metres" : "enter the time like 4:00"}.` };
  const rest = r.rest.trim() ? parseClock(r.rest) : null;
  if (r.rest.trim() && rest == null) return { block: null, error: `${label}: enter rest like 1:00.` };
  const split = r.split.trim() ? parseClock(r.split) : null;
  if (r.split.trim() && split == null) return { block: null, error: `${label}: enter the split like 1:50.5.` };
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const rateMin = num(r.rateMin), rateMax = num(r.rateMax), watts = num(r.watts);
  if ([rateMin, rateMax, watts].some((n) => n != null && !Number.isFinite(n))) return { block: null, error: `${label}: rate and watts must be numbers.` };
  return {
    block: {
      reps,
      ...(r.kind === "distance" ? { work_m: work } : { work_s: work }),
      rest_s: rest, zone: r.zone || null, rate_min: rateMin, rate_max: rateMax ?? rateMin, split_s: split, watts, note: r.note.trim() || null,
    },
    error: null,
  };
}

export function BlockEditor({ rows, onChange, ladder }: { rows: BlockRow[]; onChange: (rows: BlockRow[]) => void; ladder?: boolean }) {
  const set = (i: number, patch: Partial<BlockRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const next = [...rows];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  return (
    <div className="flex flex-col gap-3" data-testid="block-editor">
      {rows.map((r, i) => (
        <fieldset key={i} className="flex flex-col gap-2 rounded-md border border-border p-3" data-testid="block-row">
          <legend className="px-1 text-xs text-text-tertiary">{ladder ? `Step ${i + 1}` : `Block ${i + 1}`}</legend>
          <div className="grid grid-cols-[4.5rem_1fr_1fr] gap-2">
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Reps
              <input value={r.reps} onChange={(e) => set(i, { reps: e.target.value.replace(/\D/g, "") })} inputMode="numeric" className={inputCls} aria-label={`Block ${i + 1} reps`} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Work by
              <select value={r.kind} onChange={(e) => set(i, { kind: e.target.value as BlockRow["kind"], work: "" })} className={inputCls} aria-label={`Block ${i + 1} work type`}>
                <option value="distance">Distance (m)</option>
                <option value="time">Time (m:ss)</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              {r.kind === "distance" ? "Metres" : "Time"}
              <input value={r.work} onChange={(e) => set(i, { work: e.target.value })} inputMode={r.kind === "distance" ? "numeric" : "text"} placeholder={r.kind === "distance" ? "500" : "4:00"} className={inputCls} aria-label={`Block ${i + 1} work`} />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Rest after each rep
              <input value={r.rest} onChange={(e) => set(i, { rest: e.target.value })} placeholder="1:00" className={inputCls} aria-label={`Block ${i + 1} rest`} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Zone
              <select value={r.zone} onChange={(e) => set(i, { zone: e.target.value as ZoneLabel | "" })} className={inputCls} aria-label={`Block ${i + 1} zone`}>
                <option value="">None</option>
                {ZONE_CHOICES.map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="grid grid-cols-4 gap-2">
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Rate from
              <input value={r.rateMin} onChange={(e) => set(i, { rateMin: e.target.value })} inputMode="decimal" placeholder="spm" className={inputCls} aria-label={`Block ${i + 1} rate from`} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              to
              <input value={r.rateMax} onChange={(e) => set(i, { rateMax: e.target.value })} inputMode="decimal" placeholder="spm" className={inputCls} aria-label={`Block ${i + 1} rate to`} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Split /500m
              <input value={r.split} onChange={(e) => set(i, { split: e.target.value, watts: e.target.value ? "" : r.watts })} placeholder="1:50" className={inputCls} aria-label={`Block ${i + 1} split`} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              or Watts
              <input value={r.watts} onChange={(e) => set(i, { watts: e.target.value, split: e.target.value ? "" : r.split })} inputMode="numeric" className={inputCls} aria-label={`Block ${i + 1} watts`} />
            </label>
          </div>
          <input value={r.note} onChange={(e) => set(i, { note: e.target.value })} placeholder="Note (optional)" aria-label={`Block ${i + 1} note`} className={inputCls} />
          <div className="flex gap-2">
            <button type="button" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move block ${i + 1} up`} className="min-h-11 min-w-11 rounded-md border border-border text-text-secondary disabled:opacity-40">
              ↑
            </button>
            <button type="button" onClick={() => move(i, 1)} disabled={i === rows.length - 1} aria-label={`Move block ${i + 1} down`} className="min-h-11 min-w-11 rounded-md border border-border text-text-secondary disabled:opacity-40">
              ↓
            </button>
            <button type="button" onClick={() => onChange(rows.filter((_, j) => j !== i))} aria-label={`Remove block ${i + 1}`} className="ml-auto min-h-11 rounded-md border border-border px-3 text-sm text-text-secondary">
              Remove
            </button>
          </div>
        </fieldset>
      ))}
      <button type="button" data-testid="add-block" onClick={() => onChange([...rows, blankRow()])} className="min-h-11 self-start rounded-md border border-border px-3 text-sm text-text-secondary">
        + Add {ladder ? "step" : "block"}
      </button>
    </div>
  );
}
