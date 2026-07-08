"use client";

// Passwordless OTP sign-in widget for the auth add-on. Calls the backend /auth/*
// endpoints through the same-origin proxy (see next.config.mjs). The session
// token is kept in localStorage and sent as X-Session-Token.

import { useEffect, useState } from "react";

type User = {
  id: string;
  email: string | null;
  phone: string | null;
  display_name: string | null;
};

const TOKEN_KEY = "auth_session_token";

function getToken(): string | null {
  return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
}

export default function AuthWidget() {
  const [user, setUser] = useState<User | null>(null);
  const [ident, setIdent] = useState("");
  const [code, setCode] = useState("");
  const [stage, setStage] = useState<"idle" | "code">("idle");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [debugCode, setDebugCode] = useState<string | null>(null);

  async function refresh(): Promise<void> {
    const t = getToken();
    if (!t) {
      setUser(null);
      return;
    }
    const res = await fetch("/auth/me", { headers: { "X-Session-Token": t } });
    setUser(res.ok ? ((await res.json()) as User) : null);
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function requestCode(): Promise<void> {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/auth/otp/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier: ident, channel: "email" }),
      });
      const data = (await res.json()) as { sent: boolean; debug_code: string | null };
      setStage("code");
      setDebugCode(data.debug_code ?? null);
      setMsg("Code sent — check your email (or use the dev code).");
    } catch {
      setMsg("Couldn't request a code.");
    } finally {
      setBusy(false);
    }
  }

  async function verify(): Promise<void> {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/auth/otp/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier: ident, channel: "email", code }),
      });
      if (!res.ok) {
        setMsg("Invalid or expired code.");
        return;
      }
      const data = (await res.json()) as { token: string; user: User };
      window.localStorage.setItem(TOKEN_KEY, data.token);
      setUser(data.user);
      setStage("idle");
      setIdent("");
      setCode("");
      setDebugCode(null);
    } catch {
      setMsg("Couldn't verify the code.");
    } finally {
      setBusy(false);
    }
  }

  async function logout(): Promise<void> {
    const t = getToken();
    if (t) {
      await fetch("/auth/logout", { method: "POST", headers: { "X-Session-Token": t } });
    }
    window.localStorage.removeItem(TOKEN_KEY);
    setUser(null);
  }

  if (user) {
    return (
      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
        <span>Signed in as {user.email ?? user.phone ?? user.id.slice(0, 8)}</span>
        <button onClick={() => void logout()}>Sign out</button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
      {stage === "idle" ? (
        <>
          <input
            type="email"
            placeholder="you@example.com"
            value={ident}
            onChange={(e) => setIdent(e.target.value)}
          />
          <button disabled={busy || ident.length === 0} onClick={() => void requestCode()}>
            Send code
          </button>
        </>
      ) : (
        <>
          <input
            inputMode="numeric"
            placeholder="6-digit code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <button disabled={busy || code.length === 0} onClick={() => void verify()}>
            Verify
          </button>
          {debugCode !== null ? <span>dev code: {debugCode}</span> : null}
        </>
      )}
      {msg !== null ? <span style={{ fontSize: "0.85rem", opacity: 0.8 }}>{msg}</span> : null}
    </div>
  );
}
