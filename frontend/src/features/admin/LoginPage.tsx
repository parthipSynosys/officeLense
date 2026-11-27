import { useId, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { AlertIcon, LockIcon } from "@/components/Icons";
import { Logo } from "@/components/Logo";
import { Alert } from "@/components/States";
import { ApiError } from "@/lib/api";
import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { session, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const emailId = useId();
  const passwordId = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const from = (location.state as { from?: string } | null)?.from ?? "/admin";
  if (session) return <Navigate to={from} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError("Incorrect username or password.");
      else if (err instanceof ApiError && err.code === "RATE_LIMITED") setError("Too many attempts. Please wait a minute and try again.");
      else if (err instanceof ApiError && err.isNetwork) setError("Can't reach the server. Check your connection.");
      else setError("Login failed. Please try again.");
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex justify-center">
          <Logo to="/" subtitle="Admin" />
        </div>
        <form onSubmit={onSubmit} className="card space-y-4 p-6" noValidate>
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-50 text-lg text-primary">
              <LockIcon />
            </span>
            <div>
              <h1 className="text-lg font-semibold">Admin sign in</h1>
              <p className="text-sm text-ink-muted">Manage events and photos</p>
            </div>
          </div>
          {error ? (
            <Alert tone="danger" icon={<AlertIcon />}>
              {error}
            </Alert>
          ) : null}
          <div>
            <label htmlFor={emailId} className="label">
              Username
            </label>
            <input
              id={emailId}
              type="text"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              autoComplete="username"
              required
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <label htmlFor={passwordId} className="label">
              Password
            </label>
            <input
              id={passwordId}
              type="password"
              autoComplete="current-password"
              required
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <Button type="submit" fullWidth size="lg" loading={submitting} disabled={!email || !password}>
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
}
