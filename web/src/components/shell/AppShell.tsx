import type { ReactNode } from "react";
import { useAuth } from "../../lib/auth";
import { useTheme } from "../../lib/theme";
import { BottomNav } from "./BottomNav";
import { Sidebar } from "./Sidebar";
import { LogoutIcon, MoonIcon, SunIcon } from "./icons";

export function AppShell({ children }: { children: ReactNode }) {
  const { theme, toggle } = useTheme();
  const { logout, status } = useAuth();

  return (
    <div className="flex min-h-screen bg-bg text-text-primary">
      <Sidebar />

      <div className="flex min-h-screen flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-4 py-3 sm:px-6 lg:hidden">
          <span className="font-mono-nums text-sm font-semibold tracking-wide text-text-primary">CATCH</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={toggle}
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              className="flex h-11 w-11 items-center justify-center rounded-md text-text-secondary transition-colors hover:text-text-primary"
            >
              {theme === "dark" ? <SunIcon className="h-5 w-5" /> : <MoonIcon className="h-5 w-5" />}
            </button>
            {status === "authed" && (
              <button
                type="button"
                onClick={() => logout()}
                aria-label="Log out"
                className="flex h-11 w-11 items-center justify-center gap-1.5 rounded-md text-text-secondary transition-colors hover:text-text-primary"
              >
                <LogoutIcon className="h-5 w-5" />
              </button>
            )}
          </div>
        </header>

        <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-24 pt-5 sm:px-6 sm:pb-10 lg:max-w-5xl lg:px-8 lg:pb-10 lg:pt-8">
          {children}
        </main>

        <div className="lg:hidden">
          <BottomNav />
        </div>
      </div>
    </div>
  );
}
