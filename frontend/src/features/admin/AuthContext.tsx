/**
 * Admin authentication.
 *
 * The JWT is kept in React memory and mirrored to sessionStorage so a page
 * refresh doesn't log the admin out mid-upload. sessionStorage is per-tab and
 * cleared when the tab closes; nothing is stored in localStorage or cookies.
 * The token auto-expires client-side at its `exp`, and any 401 logs out.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { createAdminApi, login as apiLogin, type AdminApi } from "@/lib/api";

const STORAGE_KEY = "eventlens.admin.session";

interface Session {
  token: string;
  email: string;
  expiresAt: number; // epoch ms
}

interface AuthValue {
  session: Session | null;
  api: AdminApi | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthValue | null>(null);

function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    return s.expiresAt > Date.now() + 5_000 ? s : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession);

  const logout = useCallback(() => {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* storage unavailable */
    }
    setSession(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiLogin(email, password);
    const s: Session = { token: res.access_token, email: res.email, expiresAt: Date.now() + res.expires_in * 1000 };
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    } catch {
      /* private mode: memory only */
    }
    setSession(s);
  }, []);

  // Auto-logout at expiry.
  useEffect(() => {
    if (!session) return;
    const ms = session.expiresAt - Date.now();
    if (ms <= 0) {
      logout();
      return;
    }
    const id = window.setTimeout(logout, Math.min(ms, 2 ** 31 - 1));
    return () => window.clearTimeout(id);
  }, [session, logout]);

  const api = useMemo(() => (session ? createAdminApi(session.token, logout) : null), [session, logout]);
  const value = useMemo(() => ({ session, api, login, logout }), [session, api, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Admin API for components rendered inside <RequireAdmin> (always logged in). */
export function useAdminApi(): AdminApi {
  const { api } = useAuth();
  if (!api) throw new Error("useAdminApi used without a session");
  return api;
}
