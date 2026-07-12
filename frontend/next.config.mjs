// Live-API-Architektur (Vercel + Render + Timescale Cloud): kein statischer
// Export mehr (`output: "export"` entfernt) — die Seite läuft als normale
// Next.js-App auf Vercel und holt Daten zur Laufzeit vom FastAPI-Backend
// (NEXT_PUBLIC_API_BASE). trailingSlash bleibt für stabile URLs.
const nextConfig = {
  trailingSlash: true,
  images: { unoptimized: true }
}

export default nextConfig