import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/**
 * A small "?" that explains an unfamiliar metric. A tap or click toggles it (hover-only tooltips don't exist on a phone); Escape
 * and a tap elsewhere close it. The explanation is a real element referenced by `aria-describedby`, so it is read out too.
 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <span ref={ref} className="relative inline-flex">
      <button
        type="button"
        aria-label={`About ${label}`}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          // Fixed, clamped to the viewport: an absolutely positioned popover near a phone's edge would widen the page.
          const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
          const w = Math.min(256, window.innerWidth - 16);
          setPos({ top: r.bottom + 8, left: Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8) });
          setOpen((v) => !v);
        }}
        className="relative inline-flex h-4 w-4 items-center justify-center rounded-full border border-border-strong text-[10px] font-semibold leading-none text-text-tertiary transition-colors before:absolute before:-inset-3 before:content-[''] hover:border-accent hover:text-accent"
      >
        ?
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          style={pos ? { top: pos.top, left: pos.left } : undefined}
          className="fixed z-40 w-64 max-w-[calc(100vw-16px)] animate-fade rounded-md border border-border-strong bg-surface-3 p-3 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-text-secondary shadow-float"
        >
          {children}
        </span>
      )}
    </span>
  );
}
