import { useMemo, useRef, useState } from "react";
import { addDays, parseISODate, todayISO, weekStart } from "../../lib/dates";
import { formatShortDate } from "../../lib/format";
import { ChartTooltip, useChartWidth } from "./core";

const WEEKDAYS = ["M", "", "W", "", "F", "", "S"];

/**
 * A training-consistency heatmap: one cell per day, weeks as columns (Monday first), shaded on one sequential ramp of the accent from
 * "no load" to the window's busiest day. Empty days are an outline, never a colour that could read as a value; days without data
 * at all are blank. Hover or focus a cell for its date and value; the whole grid also has a spoken summary.
 */
export function CalendarHeatmap({
  days,
  weeks = 26,
  format,
  label,
  emptyLabel = "No training",
  onSelect,
}: {
  /** Daily values keyed by ISO date; a missing key or null means no data. */
  days: Record<string, number | null>;
  weeks?: number;
  format: (v: number) => string;
  label: string;
  emptyLabel?: string;
  onSelect?: (date: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const width = useChartWidth(ref, 320);
  const [hover, setHover] = useState<{ date: string; col: number } | null>(null);

  const grid = useMemo(() => {
    const today = todayISO();
    const first = addDays(weekStart(today), -7 * (weeks - 1));
    let max = 0;
    let active = 0;
    const cols: { date: string; value: number | null; future: boolean }[][] = [];
    for (let w = 0; w < weeks; w++) {
      const col: { date: string; value: number | null; future: boolean }[] = [];
      for (let d = 0; d < 7; d++) {
        const date = addDays(first, w * 7 + d);
        const v = days[date] ?? null;
        if (v != null && v > max) max = v;
        if (v != null && v > 0) active++;
        col.push({ date, value: v, future: date > today });
      }
      cols.push(col);
    }
    return { cols, max, active, first };
  }, [days, weeks]);

  const labelW = 14;
  const gap = 3;
  const cell = Math.max(Math.min(Math.floor((width - labelW - gap * weeks) / weeks), 16), 6);
  const h = 7 * (cell + gap) + 16;
  const w = labelW + weeks * (cell + gap);
  const fill = (v: number | null) => {
    if (v == null || v <= 0) return null;
    const f = grid.max > 0 ? v / grid.max : 0;
    // Five steps so neighbouring days stay distinguishable; the lightest step still clears the surface.
    const step = f > 0.8 ? 100 : f > 0.6 ? 80 : f > 0.4 ? 62 : f > 0.2 ? 44 : 28;
    return `color-mix(in oklab, var(--accent) ${step}%, var(--surface-2))`;
  };

  const hovered = hover ? grid.cols[hover.col].find((c) => c.date === hover.date) ?? null : null;
  const monthLabels: { col: number; text: string }[] = [];
  grid.cols.forEach((col, i) => {
    const d = parseISODate(col[0].date);
    if (d.getDate() <= 7) monthLabels.push({ col: i, text: d.toLocaleDateString(undefined, { month: "short" }) });
  });

  return (
    <div ref={ref} className="relative">
      <svg
        width="100%"
        height={h}
        viewBox={`0 0 ${Math.max(width, w)} ${h}`}
        role="img"
        aria-label={`${label}: ${grid.active} active days in the last ${weeks} weeks, starting ${formatShortDate(grid.first)}.`}
        onPointerLeave={() => setHover(null)}
      >
        {monthLabels.map((m) => (
          <text key={m.col} x={labelW + m.col * (cell + gap)} y={9} fontSize={10} fill="var(--text-tertiary)">
            {m.text}
          </text>
        ))}
        {WEEKDAYS.map((d, i) =>
          d ? (
            <text key={i} x={0} y={16 + i * (cell + gap) + cell * 0.75} fontSize={9} fill="var(--text-tertiary)">
              {d}
            </text>
          ) : null,
        )}
        {grid.cols.map((col, ci) =>
          col.map((c, di) => {
            if (c.future) return null;
            const f = fill(c.value);
            return (
              <rect
                key={c.date}
                x={labelW + ci * (cell + gap)}
                y={14 + di * (cell + gap)}
                width={cell}
                height={cell}
                rx={Math.min(3, cell / 4)}
                fill={f ?? "transparent"}
                stroke={f ? "none" : "var(--border)"}
                strokeWidth={1}
                onPointerEnter={() => setHover({ date: c.date, col: ci })}
                onClick={onSelect ? () => onSelect(c.date) : undefined}
                style={onSelect ? { cursor: "pointer" } : undefined}
              />
            );
          }),
        )}
      </svg>
      {hovered && (
        <ChartTooltip
          xPct={((labelW + hover!.col * (cell + gap)) / Math.max(width, w)) * 100}
          title={formatShortDate(hovered.date)}
          rows={[{ label: hovered.value != null && hovered.value > 0 ? "Load" : emptyLabel, value: hovered.value != null && hovered.value > 0 ? format(hovered.value) : "—" }]}
        />
      )}
      <div className="mt-1 flex items-center justify-end gap-1.5 text-[11px] text-text-tertiary" aria-hidden>
        Less
        {[28, 44, 62, 80, 100].map((s) => (
          <span key={s} className="h-2.5 w-2.5 rounded-[3px]" style={{ background: `color-mix(in oklab, var(--accent) ${s}%, var(--surface-2))` }} />
        ))}
        More
      </div>
    </div>
  );
}
