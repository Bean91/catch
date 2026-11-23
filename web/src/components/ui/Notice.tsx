import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

export type NoticeTone = "info" | "accent" | "warn" | "error" | "success";

const TONE: Record<NoticeTone, { box: string; glyph: string }> = {
  info: { box: "border-border bg-surface-2 text-text-secondary", glyph: "i" },
  accent: { box: "border-accent/30 bg-accent-soft text-text-primary", glyph: "◆" },
  warn: { box: "border-band-yellow/35 bg-band-yellow/10 text-text-primary", glyph: "!" },
  error: { box: "border-band-red/35 bg-band-red/10 text-band-red-text", glyph: "✕" },
  success: { box: "border-band-green/35 bg-band-green/10 text-text-primary", glyph: "✓" },
};

/**
 * A callout line or block. The glyph is decorative (`aria-hidden`); the words carry the meaning. Pass `role="alert"` for errors a
 * person just caused, `role="status"` for outcomes; leave it off for standing information.
 */
export function Notice({
  tone = "info",
  title,
  children,
  action,
  role,
  testId,
  className,
}: {
  tone?: NoticeTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  role?: "alert" | "status";
  testId?: string;
  className?: string;
}) {
  const t = TONE[tone];
  return (
    <div role={role} data-testid={testId} className={cn("flex min-w-0 items-start gap-3 rounded-md border px-3.5 py-3 text-sm", t.box, className)}>
      <span aria-hidden className="mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-current/10 font-mono-nums text-[11px] font-semibold">
        {t.glyph}
      </span>
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium text-text-primary">{title}</p>}
        {children && <div className={title ? "mt-0.5" : undefined}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
