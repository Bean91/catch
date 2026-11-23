import { Link } from "react-router-dom";
import { formatDuration, formatSplit, splitUnitLabel } from "../../lib/format";
import type { CompareRow, PlanComparisonResponse, ValueBasis } from "../../lib/types";

const METRIC_LABEL: Record<CompareRow["metric"], string> = {
  duration_s: "Time",
  distance_m: "Distance",
  split_s: "Split",
  watts: "Power",
  rate: "Rate",
  hr: "Heart rate",
};

const SOURCE_TEXT: Record<string, string> = {
  piece: "the intervals saved on this workout",
  concept2: "the Concept2 result's own intervals",
  laps: "the device's laps",
};

const BASIS_TEXT: Partial<Record<ValueBasis, string>> = { derived: "worked out", entered: "typed" };

function fmt(metric: CompareRow["metric"], v: number | null | undefined, splitM: number, bike: boolean): string {
  if (v == null) return "—";
  switch (metric) {
    case "duration_s":
      return formatDuration(v);
    case "distance_m":
      return `${Math.round(v).toLocaleString()} m`;
    case "split_s":
      return `${formatSplit(v)} ${splitUnitLabel(splitM)}`;
    case "watts":
      return `${Math.round(v)} W`;
    case "rate":
      return `${v.toFixed(1)} ${bike ? "rpm" : "spm"}`;
    case "hr":
      return `${Math.round(v)} bpm`;
  }
}

function targetText(r: CompareRow, splitM: number, bike: boolean): string {
  const t = r.target;
  if (t.value != null) return fmt(r.metric, t.value, splitM, bike);
  const unit = r.metric === "hr" ? "bpm" : bike ? "rpm" : "spm";
  if (t.min != null && t.max != null) return `${Math.round(t.min)}–${Math.round(t.max)} ${unit}`;
  if (t.max != null) return `≤ ${Math.round(t.max)} ${unit}`;
  return `≥ ${Math.round(t.min ?? 0)} ${unit}`;
}

/** The difference in words, never a verdict: "1.0 s slower", "2:00 shorter", "in range". */
function diffText(r: CompareRow): string | null {
  if (r.actual == null) return "not recorded";
  if (r.status) return r.status === "in_range" ? "✓ in range" : r.status === "above" ? "↑ above" : "↓ below";
  const d = r.delta;
  if (d == null) return null;
  const a = Math.abs(d);
  switch (r.metric) {
    case "split_s":
      return a < 0.05 ? "on target" : `${a.toFixed(1)} s ${d > 0 ? "slower" : "faster"}`;
    case "duration_s":
      return a < 1 ? "on target" : `${formatDuration(a)} ${d > 0 ? "longer" : "shorter"}`;
    case "distance_m":
      return a < 1 ? "on target" : `${Math.round(a).toLocaleString()} m ${d > 0 ? "further" : "short"}`;
    case "watts":
      return a < 0.5 ? "on target" : `${Math.round(a)} W ${d > 0 ? "more" : "less"}`;
    default:
      return null;
  }
}

function Row({ r, splitM, bike }: { r: CompareRow; splitM: number; bike: boolean }) {
  const basis = r.actual_basis ? BASIS_TEXT[r.actual_basis] : undefined;
  return (
    <li className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5 text-sm" data-testid="compare-row">
      <span className="w-20 shrink-0 text-text-secondary">{METRIC_LABEL[r.metric]}</span>
      <span className="font-mono-nums text-text-primary">{fmt(r.metric, r.actual, splitM, bike)}</span>
      <span className="text-xs text-text-tertiary">
        target <span className="font-mono-nums">{targetText(r, splitM, bike)}</span>
      </span>
      {diffText(r) && <span className="text-xs text-text-secondary">· {diffText(r)}</span>}
      {basis && <span className="text-xs text-text-tertiary">({basis})</span>}
    </li>
  );
}

const KIND_LABEL = { warmup: "Warm-up", cooldown: "Cool-down", work: "Rep" } as const;

/** Planned against done: only the targets that were set, the difference in words, and how each actual figure was obtained. */
export function PlanComparisonView({ data, showWorkoutLink = true }: { data: PlanComparisonResponse; showWorkoutLink?: boolean }) {
  const c = data.comparison;
  const splitM = data.split_basis_m ?? 500;
  const bike = data.workout?.sport_family === "cycling";
  if (!c) return <p className="text-sm text-text-tertiary">{data.reason}</p>;
  if (!c.has_targets) return <p className="text-sm text-text-tertiary">This plan had no targets to compare — it is linked, and counts as done.</p>;
  let workNo = 0;
  return (
    <div className="flex flex-col gap-3" data-testid="plan-comparison">
      {showWorkoutLink && data.workout && (
        <p className="text-sm text-text-secondary">
          Compared with{" "}
          <Link to={data.workout.ref} className="text-accent underline">
            {data.workout.title ?? "the linked workout"}
          </Link>
          {c.reps_source && <> — reps from {SOURCE_TEXT[c.reps_source]}</>}.
        </p>
      )}
      {c.totals.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-wide text-text-tertiary">Whole session</h4>
          <ul className="divide-y divide-border/70">
            {c.totals.map((r) => (
              <Row key={r.metric} r={r} splitM={splitM} bike={bike} />
            ))}
            {c.whole.map((r) => (
              <Row key={`w${r.metric}`} r={r} splitM={splitM} bike={bike} />
            ))}
          </ul>
        </div>
      )}
      {c.totals.length === 0 && c.whole.length > 0 && (
        <ul className="divide-y divide-border/70">
          {c.whole.map((r) => (
            <Row key={`w${r.metric}`} r={r} splitM={splitM} bike={bike} />
          ))}
        </ul>
      )}
      {c.reps.map((rep) => {
        const label = rep.kind === "work" ? `Rep ${++workNo}` : KIND_LABEL[rep.kind];
        return (
          <div key={rep.index}>
            <h4 className="text-xs font-medium uppercase tracking-wide text-text-tertiary">{label}</h4>
            <ul className="divide-y divide-border/70">
              {rep.metrics.map((r) => (
                <Row key={r.metric} r={r} splitM={splitM} bike={bike} />
              ))}
            </ul>
          </div>
        );
      })}
      {c.reason && <p className="text-xs text-text-tertiary">{c.reason}</p>}
    </div>
  );
}
