import { formatSplit } from "../../lib/format";
import type { IntervalBlock } from "../../lib/types";

const KIND_LABEL = { warmup: "Warm-up", cooldown: "Cool-down" } as const;

function amount(b: IntervalBlock): string {
  // A distance block is described by its distance; a duration carried beside it is only an estimate for the planner's totals.
  if (b.work_m != null) return `${Math.round(b.work_m).toLocaleString()} m`;
  if (b.work_min != null) {
    const s = Math.round(b.work_min * 60);
    return s % 60 === 0 ? `${s / 60} min` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }
  return "";
}

function rest(min: number): string {
  const s = Math.round(min * 60);
  return s < 60 ? `${s}s rest` : s % 60 === 0 ? `${s / 60} min rest` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} rest`;
}

/** One planned block in words: "4 × 500 m, 1:30 rest · 1:45.0 /500m · 24–26 spm". Only targets that were set appear. */
export function blockText(b: IntervalBlock, sportFamily?: string | null): string {
  const basis = sportFamily === "cycling" ? "/1000m" : "/500m";
  const head = b.kind && b.kind !== "work" ? `${KIND_LABEL[b.kind]} ${amount(b)}` : `${b.reps > 1 ? `${b.reps} × ` : ""}${amount(b)}`;
  const parts = [head + (b.rest_min ? `, ${rest(b.rest_min)}` : "")];
  if (b.split_s != null) parts.push(`${formatSplit(b.split_s)} ${basis}`);
  if (b.watts != null) parts.push(`${Math.round(b.watts)} W`);
  if (b.rate_min != null || b.rate_max != null) {
    const r = b.rate_min != null && b.rate_max != null && b.rate_min !== b.rate_max ? `${b.rate_min}–${b.rate_max}` : `${b.rate_min ?? b.rate_max}`;
    parts.push(`${r} ${sportFamily === "cycling" ? "rpm" : "spm"}`);
  }
  if (b.hr_min != null || b.hr_max != null) {
    const h = b.hr_min != null && b.hr_max != null ? `${b.hr_min}–${b.hr_max}` : b.hr_max != null ? `≤ ${b.hr_max}` : `≥ ${b.hr_min}`;
    parts.push(`HR ${h} bpm`);
  }
  if (b.zone) parts.push(b.zone);
  return parts.join(" · ");
}

export function BlockLine({ b, sportFamily }: { b: IntervalBlock; sportFamily?: string | null }) {
  return (
    <>
      <span className="font-mono-nums">{blockText(b, sportFamily)}</span>
      {b.note && <span className="text-text-tertiary"> — {b.note}</span>}
    </>
  );
}
