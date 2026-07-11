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

  if (password !== expected) {
    return NextResponse.json(
      { error: "Falsches Passwort" },
      { status: 401, headers: { "cache-control": "no-store" } }
    );
  }

  const hash = await computeHash(expected);
  const res = NextResponse.json({ ok: true }, { headers: { "cache-control": "no-store" } });
  res.cookies.set(COOKIE_NAME, hash, {
    maxAge: COOKIE_MAX_AGE,
    path: "/",
    secure: true,
    httpOnly: true,
    sameSite: "lax",
  });
  return res;
}
