import { formatClock, parseClock } from "../../lib/duration";
import type { TemplateBlock, TemplateSegment, ZoneLabel } from "../../lib/types";
import { buttonClass } from "../ui/Button";
import { controlSkin } from "../ui/Field";

const ZONE_CHOICES: ZoneLabel[] = ["UT2", "UT1", "AT", "TR", "AN"];
const inputCls = `${controlSkin} min-h-11 w-full min-w-0`;

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
  hrMin: string;
  hrMax: string;
  note: string;
}

export const blankRow = (): BlockRow => ({ reps: "4", kind: "distance", work: "500", rest: "1:00", zone: "", rateMin: "", rateMax: "", split: "", watts: "", hrMin: "", hrMax: "", note: "" });

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
    hrMin: b.hr_min != null ? String(b.hr_min) : "",
    hrMax: b.hr_max != null ? String(b.hr_max) : "",
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
  const rateMin = num(r.rateMin), rateMax = num(r.rateMax), watts = num(r.watts), hrMin = num(r.hrMin), hrMax = num(r.hrMax);
  if ([rateMin, rateMax, watts, hrMin, hrMax].some((n) => n != null && !Number.isFinite(n))) return { block: null, error: `${label}: rate, watts and heart rate must be numbers.` };
  return {
    block: {
      reps,
      ...(r.kind === "distance" ? { work_m: work } : { work_s: work }),
      rest_s: rest, zone: r.zone || null, rate_min: rateMin, rate_max: rateMax ?? rateMin, split_s: split, watts, hr_min: hrMin, hr_max: hrMax, note: r.note.trim() || null,
    },
    error: null,
  };
}

/** `bike`: a split is per 1000 m and the rate is pedal cadence (rpm); a bike's watts are a target of their own, never a pace. */
export function BlockEditor({ rows, onChange, ladder, bike = false }: { rows: BlockRow[]; onChange: (rows: BlockRow[]) => void; ladder?: boolean; bike?: boolean }) {
  const rateUnit = bike ? "rpm" : "spm";
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
              {bike ? "Cadence from" : "Rate from"}
              <input value={r.rateMin} onChange={(e) => set(i, { rateMin: e.target.value })} inputMode="decimal" placeholder={rateUnit} className={inputCls} aria-label={`Block ${i + 1} rate from`} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              to
              <input value={r.rateMax} onChange={(e) => set(i, { rateMax: e.target.value })} inputMode="decimal" placeholder={rateUnit} className={inputCls} aria-label={`Block ${i + 1} rate to`} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              {bike ? "Split /1000m" : "Split /500m"}
              <input value={r.split} onChange={(e) => set(i, { split: e.target.value, watts: e.target.value ? "" : r.watts })} placeholder="1:50" className={inputCls} aria-label={`Block ${i + 1} split`} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              or Watts
              <input value={r.watts} onChange={(e) => set(i, { watts: e.target.value, split: e.target.value ? "" : r.split })} inputMode="numeric" className={inputCls} aria-label={`Block ${i + 1} watts`} />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Heart rate from
              <input value={r.hrMin} onChange={(e) => set(i, { hrMin: e.target.value.replace(/[^\d]/g, "") })} inputMode="numeric" placeholder="bpm" className={inputCls} aria-label={`Block ${i + 1} heart rate from`} />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              to
              <input value={r.hrMax} onChange={(e) => set(i, { hrMax: e.target.value.replace(/[^\d]/g, "") })} inputMode="numeric" placeholder="bpm" className={inputCls} aria-label={`Block ${i + 1} heart rate to`} />
            </label>
          </div>
          <input value={r.note} onChange={(e) => set(i, { note: e.target.value })} placeholder="Note (optional)" aria-label={`Block ${i + 1} note`} className={inputCls} />
          <div className="flex gap-2">
            <button type="button" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move block ${i + 1} up`} className={buttonClass("secondary", "md", "min-w-11")}>
              ↑
            </button>
            <button type="button" onClick={() => move(i, 1)} disabled={i === rows.length - 1} aria-label={`Move block ${i + 1} down`} className={buttonClass("secondary", "md", "min-w-11")}>
              ↓
            </button>
            <button type="button" onClick={() => onChange(rows.filter((_, j) => j !== i))} aria-label={`Remove block ${i + 1}`} className={buttonClass("secondary", "md", "ml-auto")}>
              Remove
            </button>
          </div>
        </fieldset>
      ))}
      <button type="button" data-testid="add-block" onClick={() => onChange([...rows, blankRow()])} className={buttonClass("secondary", "md", "self-start")}>
        + Add {ladder ? "step" : "block"}
      </button>
    </div>
  );
}

// --- Warm-up / cool-down: a time or a distance, plus optional zone and targets (they used to be minutes only, and the editor
// silently dropped a distance or a zone the API or the coach had set).

export interface SegmentRow {
  by: "time" | "distance";
  amount: string;
  zone: ZoneLabel | "";
  hrMax: string;
  rateMax: string;
  /** Fields this editor doesn't show (rate_min, hr_min, note) are carried through untouched. */
  rest: Partial<TemplateSegment>;
}

export const blankSegment = (): SegmentRow => ({ by: "time", amount: "", zone: "", hrMax: "", rateMax: "", rest: {} });

export function segmentToRow(seg: TemplateSegment | null | undefined): SegmentRow {
  if (!seg) return blankSegment();
  const { duration_min, distance_m, zone, hr_max, rate_max, ...rest } = seg;
  return {
    by: distance_m != null ? "distance" : "time",
    amount: distance_m != null ? String(distance_m) : duration_min != null ? String(duration_min) : "",
    zone: zone ?? "",
    hrMax: hr_max != null ? String(hr_max) : "",
    rateMax: rate_max != null ? String(rate_max) : "",
    rest,
  };
}

export function rowToSegment(r: SegmentRow, label: string): { segment: TemplateSegment | null; error: string | null } {
  if (!r.amount.trim()) return { segment: null, error: null };
  const n = Number(r.amount);
  if (!Number.isFinite(n) || n <= 0) return { segment: null, error: `${label}: enter ${r.by === "time" ? "minutes" : "metres"} as a number.` };
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const hrMax = num(r.hrMax), rateMax = num(r.rateMax);
  if ([hrMax, rateMax].some((x) => x != null && !Number.isFinite(x))) return { segment: null, error: `${label}: heart rate and rate must be numbers.` };
  return {
    segment: { ...r.rest, ...(r.by === "time" ? { duration_min: n } : { distance_m: n }), zone: r.zone || null, hr_max: hrMax, rate_max: rateMax },
    error: null,
  };
}

export function SegmentEditor({ label, row, onChange, bike = false }: { label: string; row: SegmentRow; onChange: (r: SegmentRow) => void; bike?: boolean }) {
  const set = (patch: Partial<SegmentRow>) => onChange({ ...row, ...patch });
  const id = label.toLowerCase().replace(/[^a-z]/g, "");
  return (
    <fieldset className="flex flex-col gap-2 rounded-md border border-border p-3" data-testid={`segment-${id}`}>
      <legend className="px-1 text-xs text-text-tertiary">{label} (optional)</legend>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2">
        <label className="flex min-w-0 flex-col gap-1 text-xs text-text-secondary">
          By
          <select value={row.by} onChange={(e) => set({ by: e.target.value as SegmentRow["by"], amount: "" })} className={inputCls} aria-label={`${label} by`}>
            <option value="time">Minutes</option>
            <option value="distance">Metres</option>
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-xs text-text-secondary">
          {row.by === "time" ? "Minutes" : "Metres"}
          <input value={row.amount} onChange={(e) => set({ amount: e.target.value })} inputMode="decimal" className={inputCls} aria-label={`${label} ${row.by === "time" ? "minutes" : "metres"}`} />
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-xs text-text-secondary">
          Zone
          <select value={row.zone} onChange={(e) => set({ zone: e.target.value as ZoneLabel | "" })} className={inputCls} aria-label={`${label} zone`}>
            <option value="">None</option>
            {ZONE_CHOICES.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex min-w-0 flex-col gap-1 text-xs text-text-secondary">
          Heart rate up to
          <input value={row.hrMax} onChange={(e) => set({ hrMax: e.target.value.replace(/[^\d]/g, "") })} inputMode="numeric" placeholder="bpm" className={inputCls} aria-label={`${label} heart rate up to`} />
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-xs text-text-secondary">
          {bike ? "Cadence up to" : "Rate up to"}
          <input value={row.rateMax} onChange={(e) => set({ rateMax: e.target.value })} inputMode="decimal" placeholder={bike ? "rpm" : "spm"} className={inputCls} aria-label={`${label} rate up to`} />
        </label>
      </div>
    </fieldset>
  );
}
