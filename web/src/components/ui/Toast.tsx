import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "../../lib/cn";

export type ToastTone = "success" | "error" | "info";
type ToastItem = { id: number; message: string; tone: ToastTone; action?: { label: string; onClick: () => void }; sticky?: boolean };
type ToastApi = { toast: (message: string, opts?: { tone?: ToastTone; action?: ToastItem["action"]; sticky?: boolean }) => number; dismiss: (id: number) => void };

const ToastContext = createContext<ToastApi | null>(null);
const GLYPH: Record<ToastTone, string> = { success: "✓", error: "✕", info: "●" };

/**
 * A small, dependency-free toast stack. Toasts sit above the bottom nav (`--shell-bottom`) on a phone and bottom-right on desktop,
 * announce through one polite `role="status"` region, and dismiss themselves after 4.5 s unless `sticky`.
 * Toasts confirm an action that has no visible result in place; an outcome a page already states inline stays inline.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);
  const toast = useCallback<ToastApi["toast"]>(
    (message, opts = {}) => {
      const id = next.current++;
      setItems((all) => [...all.slice(-2), { id, message, tone: opts.tone ?? "success", action: opts.action, sticky: opts.sticky }]);
      if (!opts.sticky) window.setTimeout(() => dismiss(id), 4500);
      return id;
    },
    [dismiss],
  );
  const api = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* A live region without role="status": it is always mounted (so announcements are heard), and an empty status role
          everywhere would collide with pages that look up their own status line. */}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 z-50 flex flex-col items-center gap-2 px-4 lg:inset-x-auto lg:right-6 lg:items-end"
        style={{ bottom: "calc(var(--shell-bottom) + 12px + env(safe-area-inset-bottom))" }}
      >
        {items.map((t) => (
          <div
            key={t.id}
            data-testid="toast"
            className={cn(
              "glass-primary glass-elevated pointer-events-auto flex max-w-[min(92vw,420px)] animate-enter items-center gap-3 rounded-full border bg-surface-3 py-2 pl-3 pr-2 text-sm text-text-primary shadow-float",
              t.tone === "error" ? "border-band-red/40" : "border-border-strong",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                t.tone === "error" ? "bg-band-red/15 text-band-red-text" : t.tone === "success" ? "bg-band-green/15 text-band-green" : "bg-accent-soft text-accent",
              )}
            >
              {GLYPH[t.tone]}
            </span>
            <span className="min-w-0">{t.message}</span>
            {t.action ? (
              <button
                type="button"
                onClick={() => {
                  t.action!.onClick();
                  dismiss(t.id);
                }}
                className="min-h-9 shrink-0 rounded-full bg-accent px-3 text-[13px] font-medium text-accent-contrast"
              >
                {t.action.label}
              </button>
            ) : (
              <button type="button" aria-label="Dismiss" onClick={() => dismiss(t.id)} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-text-tertiary hover:text-text-primary">
                ✕
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** `toast()` is a no-op outside the provider (e.g. a component rendered in isolation), never a crash. */
export function useToast(): ToastApi {
  return useContext(ToastContext) ?? { toast: () => 0, dismiss: () => {} };
}
