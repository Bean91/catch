import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App.tsx";
import "./index.css";
import { AuthProvider } from "./lib/auth.tsx";
import { ThemeProvider } from "./lib/theme.tsx";

const queryClient = new QueryClient({
  // offlineFirst (not the v5 default "online"): a query still tries the network first, but
  // doesn't *pause* when the browser is offline — it runs, lets fetch() fail, and the service
  // worker's cached /api/today response (or ApiError) resolves it instead of spinning forever.
  defaultOptions: { queries: { retry: 1, staleTime: 30_000, networkMode: "offlineFirst" } },
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Dev server / HTTP-without-TLS / no SW support — offline caching just doesn't apply.
    });
  });
}

// Belt #3 (after the viewport meta and CSS touch-action) against page-level pinch-zoom: iOS
// Safari's gesturestart/gesturechange/gestureend fire even with user-scalable=no in a plain
// browser tab, and a two-finger touchmove can still zoom unless preventDefault'd — but only
// outside a chart surface, which sets its own touch-action and runs useChartInteraction's
// pinch handling instead. touchmove's listener must be { passive: false }, or preventDefault
// is silently ignored.
function isInsideChart(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest('[data-chart-surface="true"]') != null;
}

document.addEventListener(
  "gesturestart",
  (e) => {
    if (!isInsideChart(e.target)) e.preventDefault();
  },
  { passive: false },
);
document.addEventListener(
  "gesturechange",
  (e) => {
    if (!isInsideChart(e.target)) e.preventDefault();
  },
  { passive: false },
);
document.addEventListener("gestureend", (e) => {
  if (!isInsideChart(e.target)) e.preventDefault();
});
document.addEventListener(
  "touchmove",
  (e) => {
    if (e.touches.length > 1 && !isInsideChart(e.target)) e.preventDefault();
  },
  { passive: false },
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
