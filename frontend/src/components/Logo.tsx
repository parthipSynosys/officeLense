import { Link } from "react-router-dom";

export function Logo({ to = "/", subtitle }: { to?: string; subtitle?: string }) {
  return (
    <Link to={to} className="inline-flex items-center gap-2.5 rounded-xl" aria-label="EventLens home">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-white shadow-glow">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
          <circle cx="12" cy="13" r="5" />
          <circle cx="12" cy="13" r="1.6" fill="currentColor" stroke="none" />
          <path d="M8.5 5h7" strokeLinecap="round" />
        </svg>
      </span>
      <span className="flex flex-col leading-none">
        <span className="text-base font-bold tracking-tight text-ink">EventLens</span>
        {subtitle ? <span className="mt-0.5 text-xs font-medium text-ink-subtle">{subtitle}</span> : null}
      </span>
    </Link>
  );
}
