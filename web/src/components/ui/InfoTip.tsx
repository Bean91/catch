import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/**
 * The height at the bottom of the viewport taken by the tab bar: the web bar's `--shell-bottom` plus the bottom safe area. In the
 * iOS app the native tab bar's footprint arrives through the safe area alone (session 38), so both parts count. `env()` can only be
 * resolved by layout, hence the measured probe.
 */
function bottomReserve(): number {
  const probe = document.createElement("div");
  probe.style.cssText =
    "position:fixed;left:0;bottom:0;width:0;visibility:hidden;pointer-events:none;height:calc(var(--shell-bottom, 0px) + env(safe-area-inset-bottom, 0px))";
  document.body.appendChild(probe);
  const h = probe.getBoundingClientRect().height;
  probe.remove();
  return h;
}

/**
 * A small "?" that explains an unfamiliar metric. A tap or click toggles it (hover-only tooltips don't exist on a phone); Escape
 * and a tap elsewhere close it. The explanation is a real element referenced by `aria-describedby`, so it is read out too.
 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);
  // Placed after it renders, from its real size and where it actually landed. `position: fixed` is relative to the viewport only
  // when no ancestor has a transform; the page's route-change animation leaves one on <main>, as does a centred sheet, so the
  // popover's own offset from where it was asked to go is measured and taken off (before this, it opened off-screen on a scrolled
  // phone page and 240px to the right of its button on desktop). Below the button by default, above it when there isn't room
  // below — the phone's tab bar (--shell-bottom, 0 on desktop) counts as no room.
  useLayoutEffect(() => {
    const el = tipRef.current;
    if (!open || !anchor || !el) return;
    el.style.top = "0px";
    el.style.left = "0px";
    const origin = el.getBoundingClientRect();
    const shellBottom = bottomReserve();
    const left = Math.min(Math.max(8, anchor.left + anchor.width / 2 - origin.width / 2), window.innerWidth - origin.width - 8);
    const below = anchor.bottom + 8;
    const above = anchor.top - 8 - origin.height;
    const top = below + origin.height <= window.innerHeight - shellBottom - 8 || above < 8 ? below : above;
    el.style.top = `${top - origin.top}px`;
    el.style.left = `${left - origin.left}px`;
  }, [open, anchor]);
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
          setAnchor((e.currentTarget as HTMLElement).getBoundingClientRect());
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
          ref={tipRef}
          className="glass-primary glass-elevated glass-dense fixed z-40 w-64 transition-none max-w-[calc(100vw-16px)] animate-fade rounded-md border border-border-strong bg-surface-3 p-3 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-text-secondary shadow-float"
        >
          {children}
        </span>
      )}
    </span>
  );
}
