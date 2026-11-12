import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App.tsx";
import { UpdateToast } from "./components/shell/UpdateToast.tsx";
import "./index.css";
import { AuthProvider } from "./lib/auth.tsx";
import { SESSION_ENDED_EVENT } from "./lib/session.ts";
import { ThemeProvider } from "./lib/theme.tsx";

const queryClient = new QueryClient({
  // offlineFirst (not the v5 default "online"): a query still tries the network first, but
  // doesn't *pause* when the browser is offline — it runs, lets fetch() fail, and the service
  // worker's cached /api/today response (or ApiError) resolves it instead of spinning forever.
  defaultOptions: { queries: { retry: 1, staleTime: 30_000, networkMode: "offlineFirst" } },
});

// Sign-out / user switch (public build): nothing the previous person loaded may stay in memory for the next one.
window.addEventListener(SESSION_ENDED_EVENT, () => queryClient.clear());

// Belt #3 (after the viewport meta and CSS touch-action) against page-level pinch-zoom: iOS
// Safari's gesturestart/gesturechange/gestureend fire even with user-scalable=no in a plain
// browser tab, and a two-finger touchmove can still zoom unless preventDefault'd. Unlike
// session 8's original version, this is now unconditional everywhere, including over a chart
// — a chart's own pinch-to-zoom runs entirely on Pointer Events against a `touch-action: none`
// HTML element (see useChartInteraction.ts / DESIGN.md's "Chart touch-action" note), never on
// these legacy gesture events, so blocking the legacy events globally can't take anything away
// from a chart's pinch; it only stops Safari's native page-zoom from ever engaging, which it
// would otherwise still try to do concurrently with a chart's own pinch handling. touchmove's
// listener must be { passive: false }, or preventDefault is silently ignored.
document.addEventListener("gesturestart", (e) => e.preventDefault(), { passive: false });
document.addEventListener("gesturechange", (e) => e.preventDefault(), { passive: false });
document.addEventListener("gestureend", (e) => e.preventDefault());
document.addEventListener(
  "touchmove",
  (e) => {
    if (e.touches.length > 1) e.preventDefault();
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
      {/* Outside AuthProvider/App's routes on purpose — see UpdateToast.tsx's own comment. */}
      <UpdateToast />
    </QueryClientProvider>
  </StrictMode>,
);
