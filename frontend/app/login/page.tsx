"use client";

// Next.js-Äquivalent von frontend/public/login/index.html (Netlify-Pfad).
// Gleiche Logik (POST /api/login, ?next= Redirect mit Open-Redirect-Schutz),
// im Design-System der App (Tailwind-Tokens aus tailwind.config.ts) statt
// eigenständigem Inline-CSS.

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function getNext(params: URLSearchParams): string {
  const raw = params.get("next") || "/";
  // Nur relative Pfade akzeptieren (Open-Redirect-Schutz).
  if (raw.startsWith("/") && !raw.startsWith("//")) return raw;
  return "/";
}

// useSearchParams braucht eine Suspense-Grenze (wie ScreenerApp/app/page.tsx).
export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!password) return;
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        router.push(getNext(params));
        router.refresh();
      } else {
        setLoading(false);
        setError(data.error || "Anmeldung fehlgeschlagen");
        setPassword("");
      }
    } catch {
      setLoading(false);
      setError("Verbindungsfehler — bitte erneut versuchen");
    }
  }

  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <div className="w-full max-w-[400px] rounded-xl border border-edge bg-panel p-10 shadow-2xl">
        <div className="mb-8 text-center">
          <span className="bg-gradient-to-r from-amber-300 via-amber-400 to-yellow-600 bg-clip-text text-2xl font-black tracking-tight text-transparent">
            LOUICHAMP
          </span>
          <span className="mt-1 block text-[0.65rem] font-semibold uppercase tracking-[0.35em] text-muted">
            Screener
          </span>
        </div>

        <div className="mb-7 text-center">
          <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full border border-edge bg-panel2 text-accent">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
          </div>
          <h1 className="text-[1.1rem] font-semibold text-slate-100">Zugang</h1>
          <p className="text-sm text-muted">Bitte Passwort eingeben</p>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <label htmlFor="password" className="mb-1.5 block text-xs font-medium tracking-wide text-muted">
            Passwort
          </label>
          <input
            id="password"
            name="password"
            type="password"
            placeholder="··········"
            autoComplete="current-password"
            autoFocus
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mb-4 w-full rounded-lg border border-edge bg-panel2 px-3.5 py-2.5 text-slate-100 outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20"
          />

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-gradient-to-br from-amber-500 to-amber-700 py-3 text-sm font-bold tracking-wide text-ink transition-opacity disabled:cursor-not-allowed disabled:opacity-55 hover:not-disabled:opacity-90"
          >
            {loading ? "Weiterleiten …" : "Anmelden"}
          </button>

          {error && (
            <div className="mt-3.5 flex items-center gap-2 rounded-lg border border-bear/25 bg-bear/10 px-3.5 py-2.5 text-sm text-bear">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span>{error}</span>
            </div>
          )}
        </form>

        <div className="mt-8 text-center text-[0.7rem] text-edge">
          Louichamp Screener — privater Zugang
        </div>
      </div>
    </div>
  );
}
