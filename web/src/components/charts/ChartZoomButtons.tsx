// Shared +/- zoom buttons (interaction spec #2) overlaid on every pan/zoom-capable chart —
// touch-action: manipulation so a fast double-tap on a button doesn't also trigger iOS's
// double-tap-to-zoom, each a full var(--touch-target) (44px) hit target per the existing
// site-wide touch-target convention (checked programmatically in an earlier session).
export function ChartZoomButtons({ onZoomIn, onZoomOut, onReset }: { onZoomIn: () => void; onZoomOut: () => void; onReset: () => void }) {
  const buttonClass =
    "flex items-center justify-center rounded-md border border-border bg-surface text-text-secondary transition-colors hover:border-accent/40";
  const style: React.CSSProperties = { touchAction: "manipulation", width: "var(--touch-target)", height: "var(--touch-target)" };
  return (
    <div className="absolute right-1 top-1 flex gap-1">
      <button type="button" aria-label="Reset zoom" onClick={onReset} className={`${buttonClass} text-xs text-text-tertiary`} style={style}>
        ⟲
      </button>
      <button type="button" aria-label="Zoom out" onClick={onZoomOut} className={`${buttonClass} text-base`} style={style}>
        −
      </button>
      <button type="button" aria-label="Zoom in" onClick={onZoomIn} className={`${buttonClass} text-base`} style={style}>
        +
      </button>
    </div>
  );
}
