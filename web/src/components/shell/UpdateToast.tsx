import { useServiceWorkerUpdate } from "../../lib/useServiceWorkerUpdate";

// Mounted once at the root (main.tsx), outside AppShell/the auth gate — a user stuck on the
// login screen on a stale build should still be able to see and accept an update.
export function UpdateToast() {
  const { updateAvailable, reload } = useServiceWorkerUpdate();
  if (!updateAvailable) return null;
  return (
    <button
      type="button"
      onClick={reload}
      className="glass-primary glass-elevated fixed inset-x-0 z-50 mx-auto flex w-fit animate-enter items-center gap-2.5 rounded-full border border-accent/40 bg-surface-3 px-4 py-2.5 text-sm font-medium text-text-primary shadow-float transition-colors hover:border-accent lg:bottom-6"
      style={{ touchAction: "manipulation", bottom: "calc(var(--shell-bottom) + 12px + env(safe-area-inset-bottom))" }}
    >
      <span aria-hidden className="h-2 w-2 rounded-full bg-accent shadow-[0_0_0_4px_var(--accent-soft)]" />
      New version — tap to reload
    </button>
  );
}
