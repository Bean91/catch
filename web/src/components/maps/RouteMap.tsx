import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./RouteMap.css";
import { useEffect, useRef, useState } from "react";
import { TILE_ATTRIBUTION, TILE_MAX_ZOOM, TILE_URL } from "../../lib/mapConfig";

export interface MapSegment {
  coords: [number, number][];
  /** One speed (m/s) per coord, for the speed ramp. Omit for a plain line. */
  speeds?: number[];
}

export interface MapLine {
  id: string;
  segments: MapSegment[];
  weight?: number;
  opacity?: number;
  dashed?: boolean;
  /** Draw start/finish markers on this line (usually only the primary one). */
  endpoints?: boolean;
}

const BUCKETS = 6;

function accentColor(): string {
  return getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#a79cff";
}

/** Speed is shown by opacity *and* weight (never colour alone — DESIGN.md), all in the one
 * accent hue: slow = thin and faint, fast = thick and solid. */
function bucketStyle(i: number): { weight: number; opacity: number } {
  const f = i / (BUCKETS - 1);
  return { weight: 3 + f * 3, opacity: 0.35 + f * 0.65 };
}

export default function RouteMap({
  lines,
  speedRange,
  hover,
  height = 320,
  label = "Route map",
}: {
  lines: MapLine[];
  speedRange?: [number, number] | null;
  hover?: { lat: number; lon: number } | null;
  height?: number;
  label?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const hoverRef = useRef<L.CircleMarker | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const hintTimer = useRef<number | undefined>(undefined);

  const flashHint = (text: string) => {
    setHint(text);
    window.clearTimeout(hintTimer.current);
    hintTimer.current = window.setTimeout(() => setHint(null), 1600);
  };

  // Map lifetime. Gesture policy (the map must never trap page scroll): a coarse pointer gets
  // two-finger pan/zoom only, so a one-finger swipe scrolls the page; a mouse can drag, but the
  // wheel zooms only with ctrl/cmd held (which is also what a trackpad pinch sends).
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    const map = L.map(host, {
      zoomControl: true,
      scrollWheelZoom: false,
      dragging: !coarse,
      touchZoom: true,
      doubleClickZoom: !coarse,
      boxZoom: false,
      zoomSnap: 0.5,
      attributionControl: true,
    });
    map.getContainer().classList.add("catch-map");
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: TILE_MAX_ZOOM }).addTo(map);
    map.setView([0, 0], 2);
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    // Mirrored onto the element so gesture tests can assert zoom/pan really happened.
    const publish = () => {
      const c = map.getCenter();
      host.dataset.zoom = String(map.getZoom());
      host.dataset.center = `${c.lat.toFixed(5)},${c.lng.toFixed(5)}`;
    };
    map.on("zoomend moveend", publish);
    publish();

    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) {
        flashHint("Hold Ctrl (⌘) and scroll to zoom the map");
        return;
      }
      e.preventDefault();
      map.setZoom(map.getZoom() + (e.deltaY < 0 ? 0.5 : -0.5));
    };
    host.addEventListener("wheel", onWheel, { passive: false });

    let startY = 0;
    let startX = 0;
    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 1) {
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
      }
    };
    const onTouchMove = (e: TouchEvent) => {
      if (coarse && e.touches.length === 1 && Math.hypot(e.touches[0].clientX - startX, e.touches[0].clientY - startY) > 12) {
        flashHint("Use two fingers to move the map");
      }
    };
    host.addEventListener("touchstart", onTouchStart, { passive: true });
    host.addEventListener("touchmove", onTouchMove, { passive: true });

    return () => {
      host.removeEventListener("wheel", onWheel);
      host.removeEventListener("touchstart", onTouchStart);
      host.removeEventListener("touchmove", onTouchMove);
      window.clearTimeout(hintTimer.current);
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
      hoverRef.current = null;
    };
  }, []);

  // Redraw lines whenever they change.
  useEffect(() => {
    const map = mapRef.current;
    const group = layerRef.current;
    if (!map || !group) return;
    group.clearLayers();
    hoverRef.current = null;
    const color = accentColor();
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim() || "#0d0f11";
    const all: L.LatLngTuple[] = [];

    for (const line of lines) {
      for (const seg of line.segments) {
        seg.coords.forEach((c) => all.push(c));
        const base = { color, weight: line.weight ?? 4, opacity: line.opacity ?? 0.9, dashArray: line.dashed ? "6 6" : undefined, lineJoin: "round" as const, lineCap: "round" as const };
        if (seg.speeds && speedRange && seg.speeds.length === seg.coords.length && speedRange[1] > speedRange[0]) {
          const [lo, hi] = speedRange;
          const bucket = (v: number) => Math.max(0, Math.min(BUCKETS - 1, Math.floor(((v - lo) / (hi - lo)) * BUCKETS)));
          let run: L.LatLngTuple[] = [seg.coords[0]];
          let runBucket = bucket(seg.speeds[1] ?? seg.speeds[0]);
          for (let i = 1; i < seg.coords.length; i++) {
            const b = bucket(seg.speeds[i]);
            run.push(seg.coords[i]);
            if (b !== runBucket) {
              L.polyline(run, { ...base, ...bucketStyle(runBucket) }).addTo(group);
              run = [seg.coords[i]];
              runBucket = b;
            }
          }
          if (run.length > 1) L.polyline(run, { ...base, ...bucketStyle(runBucket) }).addTo(group);
        } else if (seg.coords.length > 1) {
          L.polyline(seg.coords, base).addTo(group);
        }
      }
      if (line.endpoints && line.segments.length) {
        const first = line.segments[0].coords[0];
        const lastSeg = line.segments[line.segments.length - 1].coords;
        const last = lastSeg[lastSeg.length - 1];
        // A loop starts where it finishes: the start is a larger ring drawn first and the finish a
        // smaller solid dot on top, so both stay visible when they coincide.
        L.circleMarker(first, { radius: 11, weight: 3, color, fillColor: bg, fillOpacity: 1 }).bindTooltip("Start").addTo(group);
        L.circleMarker(last, { radius: 5, weight: 2, color, fillColor: color, fillOpacity: 1 }).bindTooltip("Finish").addTo(group);
      }
    }
    if (all.length) map.fitBounds(L.latLngBounds(all), { padding: [24, 24], animate: false });
  }, [lines, speedRange]);

  // The hover marker follows the chart's crosshair.
  useEffect(() => {
    const map = mapRef.current;
    const group = layerRef.current;
    if (!map || !group) return;
    if (!hover) {
      hoverRef.current?.remove();
      hoverRef.current = null;
      return;
    }
    if (!hoverRef.current) {
      hoverRef.current = L.circleMarker([hover.lat, hover.lon], { radius: 8, weight: 3, color: accentColor(), fillColor: "#fff", fillOpacity: 1, interactive: false }).addTo(group);
    } else {
      hoverRef.current.setLatLng([hover.lat, hover.lon]);
    }
  }, [hover]);

  return (
    <div className="relative" style={{ height }}>
      <div ref={hostRef} role="application" aria-label={label} data-testid="route-map" className="h-full w-full rounded-md" />
      {hint && (
        <div
          role="status"
          data-testid="map-hint"
          className="pointer-events-none absolute inset-x-0 top-1/2 z-[1000] mx-auto w-fit -translate-y-1/2 rounded-md bg-bg/85 px-3 py-2 text-sm text-text-primary shadow"
        >
          {hint}
        </div>
      )}
    </div>
  );
}
