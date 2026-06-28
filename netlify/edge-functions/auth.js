// Cookie-basierter Passwortschutz — ersetzt HTTP Basic Auth vollständig.
// Besucher ohne gültiges Session-Cookie werden auf /login weitergeleitet.
// Das Passwort kommt ausschließlich aus der Netlify-Umgebungsvariable SITE_PASSWORD.
// Ist kein Passwort gesetzt, bleibt die Seite offen (kein versehentliches Aussperren).

const SALT = "louichamp-screener-v1";
const COOKIE_NAME = "screener_session";

async function computeHash(password) {
  const data = new TextEncoder().encode(password + SALT);
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function getCookie(cookieHeader, name) {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    const k = part.slice(0, eq).trim();
    if (k === name) return part.slice(eq + 1).trim();
  }
  return null;
}

export default async (request) => {
  const url = new URL(request.url);
  const path = url.pathname;

  // Login-Seite und Login-API immer durchlassen (sonst Endlos-Redirect).
  if (
    path === "/login" ||
    path === "/login/" ||
    path.startsWith("/api/login")
  ) {
    return;
  }

  const expected = Netlify.env.get("SITE_PASSWORD");
  if (!expected) return; // kein Schutz konfiguriert -> durchlassen

  const sessionValue = getCookie(request.headers.get("cookie"), COOKIE_NAME);
  if (sessionValue) {
    const expectedHash = await computeHash(expected);
    if (sessionValue === expectedHash) return; // gültiges Cookie -> durchlassen
  }

  // Kein/ungültiges Cookie -> zur Login-Seite umleiten.
  // Ursprüngliche URL als ?next= mitgeben, damit nach dem Login direkt dorthin
  // weitergeleitet werden kann.
  const loginUrl = new URL("/login", request.url);
  const next = path + url.search;
  if (next && next !== "/login" && next !== "/login/") {
    loginUrl.searchParams.set("next", next);
  }
  return Response.redirect(loginUrl.toString(), 302);
};

export const config = { path: "/*" };
