import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// Shared gesture/zoom/pan engine for every time-series (and the erg distance) chart — one hook
// instead of duplicating pointer/wheel/keyboard handling per chart component. The domain is a
// generic numeric range (epoch-ms for time charts, meters for ErgChart's distance axis); callers
// supply the full extent and a minimum zoomed-in span, and read back the current view window to
// compute their own x-scale.

export interface Domain {
  min: number;
  max: number;
}

export interface UseChartInteractionOptions {
  /** Current view window — owned by the caller (not this hook), so sibling charts can share
   * one domain by lifting it to a common ancestor (Trends' linked charts, spec #6). */
  domain: Domain;
  fullDomain: Domain;
  minSpan: number;
  /** Plot-area pixel width (excludes axis padding) — used to convert pointer px <-> domain. */
  plotWidthPx: number;
  /** The chart's root DOM node — ctrl/cmd+wheel zoom is attached here as a native, non-passive
   * listener (see the effect below for why it can't be React's onWheel prop). */
  surfaceRef: React.RefObject<Element | null>;
  /** Left-edge margin (axis-label gutter) inside the surface before the plot area starts, in
   * the same units as the surface's own CSS pixel width — defaults to 0 for a surface with no
   * such margin (e.g. ChartNavigator doesn't use this hook at all). */
  padLeft?: number;
  /** Called continuously while panning/zooming (rAF-throttled internally) — the caller is
   * expected to feed this straight back in as `domain` on its next render. */
  onViewChange: (domain: Domain) => void;
  /** Called once a gesture ends (pointer up, wheel idle, keyboard action) — the place to
   * trigger a refetch or URL update, so those don't fire on every intermediate frame. */
  onSettled?: (domain: Domain) => void;
  /** A single point tap (not a drag, not the second tap of a double-tap) — e.g. opening a
   * workout from a point on a trend chart. Gives the domain x-value and the raw client coords
   * (for tooltip positioning) of the tap/click. */
  onTap?: (domainX: number, clientX: number, clientY: number) => void;
  /** Double-click / double-tap — callers reset to their own default/preset domain. */
  onDoubleTap?: () => void;
  disabled?: boolean;
}

export interface ChartInteractionHandlers {
  onPointerDown: (e: React.PointerEvent) => void;
  onPointerMove: (e: React.PointerEvent) => void;
  onPointerUp: (e: React.PointerEvent) => void;
  onPointerCancel: (e: React.PointerEvent) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  onDoubleClick: (e: React.MouseEvent) => void;
}

export interface UseChartInteractionResult {
  handlers: ChartInteractionHandlers;
  zoomIn: () => void;
  zoomOut: () => void;
  panBy: (fractionOfSpan: number) => void;
  reset: (domain: Domain) => void;
  /** Domain x-value under the pointer, while hovering/holding and not actively dragging. */
  hoverX: number | null;
  setHoverX: (x: number | null) => void;
  isPanning: boolean;
}

const TAP_MOVE_THRESHOLD_PX = 8;
const DIRECTION_LOCK_THRESHOLD_PX = 6;
const DOUBLE_TAP_MS = 350;
const DOUBLE_TAP_DIST_PX = 32;

function clampDomain(domain: Domain, full: Domain, minSpan: number): Domain {
  const span = Math.min(Math.max(domain.max - domain.min, minSpan), full.max - full.min);
  let min = domain.min;
  let max = min + span;
  if (min < full.min) {
    min = full.min;
    max = min + span;
  }
  if (max > full.max) {
    max = full.max;
    min = max - span;
  }
  return { min, max };
}

export function useChartInteraction(opts: UseChartInteractionOptions): UseChartInteractionResult {
  const { domain, fullDomain, minSpan, plotWidthPx, surfaceRef, padLeft = 0, onViewChange, onSettled, onTap, onDoubleTap, disabled } = opts;
  const [hoverX, setHoverX] = useState<number | null>(null);
  const [isPanning, setIsPanning] = useState(false);

  // Mutable gesture state kept out of React state — it changes on every pointermove and must
  // never itself trigger a re-render (that's what onViewChange's rAF throttle is for).
  const gesture = useRef({
    pointers: new Map<number, { x: number; y: number }>(),
    mode: "idle" as "idle" | "pending" | "pan" | "pinch" | "vertical-scroll",
    startDomain: fullDomain,
    startPointer: { x: 0, y: 0 },
    startTime: 0,
    pinchStartDist: 0,
    pinchStartMid: 0,
    lastTap: { time: 0, x: 0 },
    rafPending: false,
  });

  // The hook is "controlled": `domainRef` is normally just a same-frame mirror of the
  // `domain` prop, kept as a ref purely so gesture math reads/writes synchronously without
  // waiting for React to re-render between pointermove events — not a second source of truth.
  const domainRef = useRef(domain);
  domainRef.current = domain;

  const commit = useCallback(
    (next: Domain, { settled }: { settled: boolean }) => {
      const clamped = clampDomain(next, fullDomain, minSpan);
      domainRef.current = clamped;
      if (!gesture.current.rafPending) {
        gesture.current.rafPending = true;
        requestAnimationFrame(() => {
          gesture.current.rafPending = false;
          onViewChange(domainRef.current);
        });
      }
      if (settled) onSettled?.(clamped);
    },
    [fullDomain, minSpan, onViewChange, onSettled],
  );

  const pxToDomainDelta = useCallback((dxPx: number) => {
    if (plotWidthPx <= 0) return 0;
    const span = domainRef.current.max - domainRef.current.min;
    return (dxPx / plotWidthPx) * span;
  }, [plotWidthPx]);

  const pxToDomainValue = useCallback(
    (clientX: number, rect: DOMRect) => {
      // The data only occupies [padLeft, padLeft + plotWidthPx] of the surface's own width
      // (the rest is axis-label margin) — using the surface's *full* rect.width as the
      // denominator here would shift every crosshair/zoom-center position by ~padLeft worth
      // of domain, most visible near the edges.
      const span = domainRef.current.max - domainRef.current.min;
      const frac = (clientX - rect.left - padLeft) / Math.max(plotWidthPx, 1);
      return domainRef.current.min + frac * span;
    },
    [padLeft, plotWidthPx],
  );

  const zoomAt = useCallback(
    (factor: number, centerDomainX: number) => {
      const d = domainRef.current;
      const span = d.max - d.min;
      const newSpan = Math.min(Math.max(span / factor, minSpan), fullDomain.max - fullDomain.min);
      const frac = (centerDomainX - d.min) / Math.max(span, 1e-9);
      let min = centerDomainX - frac * newSpan;
      let max = min + newSpan;
      commit({ min, max }, { settled: true });
    },
    [commit, fullDomain, minSpan],
  );

  const zoomIn = useCallback(() => zoomAt(1.5, (domainRef.current.min + domainRef.current.max) / 2), [zoomAt]);
  const zoomOut = useCallback(() => zoomAt(1 / 1.5, (domainRef.current.min + domainRef.current.max) / 2), [zoomAt]);

  const panBy = useCallback(
    (fractionOfSpan: number) => {
      const d = domainRef.current;
      const span = d.max - d.min;
      const delta = span * fractionOfSpan;
      commit({ min: d.min + delta, max: d.max + delta }, { settled: true });
    },
    [commit],
  );

  const reset = useCallback(
    (next: Domain) => {
      commit(next, { settled: true });
    },
    [commit],
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (disabled) return;
      const g = gesture.current;
      g.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      // Wrapped: an uncaught throw here (e.g. no genuinely active pointer with this id — seen
      // from a synthetic PointerEvent in testing, but defensive for any real browser quirk
      // too) would abort the rest of this handler and leave gesture state never initialized.
      try {
        (e.target as Element).setPointerCapture?.(e.pointerId);
      } catch {
        // Gesture tracking still works without capture; it just won't survive the pointer
        // leaving this element's bounds mid-drag.
      }

      if (g.pointers.size === 1) {
        g.mode = "pending";
        g.startDomain = domainRef.current;
        g.startPointer = { x: e.clientX, y: e.clientY };
        g.startTime = performance.now();
        setHoverX(pxToDomainValue(e.clientX, (e.currentTarget as Element).getBoundingClientRect()));
      } else if (g.pointers.size === 2) {
        const pts = Array.from(g.pointers.values());
        g.mode = "pinch";
        g.pinchStartDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
        g.pinchStartMid = (pts[0].x + pts[1].x) / 2;
        g.startDomain = domainRef.current;
      }
    },
    [disabled, pxToDomainValue],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (disabled) return;
      const g = gesture.current;
      if (!g.pointers.has(e.pointerId)) return;
      g.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const rect = (e.currentTarget as Element).getBoundingClientRect();

      if (g.mode === "pinch" && g.pointers.size === 2) {
        const pts = Array.from(g.pointers.values());
        const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) || 1;
        const mid = (pts[0].x + pts[1].x) / 2;
        const factor = dist / g.pinchStartDist;
        const centerDomainX = pxToDomainValue(g.pinchStartMid, rect);
        const span = g.startDomain.max - g.startDomain.min;
        const newSpan = Math.min(Math.max(span / factor, minSpan), fullDomain.max - fullDomain.min);
        const frac = (centerDomainX - g.startDomain.min) / Math.max(span, 1e-9);
        // mid-drag between the two fingers also pans, same gesture.
        const midShiftPx = mid - g.pinchStartMid;
        const midShiftDomain = pxToDomainDelta(-midShiftPx);
        const min = centerDomainX - frac * newSpan + midShiftDomain;
        commit({ min, max: min + newSpan }, { settled: false });
        e.preventDefault();
        return;
      }

      if (g.mode === "pending") {
        const dx = e.clientX - g.startPointer.x;
        const dy = e.clientY - g.startPointer.y;
        if (Math.hypot(dx, dy) < DIRECTION_LOCK_THRESHOLD_PX) {
          setHoverX(pxToDomainValue(e.clientX, rect));
          return;
        }
        if (Math.abs(dx) > Math.abs(dy)) {
          g.mode = "pan";
          setIsPanning(true);
        } else {
          g.mode = "vertical-scroll";
          return; // let the page scroll natively — don't preventDefault, don't capture further
        }
      }

      if (g.mode === "pan") {
        const dx = e.clientX - g.startPointer.x;
        const delta = pxToDomainDelta(-dx);
        const span = g.startDomain.max - g.startDomain.min;
        commit({ min: g.startDomain.min + delta, max: g.startDomain.min + delta + span }, { settled: false });
        setHoverX(pxToDomainValue(e.clientX, rect));
        e.preventDefault();
      }
    },
    [disabled, commit, pxToDomainDelta, pxToDomainValue, minSpan, fullDomain],
  );

  const endGesture = useCallback(
    (e: React.PointerEvent) => {
      const g = gesture.current;
      const wasMode = g.mode;
      g.pointers.delete(e.pointerId);
      if (g.pointers.size === 0) {
        if (wasMode === "pan" || wasMode === "pinch") {
          onSettled?.(domainRef.current);
        } else if (wasMode === "pending") {
          const dx = e.clientX - g.startPointer.x;
          const dy = e.clientY - g.startPointer.y;
          if (Math.hypot(dx, dy) < TAP_MOVE_THRESHOLD_PX) {
            const now = performance.now();
            const isDoubleTap =
              now - g.lastTap.time < DOUBLE_TAP_MS && Math.abs(e.clientX - g.lastTap.x) < DOUBLE_TAP_DIST_PX;
            g.lastTap = { time: now, x: e.clientX };
            if (isDoubleTap) {
              onDoubleTap?.();
            } else {
              const rect = (e.currentTarget as Element).getBoundingClientRect();
              onTap?.(pxToDomainValue(e.clientX, rect), e.clientX, e.clientY);
            }
          }
        }
        g.mode = "idle";
        setIsPanning(false);
      } else if (g.pointers.size === 1) {
        // Pinch collapsed to one finger — restart as a fresh pan from here rather than jumping.
        const remaining = Array.from(g.pointers.entries())[0];
        g.mode = "pending";
        g.startPointer = { x: remaining[1].x, y: remaining[1].y };
        g.startDomain = domainRef.current;
      }
    },
    [onSettled, onTap, onDoubleTap, pxToDomainValue],
  );

  // A *native* listener, not React's onWheel prop: React registers its delegated wheel
  // listener as passive, so e.preventDefault() inside a JSX onWheel handler is silently
  // ignored (confirmed via Chrome's own "Unable to preventDefault inside passive event
  // listener invocation" warning) — ctrl/cmd+wheel would zoom the whole page right alongside
  // the chart instead of being claimed by it. {passive: false} here is what actually works.
  useEffect(() => {
    const el = surfaceRef.current;
    if (!el) return;
    const handler = (evt: Event) => {
      const e = evt as WheelEvent;
      if (disabled) return;
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const centerDomainX = pxToDomainValue(e.clientX, rect);
      const factor = Math.exp(-e.deltaY * 0.01);
      zoomAt(factor, centerDomainX);
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, [surfaceRef, disabled, pxToDomainValue, zoomAt]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (disabled) return;
      switch (e.key) {
        case "ArrowLeft":
          e.preventDefault();
          panBy(-0.1);
          break;
        case "ArrowRight":
          e.preventDefault();
          panBy(0.1);
          break;
        case "+":
        case "=":
          e.preventDefault();
          zoomIn();
          break;
        case "-":
        case "_":
          e.preventDefault();
          zoomOut();
          break;
        case "Home":
          e.preventDefault();
          commit({ min: fullDomain.min, max: fullDomain.min + (domainRef.current.max - domainRef.current.min) }, { settled: true });
          break;
        case "End":
          e.preventDefault();
          commit({ min: fullDomain.max - (domainRef.current.max - domainRef.current.min), max: fullDomain.max }, { settled: true });
          break;
        case "Escape":
          e.preventDefault();
          onDoubleTap?.();
          break;
      }
    },
    [disabled, panBy, zoomIn, zoomOut, commit, fullDomain, onDoubleTap],
  );

  const onDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      if (disabled) return;
      e.preventDefault();
      onDoubleTap?.();
    },
    [disabled, onDoubleTap],
  );

  // If the caller's fullDomain/minSpan genuinely change (new metric picked, more history
  // synced) and the current view no longer fits inside it, re-clamp rather than leaving a
  // stale/out-of-bounds window on screen.
  useEffect(() => {
    const clamped = clampDomain(domain, fullDomain, minSpan);
    if (clamped.min !== domain.min || clamped.max !== domain.max) onViewChange(clamped);
    // Only fullDomain/minSpan changing should re-trigger this — `domain` itself changing is
    // the caller's own pan/zoom, not a reason to re-run the clamp-and-notify check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullDomain.min, fullDomain.max, minSpan]);

  return useMemo(
    () => ({
      handlers: {
        onPointerDown,
        onPointerMove,
        onPointerUp: endGesture,
        onPointerCancel: endGesture,
        onKeyDown,
        onDoubleClick,
      },
      zoomIn,
      zoomOut,
      panBy,
      reset,
      hoverX,
      setHoverX,
      isPanning,
    }),
    [onPointerDown, onPointerMove, endGesture, onKeyDown, onDoubleClick, zoomIn, zoomOut, panBy, reset, hoverX, isPanning],
  );
}
