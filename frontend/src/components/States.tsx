/** Shared loading / empty / error state components. */
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { Button } from "./Button";
import { AlertIcon, RefreshIcon } from "./Icons";

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  children,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center animate-fade-in">
      {icon ? (
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-50 text-2xl text-primary">
          {icon}
        </div>
      ) : null}
      <h3 className="text-lg font-semibold text-ink">{title}</h3>
      {description ? <p className="mt-1.5 max-w-md text-sm text-ink-muted">{description}</p> : null}
      {children}
      {action ? <div className="mt-6">{action}</div> : null}
    </div>
  );
}

export function errorMessage(err: unknown, fallback = "Something went wrong. Please try again."): string {
  if (err instanceof ApiError) {
    if (err.isNetwork) return "We couldn't reach the server. Check your connection and try again.";
    if (err.code === "RATE_LIMITED") return "Too many requests. Please wait a minute and try again.";
    return err.message || fallback;
  }
  return fallback;
}

export function ErrorState({ error, onRetry, title = "Something went wrong" }: { error: unknown; onRetry?: () => void; title?: string }) {
  return (
    <div role="alert" className="flex flex-col items-center px-6 py-10 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-danger-soft text-xl text-danger">
        <AlertIcon />
      </div>
      <h3 className="font-semibold text-ink">{title}</h3>
      <p className="mt-1 max-w-md text-sm text-ink-muted">{errorMessage(error)}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" className="mt-4" icon={<RefreshIcon />} onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

type Tone = "info" | "success" | "warning" | "danger";
const ALERT_TONES: Record<Tone, string> = {
  info: "bg-primary-50 text-primary-800 border-primary-100",
  success: "bg-success-soft text-success border-success/20",
  warning: "bg-warning-soft text-warning border-warning/20",
  danger: "bg-danger-soft text-danger border-danger/20",
};

export function Alert({ tone = "info", children, icon }: { tone?: Tone; children: ReactNode; icon?: ReactNode }) {
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : "status"}
      className={`flex gap-3 rounded-2xl border px-4 py-3 text-sm ${ALERT_TONES[tone]}`}
    >
      {icon ? <span className="mt-0.5 shrink-0 text-base">{icon}</span> : null}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

const BADGE_TONES = {
  neutral: "bg-line text-ink-muted",
  primary: "bg-primary-50 text-primary-700",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
} as const;

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof BADGE_TONES; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE_TONES[tone]}`}>
      {children}
    </span>
  );
}

export function ProgressBar({ value, label, tone = "primary" }: { value: number; label: string; tone?: "primary" | "success" }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className="h-2 w-full overflow-hidden rounded-full bg-line"
    >
      <div
        className={`h-full rounded-full transition-[width] duration-300 ${tone === "success" ? "bg-success" : "bg-primary"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
