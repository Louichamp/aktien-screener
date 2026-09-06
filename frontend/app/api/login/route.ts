// Login-API: prüft das Passwort serverseitig und setzt ein sicheres Session-Cookie.
// Next.js-Route-Handler-Äquivalent von netlify/edge-functions/login.js.
// POST /api/login — JSON-Body: { "password": "..." }
//
// Cookie-Sicherheit: HttpOnly verhindert JS-Zugriff (XSS-Schutz), Secure nur
// über HTTPS, SameSite=Lax als CSRF-Schutz ohne den Login-Flow zu blockieren.

import { NextRequest, NextResponse } from "next/server";

export const runtime = "edge";   // gleiche Web-Crypto-API wie middleware.ts

const SALT = "louichamp-screener-v1";
const COOKIE_NAME = "screener_session";
const COOKIE_MAX_AGE = 30 * 24 * 60 * 60; // 30 Tage in Sekunden

// Brute-Force-Bremse. Die Seite hat EIN gemeinsames Passwort — ohne Bremse
// kann es unbegrenzt schnell durchprobiert werden. Der Zähler lebt im
// Arbeitsspeicher der Edge-Instanz: kein zusätzlicher Dienst (kein Redis/KV)
// für eine private Seite, aber wirksam, weil Vercel Instanzen wiederverwendet.
// Bewusst als Bremse verstanden, nicht als lückenloser Schutz.
const MAX_ATTEMPTS = 8;
const WINDOW_MS = 10 * 60 * 1000;
const attempts = new Map<string, number[]>();

function clientKey(request: NextRequest): string {
  const fwd = request.headers.get("x-forwarded-for");
  return (fwd ? fwd.split(",")[0].trim() : "") || "unbekannt";
}

function tooManyAttempts(key: string): boolean {
  const now = Date.now();
  const recent = (attempts.get(key) ?? []).filter((t) => now - t < WINDOW_MS);
  attempts.set(key, recent);
  if (attempts.size > 5000) attempts.clear();      // Speicherdeckel
  return recent.length >= MAX_ATTEMPTS;
}

function noteFailure(key: string): void {
  const now = Date.now();
  attempts.set(key, [...(attempts.get(key) ?? []).filter((t) => now - t < WINDOW_MS), now]);
}

// Zeitkonstanter Vergleich: ein einfaches !== bricht beim ersten
// abweichenden Zeichen ab und verrät über die Antwortzeit, wie weit ein
// geratenes Passwort stimmt.
function timingSafeEqual(a: string, b: string): boolean {
  const ea = new TextEncoder().encode(a);
  const eb = new TextEncoder().encode(b);
  let diff = ea.length ^ eb.length;
  const n = Math.max(ea.length, eb.length);
  for (let i = 0; i < n; i++) diff |= (ea[i] ?? 0) ^ (eb[i] ?? 0);
  return diff === 0;
}

async function computeHash(password: string): Promise<string> {
  const data = new TextEncoder().encode(password + SALT);
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function POST(request: NextRequest) {
  const expected = process.env.SITE_PASSWORD;
  if (!expected) {
    // Kein Passwort konfiguriert -> Login sofort erfolgreich
    return NextResponse.json({ ok: true });
  }

  const key = clientKey(request);
  if (tooManyAttempts(key)) {
    return NextResponse.json(
      { error: "Zu viele Fehlversuche. Bitte in 10 Minuten erneut versuchen." },
      { status: 429, headers: { "cache-control": "no-store", "retry-after": "600" } }
    );
  }

  let password = "";
  try {
    const contentType = request.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const body = await request.json();
      password = String(body.password ?? "");
    } else {
      const body = await request.formData();
      password = String(body.get("password") ?? "");
    }
  } catch {
    return NextResponse.json({ error: "Ungültige Anfrage" }, { status: 400 });
  }

  if (!timingSafeEqual(password, expected)) {
    noteFailure(key);
    return NextResponse.json(
      { error: "Falsches Passwort" },
      { status: 401, headers: { "cache-control": "no-store" } }
    );
  }
  attempts.delete(key);                            // Erfolg -> Zähler zurücksetzen

  const hash = await computeHash(expected);
  const res = NextResponse.json({ ok: true }, { headers: { "cache-control": "no-store" } });
  // secure an das tatsächliche Protokoll koppeln statt hart auf true: sonst
  // sendet der Browser das Cookie in der lokalen Entwicklung über http://
  // nicht mit -> Login-Redirect-Loop sobald SITE_PASSWORD gesetzt ist.
  // Vercel terminiert TLS und liefert https: korrekt in nextUrl.protocol.
  res.cookies.set(COOKIE_NAME, hash, {
    maxAge: COOKIE_MAX_AGE,
    path: "/",
    secure: request.nextUrl.protocol === "https:",
    httpOnly: true,
    sameSite: "lax",
  });
  return res;
}
