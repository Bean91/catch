import { formatClock } from "../../lib/duration";
import type { TemplateStructure } from "../../lib/types";
import { blockTargets, blockWork, segmentText } from "./labels";

export function StructureView({ structure, exerciseNames }: { structure: TemplateStructure; exerciseNames?: Record<number, string> }) {
  const warm = segmentText(structure.warmup);
  const cool = segmentText(structure.cooldown);
  const blocks = structure.blocks ?? [];
  const items = structure.strength_items ?? [];
  if (!warm && !cool && blocks.length === 0 && items.length === 0) {
    return <p className="text-sm text-text-secondary">No structured blocks — see the description.</p>;
  }
  return (
    <ol className="flex flex-col gap-2" data-testid="structure">
      {warm && (
        <li className="rounded-md bg-surface-2 px-3 py-2 text-sm">
          <span className="text-text-tertiary">Warm-up</span> <span className="font-mono-nums text-text-primary">{warm}</span>
        </li>
      )}
      {blocks.map((b, i) => (
        <li key={i} className="rounded-md border border-border px-3 py-2 text-sm" data-testid="structure-block">
          <p className="font-mono-nums text-text-primary">
            {b.reps} × {blockWork(b)}
            {b.rest_s ? <span className="text-text-secondary"> · rest {formatClock(b.rest_s)}</span> : null}
          </p>
          {(blockTargets(b).length > 0 || b.note) && (
            <p className="text-text-secondary">
              {blockTargets(b).join(" · ")}
              {b.note ? `${blockTargets(b).length ? " · " : ""}${b.note}` : ""}
            </p>
          )}
        </li>
      ))}
      {items.map((it, i) => (
        <li key={i} className="rounded-md border border-border px-3 py-2 text-sm">
          <p className="text-text-primary">{exerciseNames?.[it.exercise_id] ?? `Exercise #${it.exercise_id}`}</p>
          <p className="font-mono-nums text-text-secondary">
            {it.target_sets ?? "—"} × {it.target_reps ?? "—"}
            {it.note ? ` · ${it.note}` : ""}
          </p>
        </li>
      ))}
      {cool && (
        <li className="rounded-md bg-surface-2 px-3 py-2 text-sm">
          <span className="text-text-tertiary">Cool-down</span> <span className="font-mono-nums text-text-primary">{cool}</span>
        </li>
      )}
    </ol>
  );
}
