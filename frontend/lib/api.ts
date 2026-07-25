// Zentrales API-Fetch-Handling für die FastAPI-Lese-Schicht.
// Filter/Sort/Pagination werden als Query-Parameter an /api/v1/screener gereicht
// — die DB erledigt WHERE/ORDER BY/LIMIT/OFFSET (siehe api/queries.py).
//
// Backend ist ein EIGENES, zweites Vercel-Projekt (Root Directory = Repo-Root,
// api/main.py läuft dort unverändert), NICHT im selben Projekt wie dieses
// Frontend — next.config.mjs proxied per rewrites() zu dessen URL
// (BACKEND_URL). Der Browser sieht dadurch trotzdem nur EINE Origin (dieses
// Frontend), daher kein CORS-Problem — aber same-origin kommt vom Next.js-
// Server-Proxy, nicht davon, dass Backend+Frontend dasselbe Deployment wären.
// NEXT_PUBLIC_API_BASE bleibt nur für lokale Entwicklung ohne diesen Proxy
// (z. B. separat laufendes `uvicorn api.main:app`) relevant.

import type {
  Facets,
  NewsResponse,
  ScreenerListResponse,
  ScreenerQuery,
  ScreenerRowDetail,
  Summary,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "";

function buildQuery(q: ScreenerQuery): string {
  const sp = new URLSearchParams();
  const set = (k: string, v: unknown) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  };
  set("search", q.search);
  set("strategy", q.strategy);
  set("risk_class", q.risk_class);
  set("sector", q.sector);
  set("country", q.country);
  set("asset_class", q.asset_class);
  set("status", q.status);
  set("rating", q.rating);
  set("trend_long", q.trend_long);
  set("trend_medium", q.trend_medium);
  set("min_total_score", q.min_total_score);
  set("min_wlatar", q.min_wlatar);
  set("min_wlafar", q.min_wlafar);
  set("min_dividend_yield", q.min_dividend_yield);
  set("max_risk_level", q.max_risk_level);
  set("tickers", q.tickers);
  if (q.rare_only) sp.set("rare_only", "true");
  set("sort_by", q.sort_by);
  set("sort_dir", q.sort_dir);
  sp.set("limit", String(q.limit ?? 25));
  sp.set("offset", String(q.offset ?? 0));
  return sp.toString();
}

export async function fetchScreener(q: ScreenerQuery): Promise<ScreenerListResponse> {
  const res = await fetch(`${API_BASE}/api/v1/screener?${buildQuery(q)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Screener-Liste fehlgeschlagen: ${res.status}`);
  return res.json();
}

export async function fetchFacets(): Promise<Facets> {
  const res = await fetch(`${API_BASE}/api/v1/screener/facets`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Facetten fehlgeschlagen: ${res.status}`);
  return res.json();
}

export async function fetchSummary(q: ScreenerQuery): Promise<Summary> {
  const res = await fetch(`${API_BASE}/api/v1/screener/summary?${buildQuery(q)}`,
    { cache: "no-store" });
  if (!res.ok) throw new Error(`Summary fehlgeschlagen: ${res.status}`);
  return res.json();
}

// Für den CSV-Export: holt ALLE zur Filterung passenden Zeilen, nicht nur eine
// Seite. api/routes.py deckelt `limit` hart auf 500 (Performance-Schutz für
// den normalen Listen-Endpoint) — ein einzelner fetchScreener-Call kappte den
// Export bisher STILL bei 500 Zeilen (ohne Hinweis, in Backend-Standard-
// Sortierung statt der auf dem Bildschirm gewählten). Bei einem 5250er-
// Universum ist "alles exportieren" ohne Filter ein sehr realistischer
// Auslöser. Paginiert jetzt in 500er-Blöcken bis zur tatsächlichen `total`,
// gedeckelt bei `cap` als Sicherheitsgrenze gegen einen Endlos-Export.
export async function fetchScreenerAll(q: ScreenerQuery, cap = 10_000): Promise<ScreenerListResponse> {
  const pageSize = 500;
  const first = await fetchScreener({ ...q, limit: pageSize, offset: 0 });
  const items = [...first.items];
  const target = Math.min(first.total, cap);
  let offset = pageSize;
  while (items.length < target) {
    const page = await fetchScreener({ ...q, limit: pageSize, offset });
    if (page.items.length === 0) break;              // Sicherheitsnetz gegen Endlosschleife
    items.push(...page.items);
    offset += pageSize;
  }
  return { ...first, items, limit: items.length };
}

export async function fetchTicker(ticker: string): Promise<ScreenerRowDetail | null> {
  const res = await fetch(`${API_BASE}/api/v1/screener/${encodeURIComponent(ticker)}`,
    { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Detail fehlgeschlagen: ${res.status}`);
  return res.json();
}

export async function fetchNews(ticker: string): Promise<NewsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/screener/${encodeURIComponent(ticker)}/news`,
    { cache: "no-store" });
  if (!res.ok) throw new Error(`News fehlgeschlagen: ${res.status}`);
  return res.json();
}
