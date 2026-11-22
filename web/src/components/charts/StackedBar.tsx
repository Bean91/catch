import { cn } from "../../lib/cn";

export type StackedSegment = { key: string; label: string; value: number; color: string; detail?: string };

/**
 * One horizontal 100%-stacked bar (time in zone, sleep stages, training distribution), with a 2px surface gap between segments and
 * an optional legend that carries every number in words. The bar itself is `role="img"` with a full text summary, so nothing
 * depends on telling the segment colours apart.
 */
export function StackedBar({
  segments,
  height = 8,
  legend = false,
  summary,
  className,
  testId,
}: {
  segments: StackedSegment[];
  height?: number;
  legend?: boolean;
  /** The spoken summary; defaults to "label detail" for each segment. */
  summary?: string;
  className?: string;
  testId?: string;
}) {
  const shown = segments.filter((s) => s.value > 0);
  const total = shown.reduce((a, s) => a + s.value, 0);
  if (total <= 0) return null;
  const label = summary ?? shown.map((s) => `${s.label} ${s.detail ?? ""}`.trim()).join(", ");
  return (
    <div className={className} data-testid={testId}>
      <div className="flex w-full gap-[2px] overflow-hidden rounded-full" style={{ height }} role="img" aria-label={label}>
        {shown.map((s) => (
          <div key={s.key} className="h-full min-w-[2px] first:rounded-l-full last:rounded-r-full" style={{ width: `${(s.value / total) * 100}%`, background: s.color }} title={`${s.label}${s.detail ? `: ${s.detail}` : ""}`} />
        ))}
      </div>
      {legend && (
        <ul className={cn("mt-2 flex flex-wrap gap-x-3.5 gap-y-1 text-xs text-text-secondary")}>
          {shown.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span aria-hidden className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
              <span>
                {s.label}
                {s.detail && <span className="ml-1 font-mono-nums text-text-tertiary">{s.detail}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
