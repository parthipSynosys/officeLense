import { Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { LogoutIcon } from "@/components/Icons";
import { Logo } from "@/components/Logo";
import { useAuth } from "./AuthContext";

/** Guards admin routes: redirects to the login page without a valid session. */
export function RequireAdmin() {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) return <Navigate to="/admin/login" replace state={{ from: location.pathname }} />;
  return <AdminLayout />;
}

function AdminLayout() {
  const { session, logout } = useAuth();
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-xl px-3 py-2 text-sm font-semibold transition-colors ${
      isActive ? "bg-primary-50 text-primary-700" : "text-ink-muted hover:bg-line/60 hover:text-ink"
    }`;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4">
          <Logo to="/admin" subtitle="Admin" />
          <nav className="ml-2 flex items-center gap-1" aria-label="Admin">
            <NavLink to="/admin" end className={link}>
              Dashboard
            </NavLink>
            <NavLink to="/admin/events" className={link}>
              Events
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-sm text-ink-subtle md:inline">{session?.email}</span>
            <button
              type="button"
              onClick={logout}
              className="inline-flex h-10 items-center gap-1.5 rounded-xl px-3 text-sm font-semibold text-ink-muted hover:bg-line/60 hover:text-ink"
            >
              <LogoutIcon className="text-lg" />
              <span className="hidden sm:inline">Log out</span>
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-16 pt-6">
        <Outlet />
      </main>
    </div>
  );
}
