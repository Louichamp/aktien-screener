// Passwortschutz für die gesamte Seite (inkl. der /data/*.json-Dateien).
// Läuft als Netlify Edge Function vor jeder Auslieferung. Das Passwort kommt aus
// der Netlify-Umgebungsvariable SITE_PASSWORD (Benutzer optional via SITE_USER).
// Ist kein Passwort gesetzt, bleibt die Seite offen (kein versehentliches Aussperren).
export default async (request) => {
  const expected = Netlify.env.get("SITE_PASSWORD");
  if (!expected) return; // kein Schutz konfiguriert -> durchlassen

  const user = Netlify.env.get("SITE_USER") || "louichamp";
  const header = request.headers.get("authorization") || "";
  const [scheme, encoded] = header.split(" ");

  if (scheme === "Basic" && encoded) {
    let decoded = "";
    try { decoded = atob(encoded); } catch { /* ungültig */ }
    const i = decoded.indexOf(":");
    const u = decoded.slice(0, i);
    const p = decoded.slice(i + 1);
    if (u === user && p === expected) return; // korrekt -> durchlassen
  }

  return new Response("🔒 Louichamp Screener — Zugang nur mit Passwort.", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Louichamp Screener", charset="UTF-8"',
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    },
  });
};

export const config = { path: "/*" };
