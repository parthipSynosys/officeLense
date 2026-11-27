import { Link } from "react-router-dom";

/** Locator brand logo (public/locator-logo.png, transparent PNG). */
export function Logo({ to = "/", subtitle }: { to?: string; subtitle?: string }) {
  return (
    <Link to={to} className="inline-flex shrink-0 items-center gap-3 rounded-xl" aria-label="Locator home">
      <img
        src="/locator-logo.png"
        alt="Locator — Tracking Redefined"
        width={403}
        height={126}
        className="h-9 w-auto max-w-none shrink-0 sm:h-11"
      />
      {subtitle ? (
        <span className="hidden shrink-0 whitespace-nowrap rounded-full bg-primary-50 px-2.5 py-1 text-xs font-semibold text-primary-700 sm:inline-block">
          {subtitle}
        </span>
      ) : null}
    </Link>
  );
}
