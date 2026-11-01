import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Domain } from "../../lib/useChartInteraction";

const HEIGHT = 36;
const HANDLE_WIDTH = 20;

// The slim overview strip under a Trends/Body chart (interaction spec #3) — shows the full
// history as a thin backdrop line, with a draggable/resizable window (the "brush") over the
// currently-visible range. Dragging the window body pans the main chart; dragging either edge
// resizes it (re-zooms). Deliberately its own small pointer-event handler, not a reuse of
// useChartInteraction — a brush drags a *rectangle*, not the content underneath it.
export function ChartNavigator({
  fullDomain,
  viewDomain,
  minSpan,
  onChange,
  onChangeSettled,
  backdrop,
}: {
  fullDomain: Domain;
  viewDomain: Domain;
  minSpan: number;
  onChange: (domain: Domain) => void;
  /** Fired once per drag/click, not per pointermove — the data-fetch/URL-commit hook. */
  onChangeSettled?: (domain: Domain) => void;
  backdrop?: { x: number; y: number }[];
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ mode: "move" | "left" | "right"; startClientX: number; startView: Domain } | null>(null);
  const lastComputed = useRef<Domain>(viewDomain);

  // The viewBox width must track the SVG's real rendered width (same pattern every other
  // chart already uses) — a hardcoded viewBox width with `width="100%"` relies on the
  // browser's default `preserveAspectRatio="xMidYMid meet"` to reconcile a mismatched aspect
  // ratio, which it does by *letterboxing*: at a wide viewport the brush strip's real content
  // rendered centered in a fraction of the card (verified via getBoundingClientRect — the
  // backdrop rect's screen box was offset and narrower than the SVG's own element box), and at
  // a narrow viewport by scaling the whole strip down to ~57% size, shrinking the 36px-tall
  // strip (and its already-thin resize handles) to an untouchable ~20px. Measuring the real
  // width and keeping the viewBox's width equal to it eliminates the aspect-ratio mismatch
  // this depended on, so `meet` never has anything to reconcile.
  const [width, setWidth] = useState(600);
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(Math.max(w, 50));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const fullSpan = Math.max(fullDomain.max - fullDomain.min, 1);
  const toPx = useCallback((t: number) => ((t - fullDomain.min) / fullSpan) * width, [fullDomain.min, fullSpan, width]);
  const toDomain = useCallback((px: number) => fullDomain.min + (px / width) * fullSpan, [fullDomain.min, fullSpan, width]);

  const winX0 = toPx(viewDomain.min);
  const winX1 = toPx(viewDomain.max);

  const clamp = useCallback(
    (d: Domain): Domain => {
      const span = Math.min(Math.max(d.max - d.min, minSpan), fullSpan);
      let min = d.min;
      let max = min + span;
      if (min < fullDomain.min) {
        min = fullDomain.min;
        max = min + span;
      }
      if (max > fullDomain.max) {
        max = fullDomain.max;
        min = max - span;
      }
      return { min, max };
    },
    [fullDomain, fullSpan, minSpan],
  );

  const onHandlePointerDown = (mode: "move" | "left" | "right") => (e: React.PointerEvent) => {
    e.stopPropagation();
    try {
      (e.target as Element).setPointerCapture(e.pointerId);
    } catch {
      // Drag tracking still works without capture — see useChartInteraction's identical guard.
    }
    drag.current = { mode, startClientX: e.clientX, startView: viewDomain };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const dxPx = ((e.clientX - d.startClientX) / rect.width) * width;
    const dxDomain = (dxPx / width) * fullSpan;
    let next: Domain;
    if (d.mode === "move") {
      next = clamp({ min: d.startView.min + dxDomain, max: d.startView.max + dxDomain });
    } else if (d.mode === "left") {
      next = clamp({ min: d.startView.min + dxDomain, max: d.startView.max });
    } else {
      next = clamp({ min: d.startView.min, max: d.startView.max + dxDomain });
    }
    lastComputed.current = next;
    onChange(next);
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (drag.current) onChangeSettled?.(lastComputed.current);
    drag.current = null;
    (e.target as Element).releasePointerCapture?.(e.pointerId);
  };

  const onBackgroundClick = (e: React.MouseEvent) => {
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const clickX = ((e.clientX - rect.left) / rect.width) * width;
    const center = toDomain(clickX);
    const span = viewDomain.max - viewDomain.min;
    const next = clamp({ min: center - span / 2, max: center + span / 2 });
    onChange(next);
    onChangeSettled?.(next);
  };

  // Memoized: `backdrop`/`fullDomain`/`fullSpan`/`width` don't change while the user pans/
  // zooms the *view* window, but this component re-renders every frame of that gesture (its
  // own `viewDomain` prop is changing) — recomputing a ~600-point path string each frame
  // showed up as real dropped frames in a CPU-throttled pan test before this fix.
  const pathD = useMemo(
    () => (backdrop && backdrop.length > 1 ? buildSparklinePath(backdrop, fullDomain, fullSpan, width) : null),
    [backdrop, fullDomain, fullSpan, width],
  );

  return (
    <svg
      ref={svgRef}
      width="100%"
      height={HEIGHT}
      viewBox={`0 0 ${width} ${HEIGHT}`}
      role="slider"
      aria-label="Visible range"
      aria-valuemin={fullDomain.min}
      aria-valuemax={fullDomain.max}
      aria-valuenow={(viewDomain.min + viewDomain.max) / 2}
      className="touch-none select-none"
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onClick={onBackgroundClick}
    >
      <rect x={0} y={0} width={width} height={HEIGHT} rx={6} fill="var(--surface-2)" />
      {pathD && <path d={pathD} fill="none" stroke="var(--text-tertiary)" strokeWidth={1} opacity={0.6} />}
      <rect x={0} y={0} width={Math.max(winX0, 0)} height={HEIGHT} fill="var(--bg)" opacity={0.6} />
      <rect x={winX1} y={0} width={Math.max(width - winX1, 0)} height={HEIGHT} fill="var(--bg)" opacity={0.6} />
      <rect
        x={winX0}
        y={1}
        width={Math.max(winX1 - winX0, 2)}
        height={HEIGHT - 2}
        rx={5}
        fill="var(--accent)"
        opacity={0.18}
        stroke="var(--accent)"
        strokeWidth={1.5}
        onPointerDown={onHandlePointerDown("move")}
        className="cursor-grab"
      />
      <rect
        x={winX0 - HANDLE_WIDTH / 2}
        y={0}
        width={HANDLE_WIDTH}
        height={HEIGHT}
        fill="transparent"
        onPointerDown={onHandlePointerDown("left")}
        className="cursor-ew-resize"
      />
      <rect
        x={winX1 - HANDLE_WIDTH / 2}
        y={0}
        width={HANDLE_WIDTH}
        height={HEIGHT}
        fill="transparent"
        onPointerDown={onHandlePointerDown("right")}
        className="cursor-ew-resize"
      />
    </svg>
  );
}

function buildSparklinePath(points: { x: number; y: number }[], domain: Domain, span: number, width: number): string {
  const ys = points.map((p) => p.y);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const range = max - min || 1;
  const toX = (x: number) => ((x - domain.min) / span) * width;
  const toY = (y: number) => HEIGHT - 4 - ((y - min) / range) * (HEIGHT - 8);
  return "M " + points.map((p) => `${toX(p.x)},${toY(p.y)}`).join(" L ");
}
