import * as Dialog from "@radix-ui/react-dialog";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cn } from "../../lib/cn";
import { NativeModalMarker } from "../../lib/native/nativeModal";

export type SheetWidth = "sm" | "md" | "lg" | "xl";

const WIDTH: Record<SheetWidth, string> = {
  sm: "sm:w-[min(92vw,420px)]",
  md: "sm:w-[min(92vw,480px)]",
  lg: "sm:w-[min(92vw,560px)]",
  xl: "sm:w-[min(94vw,680px)]",
};

export const overlayClass = "glass-overlay fixed inset-0 z-30 bg-overlay backdrop-blur-[2px] animate-fade";

type ContentProps = ComponentPropsWithoutRef<typeof Dialog.Content> & { width?: SheetWidth; children: ReactNode };

/**
 * A bottom sheet on a phone, a centred dialog from `sm:` (DESIGN.md "Sheets"): z-30 so it clears the fixed bottom nav, capped at
 * 90dvh with its bottom padded for the home indicator, and no autofocus (iOS would open a date picker or the keyboard on open).
 * Drop-in for a `Dialog.Portal` + `Dialog.Overlay` + `Dialog.Content` trio inside an existing `Dialog.Root`.
 */
export function SheetContent({ width = "md", className, children, onOpenAutoFocus, ...rest }: ContentProps) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay className={overlayClass} />
      <Dialog.Content
        onOpenAutoFocus={onOpenAutoFocus ?? ((e) => e.preventDefault())}
        className={cn(
          "glass-primary glass-dense glass-sheet fixed inset-x-0 bottom-0 z-30 max-h-[90dvh] overflow-y-auto overscroll-contain rounded-t-2xl border-t border-border bg-surface p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-float animate-sheet-up focus:outline-none",
          "sm:inset-x-auto sm:bottom-auto sm:left-1/2 sm:top-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl sm:border sm:animate-fade",
          WIDTH[width],
          className,
        )}
        {...rest}
      >
        <NativeModalMarker />
        <div aria-hidden className="mx-auto -mt-2 mb-3 h-1 w-10 rounded-full bg-border-strong sm:hidden" />
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  );
}

/** A centred dialog at every width (detail views, pickers). Same z-30 rule. */
export function ModalContent({ width = "md", className, children, onOpenAutoFocus, ...rest }: ContentProps) {
  return (
    <Dialog.Portal>
      <Dialog.Overlay className={overlayClass} />
      <Dialog.Content
        onOpenAutoFocus={onOpenAutoFocus}
        className={cn(
          "glass-primary glass-dense glass-modal fixed left-1/2 top-1/2 z-30 max-h-[85dvh] w-[min(92vw,480px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto overscroll-contain rounded-xl border border-border bg-surface p-5 shadow-float animate-fade focus:outline-none",
          WIDTH[width].replace("sm:", ""),
          className,
        )}
        {...rest}
      >
        <NativeModalMarker />
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  );
}

export function SheetHeader({ title, description, onClose }: { title: ReactNode; description?: ReactNode; onClose?: boolean }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <Dialog.Title className="text-lg font-semibold text-text-primary">{title}</Dialog.Title>
        {description ? (
          <Dialog.Description className="mt-1 text-sm text-text-secondary">{description}</Dialog.Description>
        ) : (
          <Dialog.Description className="sr-only">{typeof title === "string" ? title : ""}</Dialog.Description>
        )}
      </div>
      {onClose && (
        <Dialog.Close aria-label="Close" className="-mr-2 -mt-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-text-tertiary transition-colors hover:bg-surface-2 hover:text-text-primary">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden>
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </Dialog.Close>
      )}
    </div>
  );
}

type SheetProps = { open: boolean; onOpenChange: (open: boolean) => void; title: ReactNode; description?: ReactNode; testId?: string; width?: SheetWidth; children: ReactNode };

/** The whole thing in one: Root + SheetContent + a title/description header + a column of children. */
export function Sheet({ open, onOpenChange, title, description, testId, width, children }: SheetProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <SheetContent width={width} data-testid={testId}>
        <SheetHeader title={title} description={description} />
        <div className="flex flex-col gap-3">{children}</div>
      </SheetContent>
    </Dialog.Root>
  );
}
