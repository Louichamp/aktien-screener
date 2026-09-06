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

// Hängt den Backend-Schlüssel an die weitergeleiteten API-Aufrufe.
// Der Browser sieht ihn nie: next.config.mjs proxied /api/v1/* serverseitig
// zum zweiten Vercel-Projekt, und dieser Header wird hier — vor dem Rewrite —
// gesetzt. BACKEND_API_KEY ist bewusst NICHT NEXT_PUBLIC_.
function withBackendKey(request: NextRequest): NextResponse {
  const key = process.env.BACKEND_API_KEY;
  if (!key) return NextResponse.next();
  const headers = new Headers(request.headers);
  headers.set("x-api-key", key);
  return NextResponse.next({ request: { headers } });
}

export async function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // Nur HTML-Seiten schützen. API-Routen (holen ihre Daten vom Backend, nicht
  // von hier), /health (Monitoring, soll ohne Login erreichbar sein) und
  // statische Assets immer durchlassen.
  //
  // WICHTIG: next.config.mjs setzt trailingSlash:true (Erbe der alten Static-
  // Export-Config) — Next.js selbst 308-redirected /login -> /login/. Ohne
  // die "/login/"-Variante hier würde DAS wiederum von dieser Middleware als
  // ungeschützte Seite verkannt -> erneuter Redirect zu /login -> Next.js
  // redirected wieder auf /login/ -> Endlosschleife (genau das brach den
  // ersten Deploy: 123 Edge-Requests, 0 Function-Invocations, jede Seite
  // hing in diesem Loop fest).
  if (
    pathname === "/login" || pathname === "/login/" ||
    pathname.startsWith("/api/login") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico" ||
    pathname === "/health"
  ) {
    return NextResponse.next();
  }

  const isApi = pathname.startsWith("/api/v1/");

  const expected = process.env.SITE_PASSWORD;
  if (!expected) return withBackendKey(request);   // kein Schutz konfiguriert

  const sessionValue = request.cookies.get(COOKIE_NAME)?.value;
  if (sessionValue) {
    const expectedHash = await computeHash(expected);
    if (sessionValue === expectedHash) return withBackendKey(request);   // gültiges Cookie
  }

  // Unangemeldete API-Aufrufe bekommen 401 statt eines Redirects: Ein
  // fetch() folgt dem 302 zu /login und bekommt HTML zurück, was im Client
  // als kryptischer JSON-Parse-Fehler landet statt als klarer Auth-Fehler.
  if (isApi) {
    return NextResponse.json({ detail: "Nicht angemeldet" }, { status: 401 });
  }

  const loginUrl = new URL("/login", request.url);
  const next = pathname + search;
  if (next && next !== "/login") {
    loginUrl.searchParams.set("next", next);
  }
  return NextResponse.redirect(loginUrl);
}

// Alle Pfade außer statischen Next.js-Assets UND /api/login. Der In-Function-
// Ausschluss oben reichte NICHT: Next.js liefert Set-Cookie-Header aus einem
// Route-Handler als internes "x-middleware-set-cookie" statt eines echten
// Set-Cookie an den Browser, sobald derselbe Request-Pfad ZUSÄTZLICH von der
// Middleware verarbeitet wird (auch wenn sie nur NextResponse.next() macht) —
// live reproduziert: Login-POST kam 200 zurück, aber der Browser bekam nie
// ein echtes Set-Cookie -> Session blieb leer -> sofortiger Zurück-Redirect
// zu /login. /api/login muss daher schon HIER, auf Matcher-Ebene, raus.
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/login).*)"],
};
