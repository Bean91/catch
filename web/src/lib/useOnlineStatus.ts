import { useQuery } from "@tanstack/react-query";
import { useRef } from "react";
import { MOCK_SCENARIO, isMock } from "./api";

const PROBE_TIMEOUT_MS = 4_000;
const PROBE_INTERVAL_MS = 15_000;
// A single slow/stalled request (e.g. a sync job briefly pegging the Pi 3's one CPU core)
// shouldn't flip the banner on its own — that's the same complaint this fix exists for, just
// moved from a bad signal to a flaky one. Two consecutive failures in a row before reporting
// offline.
const FAILURES_BEFORE_OFFLINE = 2;

// `navigator.onLine` only reflects whether the device has *a* network interface up — it's
// true on a LAN with no route to the Pi, true behind a captive portal, true with Wi-Fi on but
// the Pi itself powered off. The only honest signal is whether a request to the Pi actually
// completes, so this probes /api/health directly rather than trusting the browser's flag.
// `navigator.onLine` going false is still a useful trigger to re-probe immediately (handled by
// TanStack Query's own online-manager via `refetchOnReconnect`), just never the answer itself.
async function probeHealth(): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    // Any response that actually arrives — even a 5xx — means the network path to the Pi
    // works; only a rejected fetch (DNS/connection failure, abort on timeout) means offline.
    // The service worker routes /api/health network-only with no cache fallback (vite.config.ts)
    // specifically so this can never be answered by a stale cached "ok" while truly offline.
    await fetch("/api/health", { cache: "no-store", signal: controller.signal });
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export function useOnlineStatus(): boolean {
  const consecutiveFailures = useRef(0);

  const { data } = useQuery({
    queryKey: ["health-probe"],
    // The consecutive-failure debounce below is specifically for real network flakiness
    // (a slow request, not a real outage) — ?mock=offline is a deterministic scenario, not
    // network flakiness, so it reports immediately rather than waiting out two poll intervals.
    queryFn: isMock
      ? async () => MOCK_SCENARIO !== "offline"
      : async () => {
          const healthy = await probeHealth();
          consecutiveFailures.current = healthy ? 0 : consecutiveFailures.current + 1;
          return consecutiveFailures.current < FAILURES_BEFORE_OFFLINE;
        },
    refetchInterval: PROBE_INTERVAL_MS,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    networkMode: "always",
    retry: false,
    staleTime: 0,
    // Assume online until the first probe resolves — avoids a false banner flash on load.
    initialData: true,
  });
  return data ?? true;
}
