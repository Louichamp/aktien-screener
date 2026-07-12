// Live-API-Architektur (Vercel + Neon): kein statischer Export mehr
// (`output: "export"` entfernt) — die Seite läuft als normale Next.js-App auf
// Vercel und holt Daten zur Laufzeit vom FastAPI-Backend (frontend/api/index.py).
//
// trailingSlash:true bewusst ENTFERNT (war Erbe der alten Static-Export-Config):
// in Kombination mit middleware.ts (Passwort-Redirect zu /login) erzeugte es
// eine Endlosschleife — Next.js redirectete /login -> /login/, die Middleware
// erkannte "/login/" nicht als ausgeschlossen -> zurück zu /login -> loop.
// Ohne trailingSlash gibt's diese Zweideutigkeit nicht mehr.
const nextConfig = {
  images: { unoptimized: true }
}

export default nextConfig