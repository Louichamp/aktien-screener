// Live-API-Architektur (Vercel + Neon): kein statischer Export mehr
// (`output: "export"` entfernt) — die Seite läuft als normale Next.js-App auf
// Vercel und holt Daten zur Laufzeit vom FastAPI-Backend.
//
// Backend = ZWEITES, getrenntes Vercel-Projekt (Root Directory = Repo-Root,
// dort liegt api/main.py bereits nativ) statt einer Python-Function INNERHALB
// dieses Next.js-Projekts: Vercels Python-Builder bündelt bei Root Directory
// "frontend" nur Dateien AUS frontend/ — das repo-root api/-Paket (+
// infrastructure/) wäre für eine Function hier unsichtbar gewesen
// (ModuleNotFoundError: No module named 'api.main', production-getestet).
//
// rewrites() proxied serverseitig zum zweiten Projekt -> der Browser sieht
// weiterhin NUR eine Domain (kein CORS, keine zweite Origin für den Client).
// BACKEND_URL zeigt auf die Vercel-URL des zweiten Projekts (ohne trailing /).
async function rewrites() {
  const backend = process.env.BACKEND_URL;
  if (!backend) return [];
  return [
    { source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` },
    { source: "/health", destination: `${backend}/health` },
  ];
}

// trailingSlash:true bewusst ENTFERNT (war Erbe der alten Static-Export-Config):
// in Kombination mit middleware.ts (Passwort-Redirect zu /login) erzeugte es
// eine Endlosschleife — Next.js redirectete /login -> /login/, die Middleware
// erkannte "/login/" nicht als ausgeschlossen -> zurück zu /login -> loop.
// Ohne trailingSlash gibt's diese Zweideutigkeit nicht mehr.
const nextConfig = {
  images: { unoptimized: true },
  rewrites,
}

export default nextConfig