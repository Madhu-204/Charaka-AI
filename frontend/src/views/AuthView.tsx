import { useState } from "react";
import type { FormEvent } from "react";
import type { AuthUser } from "../api";
import { ApiError, login, register } from "../api";
import { IconLeaf, IconShield } from "../components/Icons";

interface AuthViewProps {
  needsRegistration: boolean;
  onAuthenticated: (user: AuthUser) => void;
}

/**
 * Sign-in and registration for Charaka AI.
 *
 * Defaults to whichever mode the visitor needs: the first account on a fresh
 * instance lands on Register, everyone else on Sign in, and switching between
 * them preserves what has been typed.
 */
export function AuthView({ needsRegistration, onAuthenticated }: AuthViewProps) {
  const [mode, setMode] = useState<"login" | "register">(
    needsRegistration ? "register" : "login"
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isRegister = mode === "register";

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const res = isRegister
        ? await register(email.trim(), password, name.trim())
        : await login(email.trim(), password);
      onAuthenticated(res.user);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not reach the server. Is the backend running?"
      );
    } finally {
      setBusy(false);
    }
  }

  function switchMode(next: "login" | "register") {
    setMode(next);
    setError(null);
  }

  return (
    <div className="auth">
      <div className="auth__card">
        <div className="auth__brand">
          <IconLeaf width={22} height={22} />
          <span>Charaka AI</span>
        </div>

        <h1 className="auth__title">
          {isRegister ? "Create your account" : "Welcome back"}
        </h1>
        <p className="auth__sub">
          {isRegister
            ? "Your conversations, documents and dosha profile stay private to your account."
            : "Sign in to pick up your Ayurvedic conversations where you left them."}
        </p>

        {needsRegistration && isRegister && (
          <div className="auth__note">
            <IconShield width={14} height={14} />
            This looks like the first account on this instance — set up the
            owner login, then share the sign-in link with your testers.
          </div>
        )}

        <form className="auth__form" onSubmit={submit}>
          {isRegister && (
            <label className="auth__field">
              <span>Name</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                autoComplete="name"
                maxLength={80}
              />
            </label>
          )}

          <label className="auth__field">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
              maxLength={254}
            />
          </label>

          <label className="auth__field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isRegister ? "At least 8 characters" : "••••••••"}
              autoComplete={isRegister ? "new-password" : "current-password"}
              required
              minLength={isRegister ? 8 : undefined}
              maxLength={200}
            />
          </label>

          {error && (
            <div className="auth__error" role="alert">
              {error}
            </div>
          )}

          <button className="auth__submit" type="submit" disabled={busy}>
            {busy
              ? isRegister
                ? "Creating account…"
                : "Signing in…"
              : isRegister
                ? "Create account"
                : "Sign in"}
          </button>
        </form>

        <div className="auth__switch">
          {isRegister ? (
            <>
              Already have an account?{" "}
              <button type="button" onClick={() => switchMode("login")}>
                Sign in
              </button>
            </>
          ) : (
            <>
              New here?{" "}
              <button type="button" onClick={() => switchMode("register")}>
                Create an account
              </button>
            </>
          )}
        </div>

        <p className="auth__disclaimer">
          Charaka AI offers general wellness guidance from classical Ayurvedic
          texts. It is not a diagnosis — always consult a qualified physician
          about your own health.
        </p>
      </div>
    </div>
  );
}
