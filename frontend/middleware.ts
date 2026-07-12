// Cookie-basierter Passwortschutz — Next.js-Middleware-Äquivalent von
// netlify/edge-functions/auth.js. Läuft auf der Vercel Edge Runtime (gleiche
// Web-Crypto-API wie Netlifys Deno-Edge-Runtime, daher 1:1 portierbare Logik).
// Besucher ohne gültiges Session-Cookie werden auf /login weitergeleitet.
// Das Passwort kommt ausschließlich aus der Server-Umgebungsvariable
// SITE_PASSWORD (NICHT NEXT_PUBLIC_ — bleibt clientseitig unsichtbar).

import { NextRequest, NextResponse } from "next/server";

const SALT = "louichamp-screener-v1";
const COOKIE_NAME = "screener_session";

async function computeHash(password: string): Promise<string> {
  const data = new TextEncoder().encode(password + SALT);
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // Nur HTML-Seiten schützen. API-Routen (holen ihre Daten vom Backend, nicht
  // von hier) und statische Assets immer durchlassen.
  if (
    pathname === "/login" ||
    pathname.startsWith("/api/login") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }

  const expected = process.env.SITE_PASSWORD;
  if (!expected) return NextResponse.next();   // kein Schutz konfiguriert -> durchlassen

  const sessionValue = request.cookies.get(COOKIE_NAME)?.value;
  if (sessionValue) {
    const expectedHash = await computeHash(expected);
    if (sessionValue === expectedHash) return NextResponse.next();   // gültiges Cookie
  }

  const loginUrl = new URL("/login", request.url);
  const next = pathname + search;
  if (next && next !== "/login") {
    loginUrl.searchParams.set("next", next);
  }
  return NextResponse.redirect(loginUrl);
}

// Alle Pfade außer statischen Next.js-Assets (Middleware kann diese nicht per
// pathname-Check oben ausschließen, da sie vor dem Routing läuft).
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
