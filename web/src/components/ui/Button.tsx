import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { cn } from "../../lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
export type ButtonSize = "md" | "sm";

const BASE =
  "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-[background-color,border-color,color,transform,box-shadow] duration-150 ease-out active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 aria-disabled:pointer-events-none aria-disabled:opacity-45";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-contrast shadow-subtle hover:bg-accent-strong",
  secondary: "border border-border bg-surface-2 text-text-primary hover:border-border-strong hover:bg-surface-3",
  subtle: "bg-accent-soft text-accent hover:bg-accent/20",
  ghost: "text-text-secondary hover:bg-surface-2 hover:text-text-primary",
  danger: "border border-band-red/40 bg-band-red/10 text-band-red-text hover:bg-band-red/15",
};

const SIZE: Record<ButtonSize, string> = {
  md: "min-h-11 px-4 text-sm",
  sm: "min-h-9 px-3 text-[13px]",
};

export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", className?: string) {
  return cn(BASE, VARIANT[variant], SIZE[size], className);
}

function Spinner() {
  return <span aria-hidden className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" />;
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
};

/** The one button. `loading` keeps the label (so the width doesn't jump) and adds a spinner; it also disables. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, icon, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} disabled={disabled || loading} aria-busy={loading || undefined} className={buttonClass(variant, size, className)} {...rest}>
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
});

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { label: string; variant?: "ghost" | "secondary"; children: ReactNode };

/** A 44px square icon button; `label` is its accessible name. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, variant = "ghost", className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      className={cn(
        "inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md transition-colors duration-150 disabled:opacity-45",
        variant === "ghost" ? "text-text-secondary hover:bg-surface-2 hover:text-text-primary" : "border border-border bg-surface-2 text-text-primary hover:bg-surface-3",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});

/** A router link that looks like a button. */
export function ButtonLink({ variant = "secondary", size = "md", className, ...rest }: LinkProps & { variant?: ButtonVariant; size?: ButtonSize }) {
  return <Link className={buttonClass(variant, size, className)} {...rest} />;
}
