/** Full-screen "finding your photos" loader in the Locator brand style. */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

const STEPS = [
  "Checking your selfie…",
  "Scanning event photos…",
  "Scanning event videos…",
  "Matching your face…",
  "Gathering your photos…",
];
const STEP_MS = 1400;

export function SearchingOverlay({ open, title = "Finding your photos" }: { open: boolean; title?: string }) {
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!open) return;
    setStep(0);
    // Advance through the steps, then stay on the last one until results arrive.
    const id = window.setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), STEP_MS);
    return () => window.clearInterval(id);
  }, [open]);

  if (!open) return null;
  const progress = (step + 1) / STEPS.length;

  return createPortal(
    <div
      role="status"
      aria-live="polite"
      aria-label={title}
      className="fixed inset-0 z-[60] flex flex-col items-center justify-center bg-background/95 px-6 backdrop-blur-sm animate-fade-in"
    >
      <img src="/locator-logo.png" alt="Locator" className="mb-10 h-10 w-auto opacity-90" />

      <div className="relative flex h-28 w-28 items-center justify-center">
        <span className="absolute bottom-1 h-6 w-6 rounded-full bg-primary/30 animate-pin-pulse" />
        <span className="absolute bottom-1 h-6 w-6 rounded-full bg-primary/20 animate-pin-pulse [animation-delay:0.8s]" />
        <svg viewBox="0 0 64 64" className="relative h-20 w-20 animate-pin-bounce drop-shadow-lg" aria-hidden="true">
          <path d="M32 4C19.3 4 9 14.1 9 26.6 9 43.5 32 60 32 60s23-16.5 23-33.4C55 14.1 44.7 4 32 4z" className="fill-primary" />
          <circle cx="32" cy="26" r="13" fill="#fff" />
          <path d="M32 15 24 34l8-4 8 4z" className="fill-primary" />
        </svg>
      </div>

      <h2 className="mt-8 text-xl font-bold tracking-tight text-ink">{title}</h2>
      <p className="mt-1.5 h-5 text-sm text-ink-muted">{STEPS[step]}</p>

      <div className="mt-6 h-1.5 w-56 overflow-hidden rounded-full bg-primary-100">
        <div className="h-full rounded-full bg-primary transition-[width] duration-700 ease-out" style={{ width: `${progress * 100}%` }} />
      </div>
      <p className="mt-6 max-w-xs text-center text-xs text-ink-subtle">This can take a few seconds for large events with videos.</p>
    </div>,
    document.body,
  );
}
