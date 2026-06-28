// Login-API: prüft das Passwort serverseitig und setzt ein sicheres Session-Cookie.
// POST /api/login  — JSON-Body: { "password": "..." }
// Antwort: { "ok": true } oder { "error": "Falsches Passwort" }
//
// Cookie-Sicherheit: HttpOnly verhindert JS-Zugriff (XSS-Schutz).
// Der Browser sendet das Cookie automatisch bei jedem Request — kein JS-Zugriff nötig.

const SALT = "louichamp-screener-v1";
const COOKIE_NAME = "screener_session";
const COOKIE_MAX_AGE = 30 * 24 * 60 * 60; // 30 Tage in Sekunden

async function computeHash(password) {
  const data = new TextEncoder().encode(password + SALT);
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export default async (request) => {
  if (request.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const expected = Netlify.env.get("SITE_PASSWORD");
  if (!expected) {
    // Kein Passwort konfiguriert -> Login sofort erfolgreich
    return new Response(JSON.stringify({ ok: true }), {
      headers: { "content-type": "application/json" },
    });
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
    return new Response(JSON.stringify({ error: "Ungültige Anfrage" }), {
      status: 400,
      headers: { "content-type": "application/json" },
    });
  }

  if (password !== expected) {
    return new Response(JSON.stringify({ error: "Falsches Passwort" }), {
      status: 401,
      headers: {
        "content-type": "application/json",
        "cache-control": "no-store",
      },
    });
  }

  const hash = await computeHash(expected);
  // HttpOnly: JS kann den Cookie nicht lesen (XSS-Schutz).
  // Secure: nur über HTTPS gesendet (Netlify ist immer HTTPS).
  // SameSite=Lax: CSRF-Schutz ohne Login-Flow zu blockieren.
  const cookie = [
    `${COOKIE_NAME}=${hash}`,
    `Max-Age=${COOKIE_MAX_AGE}`,
    "Path=/",
    "Secure",
    "HttpOnly",
    "SameSite=Lax",
  ].join("; ");

  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: {
      "content-type": "application/json",
      "set-cookie": cookie,
      "cache-control": "no-store",
    },
  });
};

export const config = { path: "/api/login" };
