import { Outlet } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { LockIcon } from "@/components/Icons";

export function GuestLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-surface focus:px-4 focus:py-2 focus:shadow-lifted">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-line/70 bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4">
          <Logo />
          <span className="hidden items-center gap-1.5 text-xs font-medium text-ink-subtle sm:inline-flex">
            <LockIcon /> Selfies are never stored
          </span>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 pb-16 pt-6 sm:pt-10">
        <Outlet />
      </main>
      <footer className="border-t border-line/70 py-6 text-center text-xs text-ink-subtle">
        Your selfie is only used to find your photos. It is never saved.
      </footer>
    </div>
  );
}
