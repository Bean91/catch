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
      className="fixed inset-x-0 bottom-[calc(5.5rem+env(safe-area-inset-bottom))] z-50 mx-auto flex w-fit items-center gap-2 rounded-full border border-accent/50 bg-surface px-4 py-2.5 text-sm font-medium text-text-primary shadow-lg transition-colors hover:border-accent lg:bottom-6"
      style={{ touchAction: "manipulation" }}
    >
      <span className="h-2 w-2 rounded-full bg-accent" />
      New version available — tap to reload
    </button>
  );
}
