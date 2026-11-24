import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { BottomNav } from "./BottomNav";
import { GarminKeyBanner } from "./GarminKeyBanner";
import { Sidebar } from "./Sidebar";
import { Logomark, SettingsIcon } from "./icons";

export function AppShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();

  return (
    <div className="flex min-h-dvh text-text-primary">
      <Sidebar />

      {/* min-w-0: a flex item's default min-width is "auto" (shrink-to-fit its content's
          intrinsic minimum), so a wide-but-horizontally-scrollable table nested deep inside
          (e.g. the Settings zones table, or the workout-detail interval table) would
          otherwise bubble its min-content width up through every flex ancestor and stretch
          the whole page past the viewport instead of just scrolling within its own card. */}
      {/* paddingTop here (not just on <header>) so whichever element renders first — the
          header, or the Garmin-key banner above it when that's showing — clears the status
          bar/notch on an iPhone (viewport-fit=cover in index.html draws edge-to-edge). */}
      <div className="flex min-h-dvh min-w-0 flex-1 flex-col">
        {/* The safe-area padding belongs to the sticky bar itself: with the status bar drawn over the web view (native, and an
            installed iPhone PWA), a sticky bar without it scrolls content up behind the clock and battery. */}
        <div className="glass-primary glass-bar sticky top-0 z-10 bg-bg/95 backdrop-blur-lg lg:static lg:bg-transparent lg:backdrop-blur-none" style={{ paddingTop: "env(safe-area-inset-top)" }}>
        <GarminKeyBanner />

        {/* Phone and tablet top bar. Its height (and the tab bar's) are --shell-top/--shell-bottom in index.css; Coach sizes its
            conversation from them, so change both together. */}
        <header className="flex h-[var(--shell-top)] items-center justify-between border-b border-border/70 px-4 sm:px-6 lg:hidden">
          <Link to="/" className="flex min-h-11 items-center gap-2" aria-label="Catch — Today">
            <Logomark className="h-7 w-7" />
            <span className="text-sm font-semibold tracking-[0.14em] text-text-primary">CATCH</span>
          </Link>
          <Link
            to="/settings"
            aria-label="Settings"
            className="glass-press flex h-11 w-11 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary"
          >
            <SettingsIcon className="h-5 w-5" />
          </Link>
        </header>
        </div>

        <main
          key={pathname}
          className="page-enter mx-auto w-full min-w-0 max-w-3xl flex-1 px-4 pt-5 pb-[calc(var(--shell-bottom)+2rem+env(safe-area-inset-bottom))] sm:px-6 lg:max-w-5xl lg:px-8 lg:pb-12 lg:pt-8 xl:max-w-6xl"
        >
          {children}
        </main>

        <div className="lg:hidden">
          <BottomNav />
        </div>
      </div>
    </div>
  );
}
