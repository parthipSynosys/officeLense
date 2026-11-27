import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "soft";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-white shadow-glow hover:bg-primary-700 active:bg-primary-800 disabled:shadow-none",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-background active:bg-line",
  soft: "bg-primary-50 text-primary-700 hover:bg-primary-100 active:bg-primary-200",
  ghost: "text-ink-muted hover:bg-line/60 hover:text-ink",
  danger: "bg-danger text-white hover:opacity-90 active:opacity-80",
};

const SIZES: Record<Size, string> = {
  sm: "h-9 px-3 text-sm gap-1.5 rounded-xl",
  md: "h-11 px-4 text-sm gap-2 rounded-xl",
  lg: "h-14 px-6 text-base gap-2.5 rounded-2xl",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
  fullWidth?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, icon, fullWidth, className = "", children, disabled, type, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type ?? "button"}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={[
        "inline-flex select-none items-center justify-center font-semibold transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        fullWidth ? "w-full" : "",
        className,
      ].join(" ")}
      {...rest}
    >
      {loading ? <Spinner className="h-4 w-4" /> : icon ? <span className="text-[1.15em]">{icon}</span> : null}
      {children}
    </button>
  );
});
