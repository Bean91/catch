import { bandLabel } from "../../lib/format";

const BAND_COLOR_VAR: Record<string, string> = {
  green: "var(--band-green)",
  optimal: "var(--band-green)",
  light: "var(--band-green)",
  on_target: "var(--band-green)",
  yellow: "var(--band-yellow)",
  caution: "var(--band-yellow)",
  moderate: "var(--band-yellow)",
  undertraining: "var(--band-yellow)",
  below_target: "var(--band-yellow)",
  red: "var(--band-red)",
  high_risk: "var(--band-red)",
  high: "var(--band-red)",
  all_out: "var(--band-red)",
  well_below_target: "var(--band-red)",
  calibrating: "var(--band-calibrating)",
  insufficient_data: "var(--band-calibrating)",
};

/** A status pill: a dot in the band's colour on a faint tint of it, and always the band's word (never colour alone). */
export function BandBadge({ band, label }: { band: string | null | undefined; label?: string }) {
  const color = BAND_COLOR_VAR[band ?? "calibrating"] ?? "var(--band-calibrating)";
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium text-text-primary"
      style={{ borderColor: `color-mix(in oklab, ${color} 35%, transparent)`, background: `color-mix(in oklab, ${color} 12%, transparent)` }}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: color, boxShadow: `0 0 0 3px color-mix(in oklab, ${color} 22%, transparent)` }} />
      {label ?? bandLabel(band)}
    </span>
  );
}

export type BadgeTone = "neutral" | "accent" | "outline";

/** A small neutral label ("Estimate", "Bike", "GPS-derived"). Status has its own BandBadge. */
export function Badge({ children, tone = "neutral", className = "" }: { children: React.ReactNode; tone?: BadgeTone; className?: string }) {
  const t =
    tone === "accent"
      ? "border-accent/30 bg-accent-soft text-accent"
      : tone === "outline"
        ? "border-border-strong text-text-secondary"
        : "border-transparent bg-surface-3 text-text-secondary";
  return <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${t} ${className}`}>{children}</span>;
}
