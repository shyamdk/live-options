"use client";

import { LockKeyhole } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import AppSidebar from "@/components/AppSidebar";
import MarketStrip from "@/components/MarketStrip";
import { clearAuthToken, getAuthSession, getAuthStatus, loginApp } from "@/lib/api";
import type { AuthStatus } from "@/types/live";

export default function AuthShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const [authenticated, setAuthenticated] = useState(false);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const authStatus = await getAuthStatus();
        setStatus(authStatus);
        setUsername(authStatus.username || "admin");
        if (!authStatus.enabled) {
          setAuthenticated(true);
          return;
        }
        await getAuthSession();
        setAuthenticated(true);
      } catch {
        setAuthenticated(false);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await loginApp(username.trim(), password);
      setAuthenticated(true);
      setPassword("");
    } catch (exc) {
      clearAuthToken();
      setError(exc instanceof Error ? exc.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  }

  if (loading && !status) {
    return <div className="auth-page">Checking session</div>;
  }

  if (!authenticated) {
    return (
      <main className="auth-page">
        <form className="auth-panel" onSubmit={handleSubmit}>
          <div className="auth-mark">
            <LockKeyhole size={22} />
          </div>
          <h1>Live Options</h1>
          <p>Sign in to manage Dhan positions.</p>
          {status?.enabled && !status.configured ? (
            <div className="alert error">APP_AUTH_PASSWORD is not configured on the backend.</div>
          ) : null}
          {error ? <div className="alert error">{error}</div> : null}
          <label>
            <span>Username</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label>
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </label>
          <button className="button auth-submit" type="submit" disabled={loading || !status?.configured}>
            Sign in
          </button>
        </form>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <AppSidebar />
      <main className="main">
        <MarketStrip />
        {children}
      </main>
    </div>
  );
}
