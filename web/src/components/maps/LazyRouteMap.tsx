import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import type { MapLine } from "./RouteMap";

// Leaflet and its stylesheet live in this dynamic chunk, fetched only when the map is about to
// scroll into view — never in the initial bundle (scripts/check-bundle-size.mjs counts only
// eager chunks) and never on a page with no GPS card.
const RouteMap = lazy(() => import("./RouteMap"));

function Placeholder({ height, text }: { height: number; text: string }) {
  return (
    <div className="flex items-center justify-center rounded-md border border-border bg-surface-2 px-4 text-center text-sm text-text-tertiary" style={{ height }}>
      {text}
    </div>
  );
}

class MapBoundary extends Component<{ height: number; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed) return <Placeholder height={this.props.height} text="The map couldn't load (offline?). The numbers below are unaffected." />;
    return this.props.children;
  }
}

export function LazyRouteMap({
  lines,
  speedRange,
  hover,
  height = 320,
  label,
}: {
  lines: MapLine[];
  speedRange?: [number, number] | null;
  hover?: { lat: number; lon: number } | null;
  height?: number;
  label?: string;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: "400px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={wrapRef} data-testid="lazy-route-map">
      {near ? (
        <MapBoundary height={height}>
          <Suspense fallback={<Placeholder height={height} text="Loading map…" />}>
            <RouteMap lines={lines} speedRange={speedRange} hover={hover} height={height} label={label} />
          </Suspense>
        </MapBoundary>
      ) : (
        <Placeholder height={height} text="The map loads as it scrolls into view." />
      )}
    </div>
  );
}
