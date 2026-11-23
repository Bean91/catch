import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

/** Every text box, select and textarea shares this surface, border and focus ring (the ring itself is in index.css). */
/** Without a width — for a control sized by its row (a date, a unit select, a short number). */
export const controlBase =
  "min-h-11 min-w-0 rounded-md border border-border bg-surface-2 px-3 text-base text-text-primary transition-colors placeholder:text-text-tertiary hover:border-border-strong disabled:opacity-50";
export const controlClass = `${controlBase} w-full`;

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn(controlClass, className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn(controlClass, "py-2.5", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, ...rest }, ref) {
  return <select ref={ref} className={cn(controlClass, "pr-8", className)} {...rest} />;
});

/** A labelled control: the label wraps the control (so it is its accessible name), with an optional hint and error line. */
export function Field({ label, hint, error, children, className }: { label: ReactNode; hint?: ReactNode; error?: string | null; children: ReactNode; className?: string }) {
  return (
    <label className={cn("flex min-w-0 flex-col gap-1.5 text-sm", className)}>
      <span className="font-medium text-text-primary">{label}</span>
      {children}
      {hint && <span className="text-xs text-text-tertiary">{hint}</span>}
      {error && (
        <span role="alert" className="text-xs text-band-red-text">
          {error}
        </span>
      )}
    </label>
  );
}

/** For a group of controls that a single <label> can't wrap (radios, a row of inputs). */
export function FieldGroup({ legend, hint, children, className }: { legend: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className={cn("flex min-w-0 flex-col gap-1.5 text-sm", className)}>
      <span id={id} className="font-medium text-text-primary">
        {legend}
      </span>
      {children}
      {hint && <span className="text-xs text-text-tertiary">{hint}</span>}
    </div>
  );
}
