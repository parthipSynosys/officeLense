/**
 * In-memory state for the guest flow (filters, consent, selfies, last results).
 *
 * Selfies live ONLY in this React state as Blobs — never in localStorage,
 * sessionStorage, IndexedDB or cookies — and `reset()` drops them and revokes
 * their preview URLs ("Start over"). Closing/reloading the tab also clears them.
 */
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import type { MatchResponse } from "@/lib/api";

export interface Selfie {
  id: string;
  blob: Blob;
  previewUrl: string;
}

export interface SearchResult {
  /** Changes on every new search, so result views can reset their state. */
  id: number;
  response: MatchResponse;
  threshold: number | undefined; // undefined = server default
}

export const MAX_SELFIES = 3;
// Wider search for "Show more possible matches". 0.30 let in too many other people.
export const LOW_THRESHOLD = 0.33;
export const MAX_SELFIE_BYTES = 8 * 1024 * 1024;

interface GuestFlow {
  consent: boolean;
  setConsent: (v: boolean) => void;
  eventTypes: string[];
  eventIds: string[];
  setFilters: (f: { eventTypes?: string[]; eventIds?: string[] }) => void;
  selfies: Selfie[];
  addSelfie: (blob: Blob) => void;
  removeSelfie: (id: string) => void;
  clearSelfies: () => void;
  result: SearchResult | null;
  setResult: (r: SearchResult | null) => void;
  reset: () => void;
}

const Ctx = createContext<GuestFlow | null>(null);

let counter = 0;

export function GuestFlowProvider({ children }: { children: ReactNode }) {
  const [consent, setConsent] = useState(false);
  const [eventTypes, setEventTypes] = useState<string[]>([]);
  const [eventIds, setEventIds] = useState<string[]>([]);
  const [selfies, setSelfies] = useState<Selfie[]>([]);
  const [result, setResult] = useState<SearchResult | null>(null);
  const selfiesRef = useRef(selfies);
  selfiesRef.current = selfies;

  const addSelfie = useCallback((blob: Blob) => {
    setSelfies((prev) => {
      if (prev.length >= MAX_SELFIES) return prev;
      return [...prev, { id: `selfie-${++counter}`, blob, previewUrl: URL.createObjectURL(blob) }];
    });
  }, []);

  const removeSelfie = useCallback((id: string) => {
    setSelfies((prev) => {
      const target = prev.find((s) => s.id === id);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((s) => s.id !== id);
    });
  }, []);

  const clearSelfies = useCallback(() => {
    selfiesRef.current.forEach((s) => URL.revokeObjectURL(s.previewUrl));
    setSelfies([]);
  }, []);

  const setFilters = useCallback((f: { eventTypes?: string[]; eventIds?: string[] }) => {
    if (f.eventTypes) setEventTypes(f.eventTypes);
    if (f.eventIds) setEventIds(f.eventIds);
  }, []);

  const reset = useCallback(() => {
    clearSelfies();
    setResult(null);
    setConsent(false);
    setEventTypes([]);
    setEventIds([]);
  }, [clearSelfies]);

  const value = useMemo<GuestFlow>(
    () => ({
      consent,
      setConsent,
      eventTypes,
      eventIds,
      setFilters,
      selfies,
      addSelfie,
      removeSelfie,
      clearSelfies,
      result,
      setResult,
      reset,
    }),
    [consent, eventTypes, eventIds, setFilters, selfies, addSelfie, removeSelfie, clearSelfies, result, reset],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useGuestFlow(): GuestFlow {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useGuestFlow must be used inside GuestFlowProvider");
  return ctx;
}
